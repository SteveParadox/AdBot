"""Persisted identity policy; resolve once per logical request/context, never per retry."""
import hashlib
import random
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from .config import settings
from .content import Admin
from .db import UserAgentConfig, UserAgentAudit, Session, transaction

SERVICES = ('browser','ai','ai_local','proxy_health')
_cache = None
_cache_until = 0
_counter = 0


def validate(value):
    if not value or len(value)>settings().user_agent_max_length or value != value.strip() or any(ord(c)<32 or ord(c)>126 for c in value):
        raise ValueError('User-Agent must be nonempty printable ASCII, without surrounding spaces or controls, within configured length')
    return value


class Profile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    name: str = Field(min_length=1,max_length=100)
    value: str
    description: str = Field('',max_length=1000)
    category: str = Field('custom',max_length=80)
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0
    _valid = field_validator('value')(validate)


class ServicePolicy(BaseModel):
    enabled: bool = True
    updated_at: float = 0
    model_config = ConfigDict(extra='forbid')
    value: str | None = None
    profile: str | None = None
    rotation: Literal['none','round_robin','random','scheduled','proxy_endpoint'] = 'none'
    profiles: list[str] = Field(default_factory=list,max_length=100)
    interval_seconds: int = Field(300,ge=30)
    @field_validator('value')
    @classmethod
    def valid(cls,value):
        return validate(value) if value is not None else value


class Document(BaseModel):
    model_config = ConfigDict(extra='forbid')
    revision: int = Field(0,ge=0)
    global_value: str | None = None
    profiles: list[Profile] = Field(default_factory=list,max_length=100)
    services: dict[Literal['browser','ai','ai_local','proxy_health'],ServicePolicy] = Field(default_factory=dict)
    @field_validator('global_value')
    @classmethod
    def valid(cls,value):
        return validate(value) if value is not None else value
    @model_validator(mode='after')
    def references(self):
        if not any(p.id=='app-default' for p in self.profiles):
            if len(self.profiles)>=100:
                raise ValueError('Reserve a profile slot for the application default')
            self.profiles.insert(0,Profile(id='app-default',name='Application default',value=settings().user_agent_default))
        ids=[p.id for p in self.profiles]
        if len(ids)!=len(set(ids)):
            raise ValueError('Duplicate profile ID')
        for p in self.profiles:
            if p.id=='app-default' and (p.value!=settings().user_agent_default or not p.enabled):
                raise ValueError('Application-default profile is protected')
        for name,policy in self.services.items():
            if policy.profile and policy.profile not in ids or set(policy.profiles)-set(ids):
                raise ValueError('Referenced profiles cannot be deleted')
            if policy.rotation!='none':
                if name != 'browser' or name not in {s.strip() for s in settings().user_agent_rotatable_services.split(',')} or name in settings().user_agent_fixed_identities:
                    raise ValueError('Operator policy does not permit identity rotation for this service')
                from .outbound import manager
                routing=manager()
                if policy.rotation=='proxy_endpoint' and not routing.enabled:
                    raise ValueError('Proxy-coordinated identity needs enabled proxy routing')
                if routing.enabled:
                    try:
                        route=routing.policy(name)
                    except RuntimeError:
                        raise ValueError('Missing approved service routing policy') from None
                    if route.stable or not route.allow_rotation:
                        raise ValueError('Stable routing cannot rotate User-Agent')
                if not policy.profiles or policy.value is not None or policy.profile is not None:
                    raise ValueError('Rotation needs a profile pool without conflicting overrides')
        return self


def defaults():
    return Document(profiles=[Profile(id='app-default',name='Application default',value=settings().user_agent_default)])


def invalidate():
    global _cache, _cache_until
    _cache=None
    _cache_until=0


def read():
    global _cache, _cache_until
    if _cache is not None and time.monotonic()<_cache_until:
        return _cache
    with Session() as session:
        row=session.get(UserAgentConfig,1)
        if row:
            payload = dict(row.payload)
            payload['profiles'] = [dict(p, value=settings().user_agent_default) if p['id']=='app-default' else p for p in payload['profiles']]
            doc=Document.model_validate(payload | {'revision':row.revision})
        else:
            doc=defaults()
    _cache=doc
    _cache_until=time.monotonic()+5
    return doc


