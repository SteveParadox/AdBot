"""Ephemeral per-job forward proxy; DNS is validated and the socket is IP-pinned.

Browsers never resolve target hostnames themselves. TLS verification remains in the
browser/httpx. The server binds only to loopback and is closed with its context.
"""

import asyncio
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from .security import Policy, PolicyError


@asynccontextmanager
async def egress_proxy(policy: Policy, allow_method=None):
    clients: set[asyncio.Task] = set()

    async def handle(reader, writer):
        task = asyncio.current_task()
        clients.add(task)
        remote = None
        try:
            header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 10)
            method, target, version = header.split(b"\r\n", 1)[0].decode("ascii").split(" ")
            if method == "CONNECT":
                url = "https://" + target
            elif method in {"GET", "HEAD"} or (allow_method and allow_method(method, target)):
                url = target
            else:
                raise PolicyError("Read-only HTTP methods required")
            parsed = urlsplit(policy.check(url, navigation=False))
            ips = await policy.resolve(url)
            upstream, remote = await asyncio.wait_for(
                asyncio.open_connection(ips[0], parsed.port or (443 if parsed.scheme == "https" else 80)), 10
            )
            if method == "CONNECT":
                writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            else:
                path = parsed.path or "/"
                if parsed.query:
                    path += "?" + parsed.query
                headers = [f"{method} {path} {version}", f"Host: {parsed.netloc}", "Connection: close"]
                fields = {}
                for line in header.decode("latin1").split("\r\n")[1:]:
                    key, sep, value = line.partition(":")
                    if sep:
                        if key.lower() in fields:
                            raise PolicyError("Duplicate HTTP headers are not supported")
                        fields[key.lower()] = value.strip()
                if "transfer-encoding" in fields:
                    raise PolicyError("Chunked request bodies are unavailable")
                length = int(fields.get("content-length", "0"))
                if not 0 <= length <= 262144:
                    raise PolicyError("Request body exceeds limit")
                body = await asyncio.wait_for(reader.readexactly(length), 10) if length else b""
                if method not in {"GET", "HEAD"}:
                    headers.append(f"Content-Length: {len(body)}")
                for line in header.decode("latin1").split("\r\n")[1:]:
                    if line and line.partition(":")[0].lower() not in {
                        "host",
                        "connection",
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
        except (Exception, asyncio.CancelledError):
            try:
                writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
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
