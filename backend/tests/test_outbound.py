import asyncio
import json
import logging
import ssl
from pathlib import Path

import pytest
from pydantic import ValidationError
from app.outbound import Endpoint, Manager, OutboundUnavailable, ProviderPolicy, Routing, Service
from app.config import settings
from app.privacy import Redact


def configured(strategy='round_robin', **kwargs):
    return Routing(endpoints=[Endpoint(id=k,url='http://127.0.0.1:12345',health_url='https://health.example.invalid/') for k in ['a','b']],
                   services={'browser':Service(endpoints=['a','b'],strategy=strategy,stable=False,allow_rotation=True,**kwargs)})


def test_strategies(monkeypatch):
    m=Manager(configured(),True)
    assert [m.select('browser','job').id for _ in range(4)] == ['a','b','a','b']
    m=Manager(configured('sticky'),True)
    assert len({m.select('browser','job').id for _ in range(4)}) == 1
    m=Manager(configured('random'),True)
    monkeypatch.setattr('app.outbound.random.choice',lambda items:items[-1])
    assert m.select('browser','job').id == 'b'
    m=Manager(configured('health'),True)
    m.states['a']['latency_ms']=100
    m.states['b']['latency_ms']=20
    assert m.select('browser','job').id == 'b'
    m=Manager(configured('scheduled'),True)
    import types
    monkeypatch.setattr('app.outbound.time',types.SimpleNamespace(monotonic=lambda:300,time=lambda:300))
    first=m.select('browser','job').id
    assert m.select('browser','job').id == first
    monkeypatch.setattr('app.outbound.time',types.SimpleNamespace(monotonic=lambda:600,time=lambda:600))
    assert m.select('browser','job').id != first


def test_stable_and_config_guards():
    with pytest.raises(ValidationError):
        Service(endpoints=['a','b'])
    with pytest.raises(ValidationError):
        Service(endpoints=['a'],allow_rotation=True)
    with pytest.raises(ValidationError):
        Service(endpoints=['a'],strategy='random',stable=False)
    for url in ['socks5://proxy.test:1080','http://user:secret@proxy.test:80','http://proxy.test:80/path','http://proxy.test:80\r\nX:bad']:
        with pytest.raises(ValidationError):
            Endpoint(id='a',url=url,health_url='https://health.test/')
    with pytest.raises(ValidationError):
        Endpoint(id='a',url='http://proxy.test:80',username='user',password='secret',health_url='https://health.test/')
    m=Manager(configured(),False)
    assert m.select('browser','job') is None
    with pytest.raises(OutboundUnavailable):
        Manager(configured(),True).policy('ai')


async def test_failover_and_no_direct_fallback(monkeypatch):
    m=Manager(configured(allow_failover=True),True)
    calls=[]
    async def via(endpoint,*args):
        calls.append(endpoint.id)
        if endpoint.id == 'a':
            raise TimeoutError()
        return 'reader','writer'
    monkeypatch.setattr(m,'via',via)
    assert await m.connect('browser','job',['8.8.8.8'],443) == ('reader','writer')
    assert calls == ['a','b'] and m.failovers == 1
    assert m.states['a']['timeouts'] == 1 and m.states['a']['retry_at'] > 0
    m=Manager(configured(),True)
    monkeypatch.setattr(m,'via',via)
    with pytest.raises(OutboundUnavailable):
        await m.connect('browser','job',['8.8.8.8'],443)
    assert m.states['a']['failures'] == 1
    with pytest.raises(OutboundUnavailable):
        m.select('browser','job')
    m.states['a']['retry_at']=0
    assert m.select('browser','job').id in {'a','b'}


