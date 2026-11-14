"""Operator-configured egress. Destination validation always precedes upstream selection."""
import asyncio
import base64
import json
import logging
import random
import ssl
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .config import settings
from .security import PolicyError, normalize

log = logging.getLogger('adbot.egress')


class Endpoint(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,40}$')
    url: str
    username: SecretStr = SecretStr('')
    password: SecretStr = SecretStr('')
    allow_plaintext_auth: bool = False
    health_url: str

    @model_validator(mode='after')
    def validate_endpoint(self):
        try:
            p = urlsplit(self.url)
            invalid = (
                p.scheme not in {'http', 'https'} or not p.hostname or not p.port
                or p.username is not None or p.password is not None or p.query or p.fragment or p.path not in {'', '/'}
                or any(ord(c) <= 32 for c in self.url) or '\\' in self.url
                or any(ord(c) < 32 for c in self.username.get_secret_value()+self.password.get_secret_value())
                or ':' in self.username.get_secret_value()
                or (p.scheme != 'https' and self.username.get_secret_value() and not self.allow_plaintext_auth)
            )
            h = urlsplit(normalize(self.health_url))
            if invalid or h.scheme != 'https' or h.port not in {None,443}:
                raise ValueError('Unsafe proxy configuration')
        except (ValueError, AssertionError):
            raise ValueError('Invalid approved proxy endpoint or health URL') from None
        return self


