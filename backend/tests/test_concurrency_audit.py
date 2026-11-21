import asyncio
import threading
import time
import pytest

from app.concurrency import IOExecutor


async def test_cancelled_shutdown_keeps_running_thread_tracked():
    entered, release = threading.Event(), threading.Event()
    def blocking():
        entered.set()
        release.wait(2)
    io = IOExecutor(1)
    work = asyncio.create_task(io.run(blocking))
    try:
        while not entered.is_set():
            await asyncio.sleep(.001)
        closing = asyncio.create_task(io.close())
        await asyncio.sleep(.01)
        closing.cancel()
        # Cancelled shutdown must yield immediately, not synchronously join the thread.
        started = time.monotonic()
        await asyncio.gather(closing, return_exceptions=True)
        assert time.monotonic() - started < .5
        assert io.snapshot()['io_inflight'] == 1
        assert not work.done()
    finally:
        release.set()
        await asyncio.gather(work, return_exceptions=True)
        await io.close()


async def test_proxy_connection_admission_is_bounded(monkeypatch):
    from app.config import settings
    from app.egress import egress_proxy
    from app.security import Policy
    from urllib.parse import urlsplit
    monkeypatch.setattr(settings(), 'max_proxy_connections', 1, raising=False)
    async with egress_proxy(Policy(['example.org'])) as url:
        address = urlsplit(url)
        first_reader, first = await asyncio.open_connection(address.hostname, address.port)
        await asyncio.sleep(.01)
        second_reader, second = await asyncio.open_connection(address.hostname, address.port)
        try:
            assert await asyncio.wait_for(second_reader.read(1), .2) == b''
        finally:
            first.close()
            second.close()
            await first.wait_closed()
            await second.wait_closed()


def test_cancel_does_not_overwrite_completion_read_concurrently(client, target, monkeypatch):
    from app import main
    from app.db import Job, transaction
    identifier = client.post('/api/jobs', json={'website_id': target['id']}).json()['id']
    original = main.owned
    def stale_read(session, model, key, owner):
        item = original(session, model, key, owner)
        if model is Job and key == identifier:
            with transaction() as competing:
                job = competing.get(Job, key)
                job.status, job.completed_at = 'completed', time.time()
        return item
    monkeypatch.setattr(main, 'owned', stale_read)
    result = client.post(f'/api/jobs/{identifier}/cancel')
    assert result.status_code == 200
    assert result.json()['status'] == 'completed'


def test_review_cannot_overwrite_an_answer_committed_after_read(client, target, monkeypatch):
    from app.agent import api
    from app.db import AgentTask, AgentStep, Job, transaction
    identifier = client.post('/api/jobs', json={'website_id': target['id']}).json()['id']
    with transaction() as session:
        job = session.get(Job, identifier)
        job.job_type, job.status = 'agent', 'waiting_user'
        task = AgentTask(job_id=identifier, objective='test', mode='assisted', options={})
        session.add(task)
        session.flush()
        step = AgentStep(job_id=identifier, number=1, observation={}, status='waiting_user')
        session.add(step)
        session.flush()
        task.pending_step_id = step.id
        step_id = step.id
    original = api.task_for
    retained = []
    def stale_read(session, key, owner):
        pair = original(session, key, owner)
        retained.append(session.get(AgentStep, step_id))
        with transaction() as competing:
            competing.get(AgentStep, step_id).approved = False
        return pair
    monkeypatch.setattr(api, 'task_for', stale_read)
    result = client.post(f'/api/agent/tasks/{identifier}/review', json={'step_id':step_id, 'approved':True})
    assert result.status_code == 409
    with transaction() as session:
        assert session.get(AgentStep, step_id).approved is False


def test_retry_after_never_shortens_provider_delay(monkeypatch):
    from app import retry
    from email.utils import formatdate
    monkeypatch.setattr(retry.time, 'time', lambda: 1000)
    assert retry.retry_delay('120', 0) >= 120
    assert retry.retry_delay(formatdate(1120, usegmt=True), 0) >= 120
    for invalid in ('not-a-date', 'NaN', 'inf', '-10'):
        assert 2 <= retry.retry_delay(invalid, 1) <= 2.25


async def test_worker_startup_failure_closes_redis(monkeypatch):
    from app import worker
    from app.config import settings
    from redis.asyncio import Redis
    class BrokenRedis:
        closed = False
        async def ping(self):
            raise ConnectionError('injected Redis outage')
        async def aclose(self):
            self.closed = True
    connection = BrokenRedis()
    monkeypatch.setattr(settings(), 'redis_url', 'redis://127.0.0.1:1')
    monkeypatch.setattr(Redis, 'from_url', lambda _: connection)
    monkeypatch.setattr(worker.signal, 'signal', lambda *_: None)
    with pytest.raises(ConnectionError):
        await worker.main()
    assert connection.closed