async def test_local_connect_proxy_auth_and_pinned_address():
    captured=[]
    async def handle(reader,writer):
        captured.append(await reader.readuntil(b'\r\n\r\n'))
        writer.write(b'HTTP/1.1 200 OK\r\n\r\n')
        await writer.drain()
        data=await reader.read(16)
        writer.write(data)
        await writer.drain()
        writer.close()
    server=await asyncio.start_server(handle,'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    endpoint=Endpoint(id='local',url=f'http://127.0.0.1:{port}',username='approved',password='test-proxy-secret',
                      allow_plaintext_auth=True,health_url='https://health.test/')
    m=Manager(Routing(endpoints=[endpoint],services={'browser':Service(endpoints=['local'])}),True)
    try:
        reader,writer=await m.connect('browser','job',['8.8.8.8'],443)
        writer.write(b'hello')
        await writer.drain()
        assert await reader.read(5) == b'hello'
        writer.close()
        await writer.wait_closed()
        assert captured[0].startswith(b'CONNECT 8.8.8.8:443 HTTP/1.1')
        assert b'Proxy-Authorization: Basic ' in captured[0]
        assert 'test-proxy-secret' not in json.dumps(m.snapshot())
        record=logging.LogRecord('test',40,'',0,'credential test-proxy-secret',(),None)
        Redact().filter(record)
        assert 'test-proxy-secret' not in record.getMessage()
        import base64
        encoded = base64.b64encode(b'approved:test-proxy-secret').decode()
        record = logging.LogRecord('test',40,'',0,'Proxy-Authorization: Basic '+encoded,(),None)
        Redact().filter(record)
        assert encoded not in record.getMessage()
    finally:
        server.close()
        await server.wait_closed()


async def test_provider_private_dns_and_origin_validation():
    from app.security import PolicyError
    with pytest.raises(PolicyError):
        ProviderPolicy('https://api.example.invalid:443/v1',False).check('https://evil.test/v1')
    assert ProviderPolicy('https://api.example.invalid:443/v1',False).check('https://api.example.invalid/v1')
    with pytest.raises(PolicyError):
        await ProviderPolicy('http://127.0.0.1:8766',False).resolve('http://127.0.0.1:8766/v1')
    assert await ProviderPolicy('http://127.0.0.1:8766',True).resolve('http://127.0.0.1:8766/v1') == ['127.0.0.1']


async def test_probe_recovery_and_tls_checks(monkeypatch):
    m=Manager(configured(),True)
    endpoint=m.config.endpoints[0]
    m.states['a']['failures']=1
    m.states['a']['consecutive']=1
    m.states['a']['retry_at']=1
    async def resolve(self,url):
        return ['8.8.8.8']
    monkeypatch.setattr(ProviderPolicy,'resolve',resolve)
    class Writer:
        async def start_tls(self,context,server_hostname):
            assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
        def write(self,data):
            assert b'HEAD ' in data
        async def drain(self):
            pass
        def close(self):
            pass
    class Reader:
        async def readline(self):
            return b'HTTP/1.1 200 OK\r\n'
    async def via(*args):
        return Reader(),Writer()
    monkeypatch.setattr(m,'via',via)
    await m.probe(endpoint)
    assert m.states['a']['retry_at'] == 0 and m.states['a']['last_success']
    assert m.states['a']['recovery_attempts'] == 1


def test_monitor_authorization(client,monkeypatch):
    from conftest import KEY, OTHER_AUTH
    monkeypatch.setattr(settings(),'content_admin_keys',KEY)
    assert client.get('/api/admin/network',headers=OTHER_AUTH).status_code == 403
    response=client.get('/api/admin/network')
    assert response.status_code == 200 and response.json()['scope'] == 'this-process-only'
    assert 'password' not in response.text
    client.headers.clear()
    assert client.get('/api/admin/network').status_code == 401


def test_tunnel_configuration():
    root=Path(__file__).parents[2]
    conf=(root/'docker/security/tunnel-ingress.conf').read_text()
    assert 'geo $realip_remote_addr' in conf
    assert '172.30.50.2/32 1' in conf and 'return 403' in conf
    assert 'X-Forwarded-Proto https' in conf
    assert 'frontend:8081' in (root/'docker/security/tunnel.example.yml').read_text()

