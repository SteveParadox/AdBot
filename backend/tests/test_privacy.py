import logging
import subprocess
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.config import settings
from app.privacy import PrivacyMiddleware, Redact


def surface():
    app = FastAPI()
    app.add_middleware(PrivacyMiddleware)

    @app.get('/api/check')
    def check(request: __import__('starlette.requests', fromlist=['Request']).Request):
        return {'client': request.client.host, 'scheme': request.url.scheme,
                'forwarded': request.headers.get('x-forwarded-for')}

    @app.get('/api/fail')
    def fail():
        raise RuntimeError('password=do-not-disclose')

    return app


def test_untrusted_forwarding(monkeypatch):
    monkeypatch.setattr(settings(), 'trusted_proxy_cidrs', '')
    with TestClient(surface(), client=('198.51.100.5',123)) as c:
        r = c.get('/api/check',headers={'X-Real-IP':'1.1.1.1','X-Forwarded-For':'1.1.1.1',
                                      'CF-Connecting-IP':'1.1.1.1','X-Forwarded-Proto':'https'})
        assert r.json() == {'client':'198.51.100.5','scheme':'http','forwarded':None}


def test_trusted_proxy_https(monkeypatch):
    monkeypatch.setattr(settings(), 'trusted_proxy_cidrs', '10.0.0.4/32')
    monkeypatch.setattr(settings(), 'enforce_https', True)
    monkeypatch.setattr(settings(), 'hsts_enabled', True)
    with TestClient(surface(), client=('10.0.0.4',123)) as c:
        assert c.get('/api/check').status_code == 426
        r = c.get('/api/check',headers={'X-Real-IP':'198.51.100.6','X-Forwarded-Proto':'https'})
        assert r.json()['client'] == '198.51.100.6'
        assert r.json()['scheme'] == 'https'
        assert r.headers['strict-transport-security'] == 'max-age=31536000'
        assert 'set-cookie' not in r.headers
        assert c.get('/api/check',headers={'X-Real-IP':'invalid','X-Forwarded-Proto':'https'}).json()['client'] == '10.0.0.4'


def test_early_rate_limit_and_headers(monkeypatch):
    monkeypatch.setattr(settings(), 'public_rate_per_minute', 1)
    with TestClient(surface()) as c:
        assert c.get('/api/check').status_code == 200
        r = c.get('/api/check')
        assert r.status_code == 429
        assert r.headers['retry-after'] == '60'
        assert r.headers['cache-control'] == 'no-store'
        assert "frame-ancestors 'none'" in r.headers['content-security-policy']
        assert 'camera=()' in r.headers['permissions-policy']
        assert 'strict-transport-security' not in r.headers


def test_safe_errors_and_redaction():
    with TestClient(surface()) as c:
        r = c.get('/api/fail')
        assert r.status_code == 500
        assert 'do-not-disclose' not in r.text
    record = logging.LogRecord('test',40,'',0,'Bearer abc123 password=hello https://user:pass@db/private',(),None)
    Redact().filter(record)
    assert 'abc123' not in record.getMessage()
    assert 'hello' not in record.getMessage()
    assert 'user:pass' not in record.getMessage()


def test_validation_and_host_boundaries(client):
    r = client.post('/api/websites',json={'name':'secret-input'})
    assert r.status_code == 422
    assert 'secret-input' not in r.text
    assert 'input' not in r.json()['detail'][0]
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code == 400
    r = client.options('/api/websites',headers={'Origin':'https://evil.example','Access-Control-Request-Method':'POST'})
    assert 'access-control-allow-origin' not in r.headers


def test_production_docs_hidden():
    result = subprocess.run([sys.executable,'-c',
        'from app.config import settings; settings().environment="production"; from app.main import app; '
        'assert app.docs_url is None and app.redoc_url is None and app.openapi_url is None'],capture_output=True,text=True)
    assert result.returncode == 0, result.stderr


def test_deployment_guards():
    from pathlib import Path
    root = Path(__file__).parents[2]
    nginx = (root/'docker/nginx.conf').read_text()
    assert 'proxy_set_header X-Real-IP $remote_addr' in nginx
    assert 'proxy_set_header X-Forwarded-For ""' in nginx
    assert 'server_tokens off' in nginx and 'map|env' in nginx
    assert '--no-proxy-headers' in (root/'docker/backend.Dockerfile').read_text()
    assert 'npm run build' in (root/'docker/frontend.Dockerfile').read_text()
    assert 'npm", "run", "dev' not in (root/'docker/frontend.Dockerfile').read_text()

