import asyncio
import json
import logging
import signal
import time

from sqlalchemy import update, select
from sqlalchemy.exc import SQLAlchemyError

from .browser import BrowserCrashed, Runner
from .config import settings
from .concurrency import IOExecutor, active_io, database_call
from .resources import ResourceMonitor, pressured
from .privacy import install_redaction
from .outbound import manager
from .db import Session, AgentStep, AgentTask, Frontier, Job, Lease, emit, transaction
from .jobs import acquire, claim, heartbeat, owned_job, recover_expired

logging.basicConfig(level=logging.INFO, format="%(message)s")
install_redaction()
logger = logging.getLogger("adbot.worker")


async def execute(job_id, token, io=None):
    if io is None:
        async with IOExecutor(settings().max_io_threads) as owned_io:
            return await execute(job_id, token, owned_io)
    binding = active_io.set(io)
    try:
        return await _execute(job_id, token)
    finally:
        active_io.reset(binding)


async def _execute(job_id, token):
    def initialize():
        with transaction() as session:
            kind = owned_job(session, job_id, token).job_type
            # Claiming a job and starting its runner are separate boundaries.
            # Duplicate delivery of the same token must not launch two browsers.
            if not acquire(session, "execution:" + job_id, token, time.time()):
                return None
        try:
            if kind == 'export':
                from .extraction.exporter import ExportRunner
                runner = ExportRunner(job_id,token)
            elif kind == "agent":
                from .agent.runner import AgentRunner

                runner = AgentRunner(job_id, token)
            else:
                runner = Runner(job_id, token)
        except Exception:
            with transaction() as session:
                job = owned_job(session, job_id, token)
                job.status, job.completed_at = "failed", time.time()
                job.error_message = "Job initialization failed; inspect configuration and encrypted session key"
                job.lease_until = 0
                from .failures import diagnose
                job.execution_state = {**job.execution_state, "failure": diagnose(session, job, job.error_message)}
                emit(session, job_id, "failed", job.error_message)
                session.execute(update(Lease).where(Lease.token == token).values(expires_at=0))
            return None
        with transaction() as session:
            job = owned_job(session, job_id, token)
            budget = max(0.1, runner.cfg["max_duration_seconds"] - (time.time() - job.started_at))
        return runner, kind, budget

    initialized = await database_call(initialize)
    if initialized is None:
        return
    runner, kind, budget = initialized
    browser_task = asyncio.create_task(runner.run())

    async def watch():
        last_beat = 0
        while not browser_task.done():
            if time.monotonic() - last_beat >= 10:
                if not await database_call(heartbeat, job_id, token):
                    raise InterruptedError("Worker lease lost")
                last_beat = time.monotonic()
            def control_state():
                with Session() as session:
                    job = owned_job(session, job_id, token)
                    from .automation import get_policy
                    control = get_policy(session)
                    if job.cancel_requested or control.emergency_stop or kind in control.disabled or job.website_id in control.disabled_websites:
                        return "cancel", job.status
                    if job.pause_requested or control.paused:
                        desired = "paused"
                    elif kind == "agent":
                        desired = "waiting_user" if session.get(AgentTask, job_id).pending_step_id else "running"
                    else:
                        desired = "running"
                    return desired, job.status
            control, previous_status = await database_call(control_state)
            if control == "cancel":
                raise asyncio.CancelledError()
            # The observable paused state is an acknowledgement that the gate is
            # already closed. Never publish it from the IO thread beforehand.
            runner.gate.clear() if control == "paused" else runner.gate.set()
            if previous_status != control:
                def publish_control():
                    with transaction() as session:
                        job = owned_job(session, job_id, token)
                        if job.status == previous_status:
                            job.status = control
                            emit(session, job_id, control, "Execution state updated")
                await database_call(publish_control)
            await asyncio.sleep(0.25)

    watcher = asyncio.create_task(watch())
    status, error = "completed", None
    failure_exception = None
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
        failure_exception = exc
        status, error = (
            "failed",
            str(exc)[:500] if isinstance(exc, (ValueError, RuntimeError, AssertionError)) else type(exc).__name__,
        )
    finally:
        browser_task.cancel()
        watcher.cancel()
        await asyncio.gather(browser_task, watcher, return_exceptions=True)
        def finalize():
            nonlocal status, error
            with transaction() as session:
                job = session.scalar(select(Job).where(Job.id == job_id).with_for_update())
                if status and job and job.lease_token == token and job.lease_until > time.time():
                    if error:
                        from .failures import diagnose
                        diagnostic = diagnose(session, job, error, failure_exception)
                        job.execution_state = {**job.execution_state, "failure": diagnostic}
                    if status == "retry_browser":
                        safe = job.job_type == "crawl"
                        if kind == "agent":
                            last = session.scalar(
                                select(AgentStep)
                                .where(AgentStep.job_id == job_id)
                                .order_by(AgentStep.number.desc())
                                .limit(1)
                            )
                            safe = not (
                                last
                                and (last.status == "executing" or (last.outcome or {}).get("uncertain_submission"))
                                and last.decision.get("decision") in {"CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"}
                            )
                            if safe and last and last.status in {"observed", "executing"}:
                                last.status, last.outcome = (
                                    "interrupted",
                                    {"error": "Browser disconnected; read-only task will replan"},
                                )
                            session.get(AgentTask, job_id).pending_step_id = None
                        from .automation import get_policy
                        status = "queued" if safe and job.retry_count < min(runner.cfg["retries"],get_policy(session).recovery_retries) else "failed"
                        job.retry_count += 1
                        if status == "queued":
                            session.execute(
                                update(Frontier)
                                .where(Frontier.job_id == job_id, Frontier.crawl_status == "visiting")
                                .values(crawl_status="pending")
                            )
                    if error:
                        job.execution_state = {**job.execution_state, "failure": {**job.execution_state["failure"], "automatic_retry_scheduled": status == "queued" and not job.cancel_requested}}
                    job.status = "cancelled" if job.cancel_requested else status
                    if kind == "agent" and job.status == "completed":
                        result = getattr(runner, "verified_result", None)
                        if result is None:
                            job.status = "failed"
                            status, error = "failed", "Agent stopped without a durable verified result"
                            from .failures import diagnose
                            job.execution_state = {**job.execution_state, "failure": diagnose(session, job, error)}
                        else:
                            task = session.get(AgentTask, job_id)
                            task.result = result
                            if task.options["memory_enabled"]:
                                from .agent.memory import save_memory
                                save_memory(session, job, task)
                            emit(session, job_id, "goal_verified", "Objective verified against collected evidence",
                                 claims=len(result["claims"]))
                    if kind == "agent" and job.status in {"failed", "cancelled"}:
                        task = session.get(AgentTask, job_id)
                        directory = task.memory.get("directory", {})
                        if directory.get("entity") or directory.get("pages"):
                            from .agent.directory import directory_result
                            task.result = directory_result(directory, error or "Directory collection stopped before verification")
                            emit(session, job_id, "agent_partial_result", "Directory evidence preserved",
                                 records=task.result["directory"]["unique_records"])
                    job.completed_at = None if job.status == "queued" else time.time()
                    if not error and job.status == "completed":
                        job.execution_state = {k: v for k, v in job.execution_state.items() if k != "failure"}
                    job.error_message = error
                    job.lease_until = 0
                    from .db import NetworkAssignment
                    session.execute(update(NetworkAssignment).where(NetworkAssignment.job_id==job_id,NetworkAssignment.token==token).values(active=False))
                    if kind == "agent" and job.status in {"completed", "failed", "cancelled"}:
                        session.get(AgentTask, job_id).pending_step_id = None
                        step = session.scalar(
                            select(AgentStep).where(AgentStep.job_id == job_id).order_by(AgentStep.number.desc()).limit(1)
                        )
                        if step and step.status in {"observed", "waiting_user", "executing"}:
                            uncertain = step.status == "executing" and (step.decision or {}).get("decision") in {
                                "CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"
                            }
                            step.status = job.status if job.status != "completed" else "failed"
                            step.outcome = {"error": error or "Task stopped before a durable step outcome",
                                            "uncertain_submission": uncertain}
                            if uncertain and not error:
                                from .failures import diagnose
                                job.execution_state = {
                                    **job.execution_state,
                                    "failure": diagnose(session, job, "Task stopped during input; external outcome is uncertain"),
                                }
                    status = job.status
                    emit(session, job_id, job.status, f"Job {job.status}", error=error)
                    if job.snapshot.get('extraction'):
                        from .extraction.persistence import finish
                        finish(session,job)
                        from .db import ExtractionRun
                        run = session.get(ExtractionRun, job.id)
                        if not error and run and run.status == "partial":
                            from .failures import diagnose
                            job.execution_state = {**job.execution_state, "failure": diagnose(session, job, "Extraction incomplete; inspect dataset issues")}

                    from .automation import event, get_policy
                    if job.status in {"completed","failed","cancelled"} and get_policy(session).notifications:
                        event(session,"job_"+job.status,"warning" if job.status=="failed" else "info",job_id=job.id)
                session.execute(update(Lease).where(Lease.token == token).values(expires_at=0))
        await database_call(finalize)
        logger.info(json.dumps({"event": "job_finished", "job_id": job_id, "status": status, "error": "job_failed" if error else None}))


