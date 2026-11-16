"""Shared, atomic selection at logical session boundaries (SQL is authoritative)."""

import hashlib
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .db import SelectionCounter, SharedProxyHealth, transaction


def next_counter(name):
    with transaction() as session:
        changed = session.execute(
            update(SelectionCounter).where(SelectionCounter.name == name).values(value=SelectionCounter.value + 1)
        ).rowcount
        if not changed:
            try:
                with session.begin_nested():
                    session.add(SelectionCounter(name=name, value=1))
                    session.flush()
            except IntegrityError:
                session.execute(
                    update(SelectionCounter)
                    .where(SelectionCounter.name == name)
                    .values(value=SelectionCounter.value + 1)
                )
        return session.get(SelectionCounter, name).value - 1


def proxy_key(endpoint):
    return hashlib.sha256(
        (endpoint.id + "|" + endpoint.url + "|" + endpoint.username.get_secret_value()).encode()
    ).hexdigest()


def shared_retry(endpoint):
    with transaction() as session:
        row = session.get(SharedProxyHealth, proxy_key(endpoint))
        return row.retry_at if row else 0


def publish_health(endpoint, started, retry_at):
    key = proxy_key(endpoint)
    with transaction() as session:
        changed = session.execute(
            update(SharedProxyHealth)
            .where(SharedProxyHealth.id == key, SharedProxyHealth.observed_at <= started)
            .values(observed_at=started, retry_at=retry_at)
        ).rowcount
        if not changed and session.get(SharedProxyHealth, key) is None:
            try:
                with session.begin_nested():
                    session.add(SharedProxyHealth(id=key, observed_at=started, retry_at=retry_at))
                    session.flush()
            except IntegrityError:
                session.execute(
                    update(SharedProxyHealth)
                    .where(SharedProxyHealth.id == key, SharedProxyHealth.observed_at <= started)
                    .values(observed_at=started, retry_at=retry_at)
                )


def assign(runner, routing):
    from .db import NetworkAssignment
    from .jobs import owned_job
    from .user_agents import resolve, validate

    options = getattr(runner, "options", {})
    if options.get("session_persistence") or options.get("allow_form_input"):
        routing.strict_sessions.add(("browser", runner.id))

    with transaction() as session:
        owned_job(session, runner.id, runner.token)
        row = session.get(NetworkAssignment, runner.id)
        previous = (row.user_agent, row.endpoint) if row else None
    if previous:
        ua, endpoint = previous
        validate(ua)
        from .config import settings

        fixed = settings().user_agent_fixed_identities.get("browser")
        if fixed and fixed != ua:
            raise ValueError("Session identity conflicts with mandatory identity; start a reviewed new job")
        policy = routing.policy("browser")
        if endpoint is None:
            if policy.mode != "direct":
                raise ValueError("Existing direct session cannot change egress implicitly")
        else:
            if policy.mode == "direct" or endpoint not in policy.endpoints:
                raise ValueError("Existing session route is no longer approved")
            routing.sticky[("browser", runner.id)] = endpoint
            routing.bound.add(("browser", runner.id))
            endpoint = routing.select("browser", runner.id).id
    else:
        endpoint = routing.bind("browser", runner.id)
        ua = resolve("browser", proxy_endpoint=endpoint, client=runner.cfg["browser"], session_key=runner.id)
    with transaction() as session:
        job = owned_job(session, runner.id, runner.token)
        row = session.get(NetworkAssignment, job.id)
        if row:
            if row.user_agent != ua:
                raise InterruptedError("Assignment changed; refuse incompatible session")
            row.token = runner.token
            row.endpoint = endpoint
            row.active = True
            row.expires_at = job.lease_until
        else:
            session.add(
                NetworkAssignment(
                    job_id=job.id, token=runner.token, user_agent=ua, endpoint=endpoint, expires_at=job.lease_until
                )
            )
            from .db import emit

            emit(
                session,
                job.id,
                "identity_assigned",
                "Approved network identity assigned",
                endpoint=endpoint,
                client=runner.cfg["browser"],
            )
    routing.assignment_tokens[("browser", runner.id)] = runner.token
    return ua


def route_changed(identifier, endpoint, token):
    """Persist an explicitly permitted failover, fenced against stale workers."""
    from .db import NetworkAssignment, emit
    from .jobs import owned_job

    with transaction() as session:
        row = session.get(NetworkAssignment, identifier)
        if row is None:
            return
        job = owned_job(session, identifier, token)
        # Lock via a conditional write so a replacement worker cannot race us.
        changed = session.execute(
            update(NetworkAssignment)
            .where(
                NetworkAssignment.job_id == identifier,
                NetworkAssignment.token == job.lease_token,
                NetworkAssignment.active.is_(True),
            )
            .values(endpoint=endpoint)
        ).rowcount
        if not changed:
            raise InterruptedError("Session assignment lease lost")
        emit(session, identifier, "egress_changed", "Approved proxy failover applied", endpoint=endpoint)