@pytest.mark.browser
async def test_real_parallel_browser_context_storage_isolation():
    # Controlled in-memory pages: no external traffic or shared browser objects.
    from playwright.async_api import async_playwright
    async with async_playwright() as playwright:
        browsers = await asyncio.gather(*(playwright.chromium.launch(headless=True) for _ in range(2)))
        try:
            contexts = await asyncio.gather(*(browser.new_context() for browser in browsers))
            pages = await asyncio.gather(*(context.new_page() for context in contexts))
            async def prepare(index):
                await contexts[index].add_cookies([{'name':'owner', 'value':str(index), 'url':'https://fixture.test'}])
                await pages[index].route('https://fixture.test/**', lambda route: route.fulfill(
                    content_type='text/html', body='<title>Isolated fixture</title><body>test</body>'))
                await pages[index].goto('https://fixture.test/')
                await pages[index].evaluate('(v)=>localStorage.setItem("owner",v)', str(index))
            await asyncio.gather(*(prepare(i) for i in range(2)))
            assert await asyncio.gather(*(page.evaluate('localStorage.getItem("owner")') for page in pages)) == ['0','1']
            assert [(await context.cookies())[0]['value'] for context in contexts] == ['0','1']
            await browsers[0].close()
            assert await pages[1].title() == 'Isolated fixture'
        finally:
            await asyncio.gather(*(browser.close() for browser in browsers), return_exceptions=True)


async def test_model_retry_delay_respects_remaining_deadline(monkeypatch):
    import httpx
    from app.config import settings
    from app.agent.model import ModelClient, ModelDeadlineExceeded
    from app.agent.contracts import Decision
    cfg = settings()
    monkeypatch.setattr(cfg, 'ai_provider', 'local')
    monkeypatch.setattr(cfg, 'ai_model', 'fixture')
    monkeypatch.setattr(cfg, 'ai_base_url', 'http://127.0.0.1:8766/v1')
    monkeypatch.setattr(cfg, 'ai_retries', 2)
    original = httpx.AsyncClient
    calls, charges = [], []
    async def response(request):
        calls.append(request)
        return httpx.Response(429, headers={'Retry-After':'120'})
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(response), **kw))
    def account(*args):
        charges.append(args)
        return {}
    with pytest.raises(ModelDeadlineExceeded, match='retry delay'):
        await ModelClient().request('decide', {'objective':'test'}, Decision, account, timeout_cap_seconds=1)
    assert len(calls) == 1
    assert len(charges) == 2  # Exactly one reservation and one settlement.


async def test_sse_does_not_hold_database_connection_while_client_waits(client, target):
    from app.main import events
    from app.db import Job, Session, engine
    identifier = client.post('/api/jobs', json={'website_id':target['id']}).json()['id']
    with Session() as session:
        owner = session.get(Job, identifier).owner
    class Request:
        async def is_disconnected(self):
            return False
    response = await events(identifier, Request(), owner, None, 0)
    stream = response.body_iterator
    try:
        assert 'progress' in await anext(stream)
        assert engine.pool.checkedout() == 0
    finally:
        await stream.aclose()


@pytest.mark.parametrize('count', [5, 10, 25, 50, 100])
async def test_bounded_stress_with_isolated_failures(count):
    lock = threading.Lock()
    active = maximum = 0
    def operation(index):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)
        try:
            time.sleep(.001)
            if index % 7 == 0:
                raise ValueError('injected independent failure')
            return index
        finally:
            with lock:
                active -= 1
    async with IOExecutor(4) as io:
        results = await asyncio.gather(*(io.run(operation, i) for i in range(count)), return_exceptions=True)
    assert maximum <= 4
    assert active == 0 and not io.pending
    assert sum(isinstance(result, ValueError) for result in results) == len(range(0, count, 7))
    assert sum(isinstance(result, int) for result in results) == count - len(range(0, count, 7))


async def test_real_redis_atomic_rate_counter_across_clients():
    from app.config import settings
    from app.db import uid
    from app.privacy import rate_hit
    from redis.asyncio import Redis
    if not settings().redis_url:
        pytest.skip('Requires explicitly configured isolated test Redis')
    clients = [Redis.from_url(settings().redis_url) for _ in range(2)]
    key = 'adbot:audit:' + uid()
    try:
        values = await asyncio.gather(*(rate_hit(clients[i % 2], key) for i in range(100)))
        assert sorted(values) == list(range(1,101))
        assert 0 < await clients[0].ttl(key) <= 120
    finally:
        await clients[0].delete(key)
        await asyncio.gather(*(client.aclose() for client in clients))


def test_parallel_claims_are_unique_and_respect_capacity(client, target):
    from concurrent.futures import ThreadPoolExecutor
    from app.db import Website, transaction
    from app.jobs import claim, make_job
    with transaction() as session:
        website = session.get(Website, target['id'])
        for index in range(25):
            job = make_job(session, website)
            job.snapshot = {**job.snapshot, 'allowed_domains':[f'isolated-{index}.test']}
    with ThreadPoolExecutor(max_workers=8) as workers:
        claims = [result for result in workers.map(lambda _: claim(), range(25)) if result]
    assert len(claims) == 2
    assert len({identifier for identifier, _ in claims}) == 2
    assert len({token for _, token in claims}) == 2


async def test_egress_monitor_survives_policy_database_outage(monkeypatch):
    from app import automation
    from app.outbound import Manager
    from sqlalchemy.exc import SQLAlchemyError
    def unavailable():
        raise SQLAlchemyError('injected policy database outage')
    monkeypatch.setattr(automation, 'get_policy', unavailable)
    routing = Manager()
    task = asyncio.create_task(routing.monitor())
    try:
        await asyncio.sleep(.02)
        assert not task.done()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