async def main():
    routing = manager()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
    io = IOExecutor(settings().max_io_threads)
    resources = ResourceMonitor()
    resource_sample = {}
    tasks = set()
    redis = None
    config_task = None
    from .automation import pulse
    from .db import uid
    identifier = uid()
    last_pulse = 0
    try:
        if settings().redis_url:
            from redis.asyncio import Redis
            redis = Redis.from_url(settings().redis_url)
            await redis.ping()
        routing.start()
        from .automation import watch_configuration
        config_task = asyncio.create_task(watch_configuration())
        from .agent.model import warm_local_fallback
        warmup=asyncio.create_task(warm_local_fallback())
        stopping=asyncio.create_task(stop.wait())
        try:
            while not warmup.done() and not stop.is_set():
                await io.run(pulse, identifier, 'worker', {'active_jobs':0,'fallback_ready':False,'phase':'warming_fallback', **io.snapshot()})
                await asyncio.wait([warmup,stopping],timeout=10,return_when=asyncio.FIRST_COMPLETED)
            if stop.is_set():
                return
            fallback_ready=warmup.result()
        finally:
            warmup.cancel()
            stopping.cancel()
            await asyncio.gather(warmup,stopping,return_exceptions=True)
        failures=0
        while not stop.is_set():
            try:
                if time.monotonic()-last_pulse>10:
                    resource_sample = await io.run(resources.sample)
                    await io.run(pulse, identifier, 'worker', {'active_jobs':len(tasks),'last_check':time.time(),'fallback_ready':fallback_ready, **io.snapshot(), **resource_sample, 'resource_backpressure': pressured(resource_sample, settings())})
                    last_pulse=time.monotonic()
                await io.run(recover_expired)
                for task in [t for t in tasks if t.done()]:
                    try:
                        task.result()
                    except (Exception,asyncio.CancelledError):
                        logger.error('worker_task_interrupted')
                tasks = {t for t in tasks if not t.done()}
                from .automation import get_policy
                capacity = (await io.run(get_policy)).concurrency
                while len(tasks) < capacity and not stop.is_set() and not pressured(resource_sample, settings()):
                    item = await io.run(claim)
                    if item is None:
                        break
                    tasks.add(asyncio.create_task(execute(*item, io=io)))
                if redis:
                    # Redis is a wakeup accelerator; the SQL queue is authoritative.
                    try:
                        await redis.blpop("adbot:wakeup", timeout=1)
                    except Exception:
                        await asyncio.sleep(1)
                else:
                    await asyncio.sleep(0.5)
                failures=0
            except SQLAlchemyError:
                failures+=1
                logger.error('worker_database_unavailable')
                if failures>=6:
                    raise
                await asyncio.sleep(min(30,2**failures))

    finally:
        # Cancel browser activity promptly. Expired leases recover on restart;
        # operator-requested process shutdown is recorded as cancellation.
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if config_task is not None:
            config_task.cancel()
            await asyncio.gather(config_task,return_exceptions=True)
        try:
            await routing.close()
        finally:
            try:
                await io.close()
            finally:
                if redis:
                    await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