def test_distributed_limit_and_outage(monkeypatch):
    monkeypatch.setattr(settings(), 'public_rate_per_minute', 1)

    class Redis:
        hits = 0

        async def eval(self, script, count, key):
            assert 'EXPIRE' in script and count == 1
            assert '198.51.100.9' not in key
            self.hits += 1
            return self.hits

    app = surface()
    app.state.redis = Redis()
    with TestClient(app, client=('198.51.100.9',123)) as c:
        assert c.get('/api/check').status_code == 200
        assert c.get('/api/check').status_code == 429

    class Unavailable:
        async def eval(self, *args):
            raise RuntimeError('redis://private:password@internal')

    app.state.redis = Unavailable()
    with TestClient(app) as c:
        response = c.get('/api/check')
        assert response.status_code == 503
        assert 'internal' not in response.text


def test_oversize_response_is_hardened(client):
    r = client.post('/api/websites', content=b'x' * 262145)
    assert r.status_code == 413
    assert r.headers['cache-control'] == 'no-store'
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']

def test_readiness_hides_dependency_details(client, monkeypatch):
    from app import main

    def unavailable():
        raise RuntimeError('postgresql://secret@private-db')

    monkeypatch.setattr(main, 'Session', unavailable)
    response = client.get('/api/ready')
    assert response.status_code == 503
    assert response.json() == {'detail': 'Service temporarily unavailable'}

def test_log_handlers_and_configuration_guards(monkeypatch):
    import io
    import pytest
    from pydantic import ValidationError
    from app.config import Settings
    from app.privacy import install_redaction

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger = logging.getLogger('uvicorn.error')
    monkeypatch.setattr(logger, 'handlers', [handler])
    monkeypatch.setattr(logger, 'propagate', False)
    install_redaction()
    logger.error('password=sensitive-log-value')
    assert 'sensitive-log-value' not in stream.getvalue()
    assert '[redacted]' in stream.getvalue()
    assert logging.getLogger('httpx').level == logging.WARNING
    with pytest.raises(ValidationError) as error:
        Settings(trusted_proxy_cidrs='0.0.0.0/0')
    assert 'input_value' not in str(error.value)
    with pytest.raises(ValidationError):
        Settings(hsts_enabled=True, enforce_https=False)

def test_environment_and_production_allowlist_fail_closed():
    import pytest
    from pydantic import ValidationError
    from app.config import Settings
    with pytest.raises(ValidationError):
        Settings(environment='prod')
    with pytest.raises(ValidationError):
        Settings(environment='production', database_url='postgresql://unused', redis_url='redis://unused',
                 fixture_mode=False, authorized_domains=' , ')


def test_quoted_secret_redaction():
    for message in ['password="two secret words"', "secret='two secret words'", '{"api_key": "two secret words"}', 'password="two secret words']:
        record = logging.LogRecord('test',40,'',0,message,(),None)
        Redact().filter(record)
        assert 'secret words' not in record.getMessage()
        assert '[redacted]' in record.getMessage()


async def test_partial_stream_failure_is_not_swallowed():
    import pytest
    async def broken(scope, receive, send):
        await send({'type':'http.response.start','status':200,'headers':[]})
        await send({'type':'http.response.body','body':b'partial','more_body':True})
        raise ValueError('private stream credentials')
    sent = []
    async def send(message):
        sent.append(message)
    async def receive():
        return {'type':'http.disconnect'}
    middleware = PrivacyMiddleware(broken)
    with pytest.raises(RuntimeError, match='^Response stream interrupted$') as error:
        await middleware({'type':'http','path':'/stream','scheme':'http','headers':[],
                          'client':('198.51.100.1',0)},receive,send)
    assert error.value.__suppress_context__
    assert sum(m['type']=='http.response.start' for m in sent) == 1


def test_missing_assets_cannot_fall_back_to_cached_html():
    from pathlib import Path
    config = (Path(__file__).parents[2]/'docker/nginx.conf').read_text()
    assert 'location /assets/ { try_files $uri =404; }' in config
    assert '~^200:/assets/' in config

async def test_owner_limit_uses_atomic_expiry_and_safe_outage(monkeypatch):
    import pytest
    from starlette.requests import Request
    from fastapi import HTTPException
    from conftest import KEY
    from app.api_support import authenticate

    class Redis:
        count = 0
        async def eval(self, script, count, key):
            assert 'EXPIRE' in script and key.startswith('adbot:rate:')
            self.count += 1
            return self.count

    app = FastAPI()
    app.state.redis = Redis()
    request = Request({'type':'http','headers':[], 'app':app})
    monkeypatch.setattr(settings(), 'rate_per_minute', 1)
    assert await authenticate(request, 'Bearer ' + KEY)
    with pytest.raises(HTTPException) as limit:
        await authenticate(request, 'Bearer ' + KEY)
    assert limit.value.status_code == 429

    class Unavailable:
        async def eval(self, *args):
            raise RuntimeError('private redis configuration')

    app.state.redis = Unavailable()
    with pytest.raises(HTTPException) as outage:
        await authenticate(request, 'Bearer ' + KEY)
    assert outage.value.status_code == 503
    assert outage.value.detail == 'Service temporarily unavailable'