class Service(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['required', 'direct'] = 'required'
    endpoints: list[str] = Field(default_factory=list)
    strategy: Literal['round_robin','random','sticky','health','scheduled'] = 'sticky'
    stable: bool = True
    allow_rotation: bool = False
    allow_failover: bool = False
    rotation_seconds: int = Field(300, ge=30)

    @model_validator(mode='after')
    def stable_route(self):
        if self.stable and self.mode == 'required' and len(self.endpoints) != 1:
            raise ValueError('Stable services require one fixed endpoint across workers and restarts')
        if self.stable and (self.allow_rotation or self.allow_failover):
            raise ValueError('Stable services cannot rotate or fail over to another IP')
        if self.strategy != 'sticky' and not self.allow_rotation:
            raise ValueError('Rotation requires explicit service permission')
        if self.mode == 'required' and not self.endpoints:
            raise ValueError('Required routing needs approved endpoints')
        return self


class Routing(BaseModel):
    model_config = ConfigDict(extra='forbid')
    endpoints: list[Endpoint]
    services: dict[Literal['browser','ai','ai_local'], Service]

    @model_validator(mode='after')
    def references(self):
        ids = [e.id for e in self.endpoints]
        if len(ids) != len(set(ids)) or any(set(s.endpoints)-set(ids) for s in self.services.values()):
            raise ValueError('Duplicate or unknown proxy identifiers')
        return self


class OutboundUnavailable(RuntimeError):
    pass


class Manager:
    def __init__(self, config=None, enabled=None):
        self.enabled = settings().outbound_proxy_enabled if enabled is None else enabled
        self.config = config
        if self.enabled and config is None:
            try:
                raw = Path(settings().outbound_proxy_config_path).read_text(encoding='utf-8')
                self.config = Routing.model_validate_json(raw)
            except Exception:
                raise ValueError('Invalid outbound routing configuration; check the private operator file') from None
        if self.config:
            from .privacy import register_secrets
            register_secrets([value for e in self.config.endpoints for value in
                              (e.username.get_secret_value(), e.password.get_secret_value(),
                               base64.b64encode((e.username.get_secret_value()+":"+e.password.get_secret_value()).encode()).decode())])
        self.states = {e.id: dict(failures=0, consecutive=0, timeouts=0, successes=0, latency_ms=None,
                                 last_success=None, retry_at=0, recovery_attempts=0, in_flight=False, last_failure=0)
                       for e in self.config.endpoints} if self.config else {}
        self.sticky = OrderedDict()
        self.bound = set()
        self.counters = {}
        self.failovers = 0
        self.task = None
        self.instance = uuid.uuid4().hex

    def policy(self, service):
        if not self.enabled:
            return Service(mode='direct')
        policy = self.config.services.get(service)
        if policy is None:
            raise OutboundUnavailable('No approved egress policy for this service')
        return policy

    def select(self, service, session):
        p = self.policy(service)
        if p.mode == 'direct':
            return None
        now = time.monotonic()
        key = (service, session)
        previous = self.sticky.get(key)
        if previous and self.states[previous]['retry_at'] > now:
            if p.stable or not p.allow_failover:
                raise OutboundUnavailable('Assigned egress route is unavailable')
            self.sticky.pop(key, None)
            previous = None
        if previous and (key in self.bound or p.stable or not p.allow_rotation or p.strategy == 'sticky'):
            if self.states[previous]['retry_at'] > now:
                raise OutboundUnavailable('Stable egress route is unavailable')
            return next(e for e in self.config.endpoints if e.id == previous)
        healthy = [e for e in self.config.endpoints if e.id in p.endpoints and
                   self.states[e.id]['retry_at'] <= now]
        if not healthy:
            raise OutboundUnavailable('No healthy approved proxy')
        if p.strategy == 'random':
            selected = random.choice(healthy)
        elif p.strategy == 'health':
            selected = min(healthy, key=lambda e: self.states[e.id]['latency_ms'] if self.states[e.id]['latency_ms'] is not None else float('inf'))
        elif p.strategy == 'scheduled':
            selected = healthy[int(now // p.rotation_seconds) % len(healthy)]
        else:
            count = self.counters.get(service,0)
            selected = healthy[count % len(healthy)]
            self.counters[service] = count + 1
        if key not in self.sticky and len(self.sticky) >= 10000:
            raise OutboundUnavailable('Egress session capacity reached')
        self.sticky[key] = selected.id
        return selected

    def bind(self, service, session):
        endpoint = self.select(service,session)
        if endpoint:
            self.bound.add((service,session))
        return endpoint.id if endpoint else None

    def release(self, service, session):
        self.bound.discard((service,session))
        self.sticky.pop((service,session),None)

    def record(self, endpoint, started, error=None):
        s = self.states[endpoint.id]
        s['in_flight'] = False
        if error is None:
            if started >= s['last_failure']:
                s.update(consecutive=0, retry_at=0)
            s.update(latency_ms=round((time.monotonic()-started)*1000), last_success=time.time())
            s['successes'] += 1
        else:
            s['last_failure'] = time.monotonic()
            s['failures'] += 1
            s['consecutive'] += 1
            s['timeouts'] += isinstance(error, (TimeoutError, asyncio.TimeoutError))
            s['retry_at'] = time.monotonic()+min(300, 2**min(s['consecutive'],8))*random.uniform(.8,1.2)
        log.info(json.dumps({'event':'egress_connection','endpoint':endpoint.id,'ok':error is None}))

    async def via(self, endpoint, host, port):
        p = urlsplit(endpoint.url)
        writer = None
        try:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(
                p.hostname,p.port,ssl=ssl.create_default_context() if p.scheme=='https' else None,
                limit=32768),settings().outbound_connect_timeout_seconds)
            authority = f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
            auth = ''
            if endpoint.username.get_secret_value():
                token = base64.b64encode((endpoint.username.get_secret_value()+':'+endpoint.password.get_secret_value()).encode()).decode()
                auth = 'Proxy-Authorization: Basic '+token+'\r\n'
            writer.write((f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n'+auth+'\r\n').encode('ascii'))
            await writer.drain()
            reply = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),settings().outbound_request_timeout_seconds)
            if reply.split(b'\r\n',1)[0].split()[1] != b'200':
                raise OutboundUnavailable('Approved proxy refused the connection')
            return reader,writer
        except BaseException:
            if writer:
                writer.close()
            raise

    async def connect(self, service, session, addresses, port):
        p = self.policy(service)
        if p.mode == 'direct':
            return await asyncio.wait_for(asyncio.open_connection(addresses[0],port),settings().outbound_connect_timeout_seconds)
        for attempt in range(settings().outbound_max_retries+1):
            endpoint = self.select(service,session)
            started = time.monotonic()
            try:
                result = await self.via(endpoint,addresses[0],port)
                self.record(endpoint,started)
                return result
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.record(endpoint,started,exc)
                if p.stable or not p.allow_failover or attempt >= settings().outbound_max_retries:
                    break
                self.failovers += 1
                log.info(json.dumps({'event':'egress_failover_attempt','service':service,'failed_endpoint':endpoint.id,'attempt':attempt+1}))
                await asyncio.sleep(min(2, .1*2**attempt)*random.uniform(.8,1.2))
        raise OutboundUnavailable('Approved egress is unavailable; direct fallback is prohibited') from None

    def snapshot(self):
        return {'instance':self.instance,'enabled':self.enabled,'failovers':self.failovers,
                'services':{k:{'mode':v.mode,'strategy':v.strategy,'stable':v.stable} for k,v in
                            (self.config.services.items() if self.config else [])},
                'endpoints':[{'id':key,**{k:v for k,v in s.items() if k not in {'retry_at','in_flight','last_failure'}},
                              'status':'open' if s['retry_at']>time.monotonic() else 'eligible'} for key,s in self.states.items()]}

    async def probe(self, endpoint):
        p = urlsplit(endpoint.health_url)
        started = time.monotonic()
        writer = None
        self.states[endpoint.id]['in_flight'] = True
        self.states[endpoint.id]['recovery_attempts'] += 1
        try:
            ips = await ProviderPolicy(endpoint.health_url,False).resolve(endpoint.health_url)
            reader,writer = await self.via(endpoint,ips[0],443)
            await asyncio.wait_for(writer.start_tls(ssl.create_default_context(),server_hostname=p.hostname),settings().outbound_connect_timeout_seconds)
            path = p.path or '/'
            if p.query:
                path += '?'+p.query
            from .user_agents import resolve
            identity = resolve('proxy_health')
            writer.write(f'HEAD {path} HTTP/1.1\r\nHost: {p.hostname}\r\nConnection: close\r\nUser-Agent: {identity}\r\n\r\n'.encode('ascii'))
            await writer.drain()
            status = await asyncio.wait_for(reader.readline(),settings().outbound_request_timeout_seconds)
            if not 200 <= int(status.split()[1]) < 400:
                raise OutboundUnavailable('Health response rejected')
            self.record(endpoint,started)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.record(endpoint,started,exc)
        finally:
            self.states[endpoint.id]['in_flight'] = False
            if writer:
                writer.close()

    async def monitor(self):
        redis = None
        publisher = None
        if settings().redis_url:
            from redis.asyncio import Redis
            redis = Redis.from_url(settings().redis_url)

            async def heartbeat():
                while True:
                    try:
                        await redis.set('adbot:egress:instance:'+self.instance,json.dumps(self.snapshot()),ex=settings().outbound_health_interval_seconds*3)
                    except Exception:
                        log.warning('egress_monitor_publication_failed')
                    await asyncio.sleep(settings().outbound_health_interval_seconds)
            publisher = asyncio.create_task(heartbeat())
        slots = asyncio.Semaphore(4)

        async def check(endpoint):
            async with slots:
                if self.states[endpoint.id]['retry_at'] <= time.monotonic():
                    await self.probe(endpoint)
        try:
            while True:
                if self.enabled:
                    await asyncio.gather(*(check(e) for e in self.config.endpoints))
                await asyncio.sleep(settings().outbound_health_interval_seconds)
        finally:
            if publisher:
                publisher.cancel()
                await asyncio.gather(publisher, return_exceptions=True)
            if redis:
                await redis.aclose()

    def start(self):
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self.monitor())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task,return_exceptions=True)
            self.task = None


