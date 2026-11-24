"""Explicit proxy boundary, early abuse limits and safe response defaults."""
import hashlib
import ipaddress
import json
import logging
import re
import time
import uuid
from collections import OrderedDict

from starlette.responses import JSONResponse
from .config import settings


_extra_secrets = set()


def register_secrets(values):
    _extra_secrets.update(v for v in values if v)


class Redact(logging.Filter):
    def filter(self, record):
        cfg = settings()
        secrets = [*cfg.api_keys.split(","), *cfg.content_admin_keys.split(","),
                   cfg.ai_api_key.get_secret_value(), cfg.groq_api_key.get_secret_value(),
                   cfg.groq_secondary_api_key.get_secret_value(), cfg.openrouter_api_key.get_secret_value(),
                   cfg.google_api_key.get_secret_value(), cfg.nvidia_api_key.get_secret_value(),
                   cfg.ai_fallback_api_key.get_secret_value(), cfg.session_encryption_key.get_secret_value(),
                   cfg.database_url, cfg.redis_url]
        secrets += list(_extra_secrets)

        # Uvicorn's AccessFormatter unpacks these fields independently of msg.
        # Preserve their types and shape through repeated handler filters.
        if record.name == "uvicorn.access" and isinstance(record.args, tuple) and len(record.args) == 5:
            record.msg = self.redact(str(record.msg), secrets)
            record.args = tuple(self.redact(value, secrets) if isinstance(value, str) else value
                                for value in record.args)
        else:
            record.msg, record.args = self.redact(record.getMessage(), secrets), ()
        if isinstance(getattr(record, 'color_message', None), str):
            record.color_message = self.redact(record.color_message, secrets)
            if not record.args:
                # DefaultFormatter substitutes color_message after our filter.
                # Both templates must have the same already-rendered arguments.
                record.color_message = record.msg
        # Tracebacks can carry DSNs and user inputs; log exception class separately instead.
        record.exc_info, record.exc_text = None, None
        return True

    @staticmethod
    def redact(message, secrets):
        for value in sorted(secrets, key=len, reverse=True):
            if value and len(value) > 3:
                message = message.replace(value, "[redacted]")
        message = re.sub(r"(?i)Bearer\s+[^\s\"']+", "Bearer [redacted]", message)
        message = re.sub(
            r"""(?i)((?:password|api[_-]?key|token|secret)["']?\s*[:=]\s*)(["'])(?:\\[\s\S]|(?!\2)[^\\])*(?:\2|$)""",
            r'\1"[redacted]"', message)
        message = re.sub(r"(?i)(password|api[_-]?key|token|secret)([\"']?\s*[:=]\s*[\"']?)[^\s,\"'}]+",
                         r"\1\2[redacted]", message)
        message = re.sub(r"(\w+://)[^/@\s]+:[^/@\s]+@", r"\1[redacted]@", message)
        return message


def install_redaction():
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    loggers = [logging.getLogger(), *(logging.getLogger(name) for name in
               ("uvicorn", "uvicorn.error", "uvicorn.access"))]
    for logger in loggers:
        for handler in logger.handlers:
            if not any(isinstance(item, Redact) for item in handler.filters):
                handler.addFilter(Redact())


async def rate_hit(redis, key):
    # Counting and expiry must be atomic even if a worker disconnects mid-request.
    return await redis.eval(
        "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],120) end; return n",
        1, key)


class PrivacyMiddleware:
    def __init__(self, app):
        self.app = app
        self.windows = OrderedDict()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        cfg = settings()
        scope = dict(scope)
        request_id = uuid.uuid4().hex
        scope["state"] = {**scope.get("state", {}), "request_id": request_id}
        headers = {k.lower(): v for k, v in scope['headers']}
        peer = (scope.get('client') or ('unknown', 0))[0]
        trusted = False
        try:
            trusted = any(ipaddress.ip_address(peer) in ipaddress.ip_network(c.strip())
                          for c in cfg.trusted_proxy_cidrs.split(',') if c.strip())
        except ValueError:
            pass
        # Only a sanitizing final proxy may set these single-value headers. XFF and CF headers
        # are deliberately ignored; the edge must validate Cloudflare's network or tunnel first.
        if trusted:
            try:
                client = str(ipaddress.ip_address(headers.get(b'x-real-ip', b'').decode()))
                scope['client'] = (client, 0)
            except ValueError:
                pass
            proto = headers.get(b'x-forwarded-proto', b'').decode('ascii', errors='replace')
            if proto in {'http', 'https'}:
                scope['scheme'] = proto
        scope['headers'] = [(k, v) for k, v in scope['headers'] if not
                            k.lower().startswith((b'x-forwarded-', b'cf-')) and k.lower() not in
                            {b'forwarded', b'x-real-ip'}]
        started = False

        async def secured(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
                values = [(k, v) for k, v in message.get('headers', []) if k.lower() not in
                          {b'server', b'x-powered-by', b'cache-control', b'content-security-policy', b'x-request-id'}]
                values += [(b'x-request-id', request_id.encode()), (b'cache-control', b'no-store'), (b'x-content-type-options', b'nosniff'),
                           (b'referrer-policy', b'no-referrer'),
                           (b'permissions-policy', b'camera=(), microphone=(), geolocation=(), payment=()'),
                           (b'content-security-policy', b"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")]
                if cfg.environment != 'production' and scope['path'] in {'/docs', '/redoc'}:
                    values = [(k, v) for k, v in values if k != b'content-security-policy']
                    values.append((b'content-security-policy', b"default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' https://fastapi.tiangolo.com; frame-ancestors 'none'"))
                if cfg.hsts_enabled and scope['scheme'] == 'https':
                    values.append((b'strict-transport-security', b'max-age=31536000'))
                message['headers'] = values
            await send(message)

        async def reject(code, detail):
            await JSONResponse({'detail': detail}, code, headers={'Retry-After': '60'} if code == 429 else None)(scope, receive, secured)

        if cfg.enforce_https and scope['scheme'] != 'https' and scope['path'] not in {'/api/health', '/api/ready'}:
            return await reject(426, 'HTTPS required')
        if scope['path'].startswith('/api/'):
            client = (scope.get('client') or ('unknown', 0))[0]
            key = hashlib.sha256(client.encode()).hexdigest()
            redis = getattr(scope['app'].state, 'redis', None)
            try:
                if redis:
                    bucket = f'adbot:ingress:{key}:{int(time.time() // 60)}'
                    # Atomic counter with expiration, including if a worker disconnects.
                    hits = await rate_hit(redis, bucket)
                else:
                    now = time.monotonic()
                    while self.windows and next(iter(self.windows.values()))[1] <= now:
                        self.windows.popitem(last=False)
                    if key not in self.windows and len(self.windows) >= 10000:
                        return await reject(429, 'Rate limit capacity reached; retry later')
                    hits, expires = self.windows.get(key, (0, now + 60))
                    hits += 1
                    self.windows[key] = (hits, expires)
                if hits > cfg.public_rate_per_minute:
                    return await reject(429, 'Rate limit exceeded; retry in one minute')
            except Exception:
                return await reject(503, 'Service temporarily unavailable')
        try:
            await self.app(scope, receive, secured)
        except Exception as exc:
            logging.getLogger('adbot.security').error(json.dumps({'event': 'request_failed', 'request_id': request_id, 'timestamp': time.time(), 'error_type': type(exc).__name__}))
            if not started:
                await reject(500, 'Service temporarily unavailable')
            else:
                # A second response cannot repair a partial stream. Let the server terminate it
                # without attaching the sensitive original exception or traceback.
                raise RuntimeError('Response stream interrupted') from None
