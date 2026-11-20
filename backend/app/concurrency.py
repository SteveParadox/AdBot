"""Bounded blocking-I/O execution. Sessions must be created inside submitted calls."""
import asyncio
import functools
import time
import logging
from contextvars import ContextVar
from concurrent.futures import ThreadPoolExecutor


class IOExecutor:
    def __init__(self, workers):
        self.workers = workers
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="adbot-io")
        self.slots = asyncio.Semaphore(workers)
        self.pending = set()
        self.closed = False
        self.closing = None
        self.operations = 0
        self.total_queue_ms = 0.0
        self.total_work_ms = 0.0

    async def run(self, function, *args, **kwargs):
        if self.closed:
            raise RuntimeError("I/O executor is closed")
        queued = time.perf_counter()
        await self.slots.acquire()
        self.total_queue_ms += (time.perf_counter() - queued) * 1000
        if self.closed:
            self.slots.release()
            raise RuntimeError("I/O executor is closed")
        try:
            future = asyncio.get_running_loop().run_in_executor(
                self.pool, functools.partial(self._measure, function, args, kwargs)
            )
        except BaseException:
            self.slots.release()
            raise
        self.pending.add(future)

        def finished(result):
            self.pending.discard(result)
            self.slots.release()
            # A cancelled caller cannot cancel a running transaction. Retrieve errors
            # and retain the slot until the actual blocking operation finishes.
            if not result.cancelled():
                result.exception()

        future.add_done_callback(finished)
        return await asyncio.shield(future)

    def _measure(self, function, args, kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.operations += 1
            self.total_work_ms += elapsed
            if elapsed >= 100:
                logging.getLogger("adbot.io").info("slow_io operation=%s duration_ms=%.1f", getattr(function, "__name__", type(function).__name__), elapsed)

    def snapshot(self):
        return {"io_workers": self.workers, "io_inflight": len(self.pending), "operations": self.operations, "queue_ms": self.total_queue_ms, "work_ms": self.total_work_ms}

    async def close(self):
        self.closed = True
        if self.closing is None:
            self.closing = asyncio.create_task(self._drain())
        # One shutdown owner; cancelling a caller must not cancel the executor's
        # futures or release admission while native threads are still running.
        await asyncio.shield(self.closing)

    async def _drain(self):
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)
        self.pool.shutdown(wait=True)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.close()


active_io = ContextVar("active_database_io", default=None)


async def database_call(function, *args, **kwargs):
    """Submit whole operations; never pass a live Session to another thread."""
    executor = active_io.get()
    if executor is not None:
        return await executor.run(function, *args, **kwargs)
    from .config import settings
    async with IOExecutor(settings().max_io_threads) as executor:
        return await executor.run(function, *args, **kwargs)
