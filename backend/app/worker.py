import asyncio
import json
import logging
import signal
import time

from sqlalchemy import update

from .browser import BrowserCrashed, Runner
from .config import settings
from .db import Frontier, Job, Lease, emit, transaction
from .jobs import claim, heartbeat, owned_job, recover_expired

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("adbot.worker")


async def execute(job_id, token):
    runner = Runner(job_id, token)
    with transaction() as session:
        job = owned_job(session, job_id, token)
        budget = max(0.1, runner.cfg["max_duration_seconds"] - (time.time() - job.started_at))
    browser_task = asyncio.create_task(runner.run())

    async def watch():
        last_beat = 0
        while not browser_task.done():
            if time.monotonic() - last_beat >= 10:
                if not heartbeat(job_id, token):
                    raise InterruptedError("Worker lease lost")
                last_beat = time.monotonic()
            with transaction() as session:
                job = owned_job(session, job_id, token)
                if job.cancel_requested:
                    raise asyncio.CancelledError()
                if job.pause_requested:
                    runner.gate.clear()
                    job.status = "paused"
                else:
                    runner.gate.set()
                    job.status = "running"
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch())
    status, error = "completed", None
    try:
        async with asyncio.timeout(budget):
            done, _ = await asyncio.wait([browser_task, watcher], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    except asyncio.CancelledError:
        status = "cancelled"
    except InterruptedError:
        status = None
    except TimeoutError:
        status, error = "failed", "Session duration limit exceeded"
    except BrowserCrashed:
        status, error = "retry_browser", "Browser disconnected unexpectedly"
    except Exception as exc:
        status, error = (
            "failed",
            str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError, AssertionError)) else type(exc).__name__,
        )
    finally:
        browser_task.cancel()
        watcher.cancel()
        await asyncio.gather(browser_task, watcher, return_exceptions=True)
        with transaction() as session:
            job = session.get(Job, job_id)
            if status and job and job.lease_token == token and job.lease_until > time.time():
                if status == "retry_browser":
                    safe = job.job_type == "crawl"
                    status = "queued" if safe and job.retry_count < runner.cfg["retries"] else "failed"
                    job.retry_count += 1
                    if status == "queued":
                        session.execute(
                            update(Frontier)
                            .where(Frontier.job_id == job_id, Frontier.crawl_status == "visiting")
                            .values(crawl_status="pending")
                        )
                job.status = "cancelled" if job.cancel_requested else status
                job.completed_at = None if job.status == "queued" else time.time()
                job.error_message = error
                job.lease_until = 0
                emit(session, job_id, job.status, f"Job {job.status}", error=error)
            session.execute(update(Lease).where(Lease.token == token).values(expires_at=0))
        logger.info(json.dumps({"event": "job_finished", "job_id": job_id, "status": status, "error": error}))


async def main():
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    tasks = set()
    redis = None
    if settings().redis_url:
        from redis.asyncio import Redis

        redis = Redis.from_url(settings().redis_url)
        await redis.ping()
    try:
        while not stop.is_set():
            recover_expired()
            tasks = {t for t in tasks if not t.done()}
            while len(tasks) < settings().max_concurrency and (item := claim()):
                tasks.add(asyncio.create_task(execute(*item)))
            if redis:
                # Redis is a wakeup accelerator; the SQL queue is authoritative.
                try:
                    await redis.blpop("adbot:wakeup", timeout=1)
                except Exception:
                    await asyncio.sleep(1)
            else:
                await asyncio.sleep(0.5)
    finally:
        # Cancel browser activity promptly. Expired leases recover on restart;
        # operator-requested process shutdown is recorded as cancellation.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if redis:
            await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