def resolve(service, *, override=None, authorized=False, proxy_endpoint=None):
    global _counter
    if service not in SERVICES:
        raise ValueError('Unknown outbound identity service')
    if override is not None and not (authorized and settings().user_agent_allow_request_overrides):
        raise PermissionError('Per-request identity override is not authorized')
    if override is not None:
        validate(override)
    fixed=settings().user_agent_fixed_identities.get(service)
    if fixed:
        return validate(fixed)
    doc=read()
    if override is not None:
        return validate(override)
    policy=doc.services.get(service,ServicePolicy())
    if not policy.enabled:
        policy=ServicePolicy()
    if policy.value is not None:
        return validate(policy.value)
    pool={p.id:p for p in doc.profiles if p.enabled}
    if policy.profile in pool:
        return validate(pool[policy.profile].value)
    if policy.rotation!='none':
        from .outbound import manager
        routing=manager()
        if routing.enabled:
            route=routing.policy(service)
            if route.stable or not route.allow_rotation:
                raise ValueError('Stable proxy integration cannot rotate identity')
        choices=[pool[i].value for i in policy.profiles if i in pool]
        if choices:
            if policy.rotation=='random':
                return validate(random.choice(choices))
            if policy.rotation=='proxy_endpoint':
                if not proxy_endpoint:
                    raise ValueError('Proxy-coordinated rotation requires an assigned endpoint')
                index=int.from_bytes(hashlib.sha256(proxy_endpoint.encode()).digest()[:8],'big')
            elif policy.rotation=='scheduled':
                index=int(time.time()//policy.interval_seconds)
            else:
                index=_counter
                _counter+=1
            return validate(choices[index%len(choices)])
    return validate(doc.global_value or settings().user_agent_default)


router=APIRouter(prefix='/api/admin/user-agents')


@router.get('')
def get_config(admin:Admin):
    try:
        invalidate()
        doc=read()
        with Session() as session:
            row=session.get(UserAgentConfig,1)
            updated=row.updated_at if row else None
        return doc.model_dump() | {'updated_at':updated,'default':settings().user_agent_default,
                'max_length':settings().user_agent_max_length,'fixed':settings().user_agent_fixed_identities,
                'rotatable_services':[v.strip() for v in settings().user_agent_rotatable_services.split(',') if v.strip()],
                'registered_services':list(SERVICES)}
    except (SQLAlchemyError,ValueError):
        raise HTTPException(503,'Identity configuration is unavailable') from None


@router.post('')
def save_config(doc:Document,admin:Admin):
    try:
        with transaction() as session:
            old=session.get(UserAgentConfig,1)
            previous={p['id']:p for p in old.payload['profiles']} if old else {}
            now=time.time()
            if not any(p.id=='app-default' for p in doc.profiles):
                doc.profiles.insert(0,defaults().profiles[0])
            for p in doc.profiles:
                p.created_at=previous.get(p.id,{}).get('created_at',now)
                p.updated_at=now
            for policy in doc.services.values():
                policy.updated_at=now
            payload=doc.model_dump(exclude={'revision'})
            if old:
                result=session.execute(update(UserAgentConfig).where(UserAgentConfig.id==1,UserAgentConfig.revision==doc.revision)
                                       .values(payload=payload,revision=doc.revision+1,updated_at=now))
                if result.rowcount!=1:
                    raise HTTPException(409,'Configuration changed; reload before saving')
            else:
                if doc.revision!=0:
                    raise HTTPException(409,'Reload identity configuration')
                session.add(UserAgentConfig(id=1,revision=1,payload=payload,updated_at=now))
            session.add(UserAgentAudit(administrator=admin,revision=doc.revision+1))
        invalidate()
        return {'revision':doc.revision+1,'updated_at':now}
    except IntegrityError:
        raise HTTPException(409,'Configuration changed; reload before saving') from None
    except SQLAlchemyError:
        raise HTTPException(503,'Identity configuration is unavailable') from None