@lru_cache
def manager():
    return Manager()


class ProviderPolicy:
    def __init__(self, base, local):
        self.base = urlsplit(base)
        self.local = local

    def check(self, url, navigation=False):
        value = normalize(url)
        p = urlsplit(value)
        if (p.scheme,p.hostname,p.port or (443 if p.scheme=='https' else 80)) != (self.base.scheme,self.base.hostname,self.base.port or (443 if self.base.scheme=='https' else 80)):
            raise PolicyError('Unapproved provider destination')
        return value

    async def resolve(self,url):
        import ipaddress
        import socket
        p = urlsplit(self.check(url))
        records = await asyncio.wait_for(asyncio.get_running_loop().getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM),10)
        ips = list(dict.fromkeys(r[4][0] for r in records))
        if not ips or (not self.local and any(not ipaddress.ip_address(ip).is_global for ip in ips)):
            raise PolicyError('Provider resolved to a forbidden address')
        return ips


@asynccontextmanager
async def model_clients(providers, user_agent_override=None, authorized_override=False, **kwargs):
    from contextlib import AsyncExitStack
    from .egress import egress_proxy
    cfg = settings()
    async with AsyncExitStack() as stack:
        clients = []
        for i,(base,_,_) in enumerate(providers):
            from .user_agents import resolve
            service = 'ai_local' if cfg.ai_provider == 'local' or i > 0 else 'ai'
            options = dict(kwargs)
            headers = httpx.Headers(options.pop('headers', None))
            headers['User-Agent'] = resolve(service,override=user_agent_override,authorized=authorized_override)
            options['headers'] = headers
            if not manager().enabled:
                clients.append(await stack.enter_async_context(httpx.AsyncClient(**options)))
                continue
            local = cfg.ai_provider == 'local' or i > 0
            service = 'ai_local' if local else 'ai'
            token = uuid.uuid4().hex
            # Server-configured local providers may use approved private addresses, but cannot
            # be reached through a remote proxy (127.0.0.1 would mean the proxy itself).
            if local and manager().policy(service).mode != 'direct':
                raise OutboundUnavailable('Local model providers require an explicitly direct service policy')
            proxy = await stack.enter_async_context(egress_proxy(ProviderPolicy(base,local),lambda m,u: m=='POST',service,token))
            clients.append(await stack.enter_async_context(httpx.AsyncClient(proxy=proxy,**options)))
        yield clients

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Validate private approved routing configuration without network calls')
    parser.add_argument('--check', action='store_true', required=True)
    parser.parse_args()
    try:
        checked = Manager(enabled=True)
        print(json.dumps({'valid':True,'endpoints':len(checked.config.endpoints),'services':list(checked.config.services)}))
    except Exception:
        print(json.dumps({'valid':False,'error':'Invalid private routing configuration'}))
        raise SystemExit(1) from None
