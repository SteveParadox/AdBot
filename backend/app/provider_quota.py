"""SQL-authoritative fixed-minute admission; no credentials stored in quota keys."""
import hashlib
import time
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .db import ProviderQuota, transaction


class QuotaBlocked(RuntimeError):
    def __init__(self, retry_after):
        self.retry_after = max(0.01, retry_after)
        super().__init__("Shared provider quota exhausted or cooling down")


def identity(base, secret):
    return hashlib.sha256((base.rstrip("/") + "|" + secret).encode()).hexdigest()


def locked(session, key):
    # UPDATE first also serializes SQLite writers, whose FOR UPDATE is a no-op.
    changed = session.execute(update(ProviderQuota).where(ProviderQuota.key == key).values(key=key)).rowcount
    if not changed:
        try:
            with session.begin_nested():
                session.add(ProviderQuota(key=key, window=0, requests=0, tokens=0, cooldown_until=0))
                session.flush()
        except IntegrityError:
            pass
        session.execute(update(ProviderQuota).where(ProviderQuota.key == key).values(key=key))
    return session.get(ProviderQuota, key, populate_existing=True)


def reserve(key, tokens, rpm, tpm, now=None):
    now = time.time() if now is None else now
    window = int(now // 60)
    with transaction() as session:
        row = locked(session, key)
        if row.cooldown_until > now:
            raise QuotaBlocked(row.cooldown_until - now)
        if tpm and tokens > tpm:
            raise ValueError("Model request exceeds configured provider token quota")
        if row.window != window:
            row.window, row.requests, row.tokens = window, 0, 0
        if (rpm and row.requests >= rpm) or (tpm and row.tokens + tokens > tpm):
            raise QuotaBlocked((window + 1) * 60 - now)
        row.requests += 1
        row.tokens += tokens
    return (window, tokens)


def settle(key, receipt, actual):
    # Unknown/failed transport keeps its conservative reservation.
    with transaction() as session:
        row = locked(session, key)
        if row.window == receipt[0]:
            row.tokens = max(0, row.tokens + actual - receipt[1])


def cooldown(key, seconds):
    with transaction() as session:
        row = locked(session, key)
        row.cooldown_until = max(row.cooldown_until, time.time() + max(1, min(seconds, 86400)))



def release(key, receipt):
    """Refund admission only when task budgeting prevents dispatch entirely."""
    with transaction() as session:
        row = locked(session, key)
        if row.window == receipt[0]:
            row.requests = max(0, row.requests - 1)
            row.tokens = max(0, row.tokens - receipt[1])
