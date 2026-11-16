import asyncio
import json
import logging
import signal
import time
from sqlalchemy.exc import SQLAlchemyError

from .jobs import cleanup, tick
from .automation import supervise, get_policy
from .db import uid
from .privacy import install_redaction

install_redaction()


async def main():
    stop = asyncio.Event()
    loop=asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            signal.signal(sig,lambda *_:loop.call_soon_threadsafe(stop.set))
    last_cleanup = 0
    last_supervision = 0
    identifier=uid()
    failures=0
    while not stop.is_set():
        delay=1
        try:
            count = tick()
            if time.time()-last_supervision>30:
                supervise(identifier)
                last_supervision=time.time()
            if get_policy().maintenance_enabled and time.time() - last_cleanup > 3600:
                cleanup()
                last_cleanup = time.time()
            if count:
                logging.warning(json.dumps({"event": "scheduled_jobs", "count": count}))
            failures=0
        except SQLAlchemyError:
            failures+=1
            logging.error('scheduler_database_unavailable')
            if failures>=6:
                raise
            delay=min(30,2**failures)
        except Exception as exc:
            logging.error(json.dumps({"event": "scheduler_error", "error": type(exc).__name__}))
        try:
            await asyncio.wait_for(stop.wait(), delay)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