async def test_enabled_model_client_uses_real_proxy_and_validated_tls(tmp_path,monkeypatch):
    import datetime
    import ipaddress
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
    from pydantic import SecretStr
    from app.outbound import model_clients
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'provider.example.invalid')])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
          .serial_number(x509.random_serial_number()).not_valid_before(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(minutes=1))
          .not_valid_after(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=1))
          .add_extension(x509.SubjectAlternativeName([x509.DNSName('provider.example.invalid'), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]),critical=False)
          .sign(key,hashes.SHA256()))
    cert_path=tmp_path/'cert.pem'
    key_path=tmp_path/'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path,key_path)
    target_headers=[]
    async def target(reader,writer):
        target_headers.append(await reader.readuntil(b'\r\n\r\n'))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 11\r\nConnection: close\r\n\r\n{"ok":true}')
        await writer.drain()
        writer.close()
    destination=await asyncio.start_server(target,'127.0.0.1',0,ssl=tls)
    target_port=destination.sockets[0].getsockname()[1]
    connects=[]
    async def relay(reader,writer):
        raw=await reader.readuntil(b'\r\n\r\n')
        connects.append(raw)
        upstream,remote=await asyncio.open_connection('127.0.0.1',target_port)
        writer.write(b'HTTP/1.1 200 OK\r\n\r\n')
        await writer.drain()
        async def pipe(source,dest):
            while data:=await source.read(65536):
                dest.write(data)
                await dest.drain()
        tasks=[asyncio.create_task(pipe(reader,remote)),asyncio.create_task(pipe(upstream,writer))]
        try:
            await asyncio.wait(tasks,timeout=10,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            writer.close()
            remote.close()
    proxy=await asyncio.start_server(relay,'127.0.0.1',0,ssl=tls)
    monkeypatch.setenv('SSL_CERT_FILE',str(cert_path))
    proxy_port=proxy.sockets[0].getsockname()[1]
    endpoint=Endpoint(id='test',url=f'https://127.0.0.1:{proxy_port}',health_url='https://health.test/')
    m=Manager(Routing(endpoints=[endpoint],services={'ai':Service(endpoints=['test'])}),True)
    monkeypatch.setattr('app.outbound.manager',lambda:m)
    monkeypatch.setattr('app.egress.manager',lambda:m)
    monkeypatch.setattr(m,'start',lambda:None)
    monkeypatch.setattr(settings(),'ai_provider','openai_compatible')
    async def resolve(self,url):
        self.check(url)
        return ['127.0.0.1']
    monkeypatch.setattr(ProviderPolicy,'resolve',resolve)
    try:
        base=f'https://provider.example.invalid:{target_port}'
        async with model_clients([(base,SecretStr(''),'test')],trust_env=False,follow_redirects=False,
                                 timeout=5,verify=ssl.create_default_context(cafile=str(cert_path))) as clients:
            response=await clients[0].post(base+'/chat/completions',json={})
            assert response.json()=={'ok':True}
        assert connects[0].startswith(f'CONNECT 127.0.0.1:{target_port} '.encode())
        assert b'proxy-authorization' not in target_headers[0].lower()
        assert target_headers[0].lower().count(b'user-agent:') == 1
        assert settings().user_agent_default.encode() in target_headers[0]
        monkeypatch.delenv('SSL_CERT_FILE')
        with pytest.raises(ssl.SSLCertVerificationError):
            await m.via(endpoint,'127.0.0.1',target_port)
    finally:
        proxy.close()
        destination.close()
        await proxy.wait_closed()
        await destination.wait_closed()

async def test_retry_limit_and_monitor_lifecycle(monkeypatch):
    m=Manager(configured(allow_failover=True),True)
    monkeypatch.setattr(settings(),'outbound_max_retries',0)
    attempts=[]
    async def failed(endpoint,*args):
        attempts.append(endpoint.id)
        raise TimeoutError()
    monkeypatch.setattr(m,'via',failed)
    with pytest.raises(OutboundUnavailable):
        await m.connect('browser','job',['8.8.8.8'],443)
    assert attempts == ['a']
    event=asyncio.Event()
    probes=[]
    async def probe(endpoint):
        probes.append(endpoint.id)
        event.set()
    monkeypatch.setattr(m,'probe',probe)
    m.states['a']['retry_at']=0
    m.start()
    await asyncio.wait_for(event.wait(),1)
    await m.close()
    assert probes and m.task is None


def test_sticky_release_and_rotating_fail_closed():
    m=Manager(configured('sticky'),True)
    selected=m.select('browser','job')
    m.states[selected.id]['retry_at']=float('inf')
    with pytest.raises(OutboundUnavailable):
        m.select('browser','job')
    m.release('browser','job')
    assert ('browser','job') not in m.sticky
    m=Manager(configured('sticky',allow_failover=True),True)
    selected=m.select('browser','job')
    m.states[selected.id]['retry_at']=float('inf')
    assert m.select('browser','job').id != selected.id

def test_private_configuration_errors_fail_closed(tmp_path,monkeypatch):
    private=tmp_path/'private.json'
    private.write_text('{"password":"sensitive-config-value", broken')
    monkeypatch.setattr(settings(),'outbound_proxy_config_path',private)
    with pytest.raises(ValueError) as error:
        Manager(enabled=True)
    assert 'sensitive-config-value' not in str(error.value)
    assert error.value.__suppress_context__
