import asyncio
import json
import logging
import signal
import time

from .jobs import cleanup, tick
from .privacy import install_redaction

install_redaction()


async def main():
    stop = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    last_cleanup = 0
    while not stop.is_set():
        try:
            count = tick()
            if time.time() - last_cleanup > 3600:
                cleanup()
                last_cleanup = time.time()
            if count:
                logging.warning(json.dumps({"event": "scheduled_jobs", "count": count}))
        except Exception as exc:
            logging.error(json.dumps({"event": "scheduler_error", "error": type(exc).__name__}))
        try:
            await asyncio.wait_for(stop.wait(), 1)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
