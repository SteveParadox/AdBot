"""Ephemeral per-job forward proxy; DNS is validated and the socket is IP-pinned.

Browsers never resolve target hostnames themselves. TLS verification remains in the
browser/httpx. The server binds only to loopback and is closed with its context.
"""

import asyncio
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from .security import Policy, PolicyError
from .outbound import manager


@asynccontextmanager
async def egress_proxy(policy: Policy, allow_method=None, service="browser", session=None):
    import uuid
    session = session or uuid.uuid4().hex
    routing = manager()
    routing.policy(service)
    routing.start()
    clients: set[asyncio.Task] = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        clients.add(task)
        remote = None
        response_started = False
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            method, target, version = header.split(b"\r\n", 1)[0].decode("ascii").split(" ")
            if version not in {'HTTP/1.0','HTTP/1.1'}:
                raise PolicyError('Unsupported HTTP version')
            if method == "CONNECT":
                if any(c in target for c in '/?#') or urlsplit('//'+target).port is None:
                    raise PolicyError('CONNECT requires an authority and port')
                url = "https://" + target
            elif method in {"GET", "HEAD"} or (allow_method and allow_method(method, target)):
                url = target
            else:
                raise PolicyError("Read-only HTTP methods required")
            parsed = urlsplit(policy.check(url, navigation=False))
            if method != 'CONNECT' and parsed.scheme != 'http':
                raise PolicyError('HTTPS requires CONNECT')
            ips = await policy.resolve(url)
            upstream, remote = await routing.connect(service, session, ips, parsed.port or (443 if parsed.scheme == "https" else 80))
            if method == "CONNECT":
                response_started = True
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                headers = [f"{method} {path} {version}", f"Host: {parsed.netloc}", "Connection: close"]
                fields = {}
                for line in header.decode("latin1").split("\r\n")[1:]:
                    key, sep, value = line.partition(":")
                    if not line:
                        continue
                    if not sep or not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+",key) or any(ord(c)<32 and c!='\t' for c in value) or '\x7f' in value:
                        raise PolicyError('Malformed HTTP header')
                    if sep:
                        if key.lower() in fields:
                            raise PolicyError("Duplicate HTTP headers are not supported")
                        fields[key.lower()] = value.strip()
                if "transfer-encoding" in fields:
                    raise PolicyError("Chunked request bodies are unavailable")
                length = int(fields.get("content-length", "0"))
                if method in {'GET','HEAD'} and length:
                    raise PolicyError('Read-only request bodies are not supported')
                if not 0 <= length <= 262144:
                    raise PolicyError("Request body exceeds limit")
                body = await asyncio.wait_for(reader.readexactly(length), 10) if length else b""
                if method not in {"GET", "HEAD"}:
                    headers.append(f"Content-Length: {len(body)}")
                hop_headers = {v.strip().lower() for v in fields.get("connection", "").split(",")}
                for line in header.decode("latin1").split("\r\n")[1:]:
                    if line and line.partition(":")[0].lower() not in hop_headers | {
                        "host",
                        "forwarded",
                        "x-forwarded-for",
                        "x-real-ip",
                        "cf-connecting-ip",
                        "connection",
                        "keep-alive",
                        "upgrade",
                        "te",
                        "trailer",
                        "proxy-connection",
                        "proxy-authorization",
                        "transfer-encoding",
                        "content-length",
                    }:
                        headers.append(line)
                remote.write(("\r\n".join(headers) + "\r\n\r\n").encode("latin1") + body)
                await remote.drain()
            await writer.drain()

            async def pipe(source, destination):
                while chunk := await source.read(65536):
                    if destination is writer:
                        nonlocal response_started
                        response_started = True
                    destination.write(chunk)
                    await destination.drain()

            pipes = [asyncio.create_task(pipe(upstream, writer))]
            if method == "CONNECT":
                pipes.append(asyncio.create_task(pipe(reader, remote)))
            try:
                await asyncio.wait(pipes, timeout=180, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for p in pipes:
                    p.cancel()
                await asyncio.gather(*pipes, return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            try:
                if response_started:
                    return
                status = b'403 Forbidden' if isinstance(exc, PolicyError) else b'502 Bad Gateway'
                writer.write(b"HTTP/1.1 "+status+b"\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
            except Exception:
                pass
        finally:
            if remote:
                remote.close()
            writer.close()
            clients.discard(task)

    server = await asyncio.start_server(handle, "127.0.0.1", 0, limit=32768)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        await server.wait_closed()
        tasks = list(clients)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        routing.release(service, session)
