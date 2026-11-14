import asyncio
import subprocess
import sys
import time

from app.outbound import Manager
from test_outbound import configured


def test_proxy_validation_survives_optimized_python():
    code = """from app.outbound import Endpoint
from pydantic import ValidationError
import sys
try:
    Endpoint(id='a',url='socks5://proxy.test:1080',health_url='http://health.test/')
except ValidationError:
    sys.exit(0)
sys.exit(3)
"""
    result=subprocess.run([sys.executable,'-O','-c',code],capture_output=True,text=True)
    assert result.returncode==0, result.stderr


def test_older_success_does_not_clear_newer_circuit_failure():
    m=Manager(configured(),True)
    endpoint=m.config.endpoints[0]
    older=time.monotonic()-1
    m.record(endpoint,time.monotonic(),TimeoutError())
    deadline=m.states[endpoint.id]['retry_at']
    m.record(endpoint,older)
    assert m.states[endpoint.id]['retry_at']==deadline
    assert m.states[endpoint.id]['consecutive']==1


async def test_forward_proxy_rejects_ambiguous_framing_and_strips_hop_headers():
    from app.egress import egress_proxy
    captured=[]
    async def target(reader,writer):
        try:
            data=await reader.readuntil(b'\r\n\r\n')
            captured.append(data)
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
    server=await asyncio.start_server(target,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    class Policy:
        def check(self,url,**kwargs):
            return url
        async def resolve(self,url):
            return ['127.0.0.1']
    try:
        async with egress_proxy(Policy()) as proxy:
            from urllib.parse import urlsplit
            proxy_port=urlsplit(proxy).port
            for fields,body in [('Content-Length: 4\r\n',b'evil'),('Content-Length : 0\r\n',b''),('Transfer-Encoding: chunked\r\n',b'')]:
                reader,writer=await asyncio.open_connection('127.0.0.1',proxy_port)
                writer.write(f'GET http://127.0.0.1:{port}/ HTTP/1.1\r\nHost: test\r\n{fields}\r\n'.encode()+body)
                await writer.drain()
                assert (await reader.read()).startswith(b'HTTP/1.1 403')
                writer.close()
                await writer.wait_closed()
            reader,writer=await asyncio.open_connection('127.0.0.1',proxy_port)
            writer.write(f'GET http://127.0.0.1:{port}/ HTTP/1.1\r\nHost: test\r\nConnection: X-Leak\r\nX-Leak: private\r\nX-Forwarded-For: private\r\n\r\n'.encode())
            await writer.drain()
            assert (await reader.read()).startswith(b'HTTP/1.1 200')
            writer.close()
            await writer.wait_closed()
            assert len(captured)==1
            assert b'private' not in captured[0]
    finally:
        server.close()
        await server.wait_closed()

async def test_connect_shutdown_does_not_inject_http_into_tls_stream():
    from app.egress import egress_proxy
    from urllib.parse import urlsplit
    async def target(reader,writer):
        await reader.read()
        writer.close()
    server=await asyncio.start_server(target,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    class Policy:
        def check(self,url,**kwargs):
            return url
        async def resolve(self,url):
            return ['127.0.0.1']
    try:
        async with egress_proxy(Policy()) as proxy:
            reader,writer=await asyncio.open_connection('127.0.0.1',urlsplit(proxy).port)
            writer.write(f'CONNECT 127.0.0.1:{port} HTTP/1.1\r\nHost: test\r\n\r\n'.encode())
            await writer.drain()
            assert (await reader.readuntil(b'\r\n\r\n')).startswith(b'HTTP/1.1 200')
        assert await asyncio.wait_for(reader.read(),2) == b''
        writer.close()
        await writer.wait_closed()
    finally:
        server.close()
        await server.wait_closed()

async def test_monitor_heartbeat_is_not_blocked_by_slow_health_checks(monkeypatch):
    from app.config import settings
    published=asyncio.Event()
    blocked=asyncio.Event()
    class Redis:
        closed=False
        async def set(self,*args,**kwargs):
            published.set()
        async def aclose(self):
            self.closed=True
    redis=Redis()
    monkeypatch.setattr(settings(),'redis_url','redis://test.invalid')
    monkeypatch.setattr('redis.asyncio.Redis.from_url',lambda url:redis)
    m=Manager(configured(),True)
    async def slow_probe(endpoint):
        await blocked.wait()
    monkeypatch.setattr(m,'probe',slow_probe)
    try:
        m.start()
        await asyncio.wait_for(published.wait(),2)
    finally:
        await m.close()
    assert redis.closed
