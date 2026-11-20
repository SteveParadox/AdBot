"""Synthetic blocking-I/O benchmark; no external traffic or production claims."""
import asyncio
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app.concurrency import IOExecutor


async def measure(count, threaded):
    latencies = []
    tracemalloc.start()
    wall, cpu = time.perf_counter(), time.process_time()
    async with IOExecutor(4) as io:
        async def task():
            if threaded:
                await io.run(time.sleep, 0.01)
            else:
                time.sleep(0.01)
            latencies.append(time.perf_counter() - wall)
        await asyncio.gather(*(task() for _ in range(count)))
    elapsed = time.perf_counter() - wall
    cpu_seconds = time.process_time() - cpu
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return dict(tasks=count, mode='bounded_threads' if threaded else 'blocking_event_loop',
                elapsed_seconds=elapsed, tasks_per_minute=count / elapsed * 60,
                mean_latency_seconds=statistics.mean(latencies),
                p95_latency_seconds=sorted(latencies)[max(0, int(count * .95) - 1)],
                cpu_seconds=cpu_seconds, cpu_percent_one_core=cpu_seconds / elapsed * 100,
                peak_python_bytes=peak, errors=0, retries=0)


async def main():
    results = [await measure(n, mode) for n in (5, 10, 25, 50, 100) for mode in (False, True)]
    print(json.dumps({'workload':'10ms blocking sleep; four I/O threads; latency includes queue wait',
                      'results': results}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
