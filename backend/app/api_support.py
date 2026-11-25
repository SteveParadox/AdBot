"""Shared workspace authentication and API serialization helpers."""

import hashlib
import hmac
import time
from collections import defaultdict, deque
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, inspect, select

from .config import settings
from .db import Website, Workflow
from .privacy import rate_hit

rate_windows = defaultdict(deque)


async def authenticate(request: Request, authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ")
    if not any(hmac.compare_digest(token, k.strip()) for k in settings().api_keys.split(",")):
        raise HTTPException(401, "Valid Bearer API key required", headers={"WWW-Authenticate": "Bearer"})
    owner = hashlib.sha256(token.encode()).hexdigest()
    request.state.owner = owner
    from .traffic import request_counters
    counters = request_counters.get()
    if counters is not None:
        counters["owner"] = owner
    redis = getattr(request.app.state, "redis", None)
    if redis:
        key = f"adbot:rate:{owner}:{int(time.time() // 60)}"
        try:
            hits = await rate_hit(redis, key)
        except Exception:
            raise HTTPException(503, "Service temporarily unavailable") from None
        if hits > settings().rate_per_minute:
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
    else:
        window = rate_windows[owner]
        now = time.monotonic()
        while window and window[0] < now - 60:
            window.popleft()
        if len(window) >= settings().rate_per_minute:
            raise HTTPException(429, "Rate limit exceeded", headers={"Retry-After": "60"})
        window.append(now)
    return owner


Owner = Annotated[str, Depends(authenticate)]
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=200)]


def owned(session, model, identifier, owner):
    item = session.get(model, identifier)
    if not item:
        raise HTTPException(404, "Resource not found")
    actual_owner = item.owner if hasattr(item, "owner") else session.get(Website, item.website_id).owner
    if actual_owner != owner:
        raise HTTPException(404, "Resource not found")
    return item


def output(item):
    # Only column values; leases, owner identity, idempotency metadata and raw
    # snapshots are internal and never returned to clients.
    excluded = {"owner", "lease_token", "lease_until", "payload_hash", "idempotency_key", "snapshot"}
    result = {c.key: getattr(item, c.key) for c in inspect(item).mapper.column_attrs if c.key not in excluded}
    if isinstance(result.get("execution_state"), dict):
        result["execution_state"] = {
            key: value for key, value in result["execution_state"].items() if key not in {"agent_record_scope", "research_checkpoint"}
        }
    if hasattr(item, "job_type"):
        result["failure"] = (item.execution_state or {}).get("failure")
    return result


def collection(session, query, offset, limit):
    count = session.scalar(select(func.count()).select_from(query.order_by(None).subquery()))
    return {"items": [output(item) for item in session.scalars(query.offset(offset).limit(limit))], "total": count}


def workflow_for(session, identifier, website_id, owner):
    if not identifier:
        return None
    workflow = owned(session, Workflow, identifier, owner)
    if workflow.website_id != website_id or not workflow.enabled:
        raise HTTPException(422, "Workflow must be enabled and belong to the website")
    return workflow
