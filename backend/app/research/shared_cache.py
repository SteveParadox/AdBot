"""Conversation-scoped shared research cache; JSON only, never pickle.

Redis is an optional acceleration tier, not an authoritative task store.
Fixed hashed slots bound per-conversation cardinality and permit deletion
without KEYS/SCAN. Collisions are ordinary misses.
"""
import hashlib
import json
import time

from redis import Redis
from redis.asyncio import Redis as AsyncRedis
from redis.exceptions import RedisError

from ..config import settings

SLOTS = {"query": 128, "document": 64}
MAX_BYTES = 1_500_000
VERSION = "v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def prefix(owner, conversation):
    return f"adbot:research:{VERSION}:{digest([owner, conversation])}"


def slot(owner, conversation, kind, key):
    fingerprint = digest(key)
    return f"{prefix(owner, conversation)}:{kind}:{int(fingerprint[:8], 16) % SLOTS[kind]}", fingerprint


def client_options():
    return {"socket_connect_timeout": .4, "socket_timeout": .4, "retry_on_timeout": False,
            "max_connections": 8, "decode_responses": False}


class SharedCache:
    def __init__(self, owner, conversation, metrics):
        self.owner, self.conversation, self.metrics = owner, conversation, metrics
        self.client = None
        self.disabled = False
        self.enabled = bool(conversation and settings().redis_url and settings().research_cache_seconds)

    async def __aenter__(self):
        if self.enabled:
            self.client = AsyncRedis.from_url(settings().redis_url, **client_options())
        return self

    async def __aexit__(self, *exc):
        if self.client:
            await self.client.aclose()

    def address(self, kind, key):
        return slot(self.owner, self.conversation, kind, key)

    def error(self):
        self.disabled = True
        self.metrics["shared_cache_errors"] = self.metrics.get("shared_cache_errors", 0) + 1

    async def get(self, kind, key, max_age):
        if not self.client or self.disabled or max_age <= 0:
            return None
        address, fingerprint = self.address(kind, key)
        try:
            raw = await self.client.get(address)
            if not raw or len(raw) > MAX_BYTES:
                return None
            record = json.loads(raw)
            age = time.time() - record["stored"]
            if record["key"] != fingerprint or not 0 <= age < max_age:
                return None
            self.metrics["shared_cache_hits"] = self.metrics.get("shared_cache_hits", 0) + 1
            return record["value"], record["stored"]
        except (RedisError, OSError, TimeoutError):
            self.error()
        except (ValueError, TypeError, KeyError, OverflowError):
            # Corrupt or incompatible data is a miss, not a task failure.
            return None

    async def put(self, kind, key, value, ttl):
        if not self.client or self.disabled or ttl <= 0:
            return
        address, fingerprint = self.address(kind, key)
        try:
            raw = json.dumps({"key": fingerprint, "stored": time.time(), "value": value},
                             ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode()
            if len(raw) <= MAX_BYTES:
                await self.client.set(address, raw, ex=max(1, min(3600, int(ttl))))
        except (RedisError, OSError, TimeoutError):
            self.error()
        except (ValueError, TypeError, OverflowError):
            return

    async def discard(self, kind, key):
        if not self.client or self.disabled:
            return
        address, _ = self.address(kind, key)
        try:
            # Evicting a colliding entry is harmless; it only causes a miss.
            await self.client.delete(address)
        except (RedisError, OSError, TimeoutError):
            self.error()


def purge_conversation(owner, conversation):
    """Best-effort bounded invalidation; TTL remains the outage backstop."""
    if not settings().redis_url:
        return True
    base = prefix(owner, conversation)
    keys = [f"{base}:{kind}:{index}" for kind, count in SLOTS.items() for index in range(count)]
    try:
        with Redis.from_url(settings().redis_url, **client_options()) as client:
            client.delete(*keys)
        return True
    except (RedisError, OSError, TimeoutError):
        return False
