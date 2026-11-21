import asyncio
import threading

import pytest

from app.concurrency import IOExecutor


def test_resource_pressure_and_sampling(monkeypatch):
    from types import SimpleNamespace
    from app import resources
    samples = iter([(10, 100, 50), (95, 200, 96)])
    monkeypatch.setattr(resources, 'host_sample', lambda: next(samples))
    monitor = resources.ResourceMonitor()
    cfg = SimpleNamespace(resource_monitoring_enabled=True, max_host_memory_percent=95, max_host_cpu_percent=90)
    assert not resources.pressured(monitor.sample(), cfg)
    sample = monitor.sample()
    assert sample['host_cpu_percent'] == 85
    assert resources.pressured(sample, cfg)
    cfg.resource_monitoring_enabled = False
    assert not resources.pressured(sample, cfg)


def test_resource_sampling_unavailable(monkeypatch):
    from app import resources
    def unavailable():
        raise OSError('unsupported host')
    monkeypatch.setattr(resources, 'host_sample', unavailable)
    assert resources.ResourceMonitor().sample()['resource_sampling_unavailable']


async def test_pool_bound_and_event_loop_responsive():
    release = threading.Event()
    entered = threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
        return 42

    async with IOExecutor(1) as io:
        first = asyncio.create_task(io.run(block))
        try:
            while not entered.is_set():
                await asyncio.sleep(0.001)
            second = asyncio.create_task(io.run(lambda: 7))
            await asyncio.sleep(0.01)
            assert not second.done()
            assert io.snapshot()['io_inflight'] == 1
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert io.snapshot()['io_inflight'] == 1
            assert not second.done()
        finally:
            release.set()
        assert await second == 7


async def test_exception_shutdown_and_reject_new_work():
    io = IOExecutor(2)
    def fail():
        raise ValueError('expected')
    with pytest.raises(ValueError, match='expected'):
        await io.run(fail)
    assert await io.run(lambda: 'healthy') == 'healthy'
    await io.close()
    with pytest.raises(RuntimeError, match='closed'):
        await io.run(lambda: None)


async def test_shutdown_waits_for_cancelled_callers():
    release = threading.Event()
    entered = threading.Event()
    def block():
        entered.set()
        assert release.wait(3)
    io = IOExecutor(1)
    task = asyncio.create_task(io.run(block))
    try:
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        closing = asyncio.create_task(io.close())
        await asyncio.sleep(0.01)
        assert not closing.done()
    finally:
        release.set()
        await io.close()
    await closing


def test_priority_aging(client, target, monkeypatch):
    import time
    from app.config import settings
    from app.db import Job, transaction
    from app.jobs import claim
    from test_automation import queue
    monkeypatch.setattr(settings(), 'priority_aging_seconds', 1)
    old = queue(client, target, priority=-10)
    queue(client, target, priority=10)
    with transaction() as session:
        session.get(Job, old).created_at = time.time() - 30
    assert claim()[0] == old


def test_browser_cap_across_distinct_domains(client, target, monkeypatch):
    from app.config import settings
    from app.db import Job, transaction
    from app.jobs import claim
    from test_automation import queue
    monkeypatch.setattr(settings(), 'max_browser_sessions', 1)
    first = queue(client, target)
    second = queue(client, target)
    with transaction() as session:
        job = session.get(Job, second)
        job.snapshot = {**job.snapshot, 'allowed_domains': ['example.org']}
    assert claim()[0] == first
    assert claim() is None


def test_agent_capacity_does_not_block_crawls(client, target, monkeypatch):
    from app.config import settings
    from app.db import Job, transaction
    from app.jobs import claim
    from test_automation import queue
    monkeypatch.setattr(settings(), 'max_concurrent_agents', 1)
    identifiers = [queue(client, target) for _ in range(3)]
    with transaction() as session:
        for index, identifier in enumerate(identifiers):
            job = session.get(Job, identifier)
            job.snapshot = {**job.snapshot, 'allowed_domains': [f'example{index}.org']}
            job.job_type = 'agent' if index < 2 else 'crawl'
    assert claim()[0] == identifiers[0]
    assert claim()[0] == identifiers[2]
    assert claim() is None


def test_blocked_domain_backlog_does_not_hide_eligible_work(client, target):
    from app.db import transaction
    from app.jobs import claim, make_job
    from app.db import Website
    from test_automation import queue
    first = queue(client, target)
    assert claim()[0] == first
    with transaction() as session:
        website = session.get(Website, target['id'])
        for _ in range(55):
            make_job(session, website)
        independent = make_job(session, website)
        independent.snapshot = {**independent.snapshot, 'allowed_domains': ['independent.org']}
        identifier = independent.id
    assert claim()[0] == identifier


async def test_worker_execution_overlap_and_failure_isolation(client, target, monkeypatch):
    from app import worker
    from app.db import Job, Lease, Session, transaction
    from app.jobs import claim
    from sqlalchemy import select
    from test_automation import queue
    identifiers = [queue(client, target) for _ in range(2)]
    with transaction() as session:
        job = session.get(Job, identifiers[1])
        job.snapshot = {**job.snapshot, 'allowed_domains': ['other.org']}
    claims = [claim(), claim()]
    entered = set()
    both = asyncio.Event()
    class Runner:
        def __init__(self, identifier, token):
            self.identifier = identifier
            self.cfg = {'max_duration_seconds': 10, 'retries': 0}
            self.gate = asyncio.Event()
        async def run(self):
            entered.add(self.identifier)
            if len(entered) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)
            if self.identifier == identifiers[0]:
                raise RuntimeError('isolated failure')
    monkeypatch.setattr(worker, 'Runner', Runner)
    await asyncio.gather(*(worker.execute(*item) for item in claims))
    with Session() as session:
        assert session.get(Job, identifiers[0]).status == 'failed'
        assert session.get(Job, identifiers[1]).status == 'completed'
        assert all(row.expires_at == 0 for row in session.scalars(select(Lease)))
