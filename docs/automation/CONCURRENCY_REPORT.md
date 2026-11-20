# Concurrency audit and implementation

> Update: worker control polling/finalization, model accounting and agent review/checkpoint operations now use the bounded executor, with duration/queue telemetry and shared provider quotas. See [current reliability guide](RELIABILITY.md). The measurements below describe the earlier concurrency implementation.


Follow-up adversarial findings and current verification: [CONCURRENCY_AUDIT.md](CONCURRENCY_AUDIT.md).

## Scope and architecture

This is an incremental hardening of the existing execution architecture. It does
not implement every capability in the requested thirteen-phase roadmap. In
particular, provider-wide RPM/TPM admission remains outstanding. Existing limits and authorization remain authoritative.

The SQL queue remains durable and Redis remains a wakeup accelerator. Independent
jobs run as asyncio tasks. Each job owns its runner, browser, egress proxy, identity,
agent state and database transactions. Sequential agent decisions and workflow
steps preserve their dependencies; parallelizing these would change semantics.
Per-job browser processes intentionally retain crash and network isolation.

| Component | Audited execution before changes | Recommendation / implemented change | Priority |
|---|---|---|---|
| AI agents | Independent async runners; sequential observe/decide/act; durable budgets and checkpoints | Retain; add distributed agent capacity slots | Critical |
| Browser sessions | Independent async browser processes and contexts; global and domain leases | Retain isolation; separate browser ceiling | Critical |
| HTTP | Async httpx, async proxy sockets, bounded provider responses | Retain; provider-wide admission remains outstanding | High |
| Jobs | SQL queue, atomic lease claims, heartbeats and recovery | Reuse; thread-offload worker queue coordination | High |
| CPU processing | Bounded JSON/text/image handling; local inference is an external service | No demonstrated CPU hotspot justifying a process pool | Medium |
| Database | Sync SQLAlchemy pooled connections, transaction-local sessions, SQLite WAL / PostgreSQL | Offload worker coordination and scheduler transactions; remaining inline transactions need follow-up | High |
| Proxy / UA | Async networking plus SQL counters, health cooldowns and pinned assignments | Preserve policy and session identity | High |
| Monitoring | Independent configuration watcher, SQL worker pulses and admin polling | Add bounded-I/O utilization samples | Medium |
| Scheduling | Atomic due-schedule advancement; immutable single dependency; priority/FIFO | Add age-adjusted priority | High |

See CONCURRENCY_INVENTORY.md for the backend module inventory. Existing architecture,
automation, security, API and operations documentation informed this audit. No
repository AGENTS.md was found. User changes in docs/OPERATIONS.md were preserved.

## Changes

- `backend/app/concurrency.py`: process-owned bounded ThreadPoolExecutor, asynchronous
  admission, exception propagation, cancellation-safe capacity accounting and shutdown.
  At most the configured number of calls is submitted; waiting coroutine callers
  do not enter an unbounded executor queue. The SQL backlog and worker task ceiling
  bound the production producer workload.
- `backend/app/worker.py`: offload claim, recovery, policy reads and worker pulses.
  Warmup still gates worker startup as before. The pool drains during shutdown.
- `backend/app/scheduler.py`: offload schedule ticks, supervision, policy reads and
  retention cleanup into the same bounded execution abstraction.
- `backend/app/jobs.py`: distributed agent-slot leases and separate browser capacity;
  waiting time adds priority points. Candidates stream in batches of 50 so a blocked domain backlog cannot hide eligible jobs beyond the first batch. Domain leases still serialize same-domain work.
- `backend/app/config.py`, `.env.example`: validated operator ceilings.
- `frontend/src/AutomationCenter.tsx`: display active jobs and I/O utilization per worker.
- `backend/tests/test_concurrency.py`: executor bounds, event-loop responsiveness,
  cancellation, cleanup, exception isolation, aging, capacity and overlapping jobs.
- `scripts/benchmark_concurrency.py`: reproducible synthetic benchmark.

New dependencies: none. Database migrations: none. Existing Lease rows store agent
capacity ownership and use the existing heartbeat/expiry mechanisms. No commits,
pushes, production restarts or live workload changes were performed.

## Configuration

| Variable | Default | Meaning |
|---|---:|---|
| ADBOT_MAX_IO_THREADS | 4 | Per worker/scheduler blocking-I/O threads, range 1–32 |
| ADBOT_MAX_CONCURRENT_AGENTS | 2 | Global agent slots, range 1–8 |
| ADBOT_MAX_BROWSER_SESSIONS | 2 | Global browser-job slots, range 1–8 |
| ADBOT_PRIORITY_AGING_SECONDS | 300 | Seconds waiting per extra priority point |

Effective total capacity is the smaller of the existing administrator concurrency
policy and the browser ceiling. Agents also need an agent slot. Paused and
waiting-for-user jobs retain their leases and capacity. Environment changes need
worker restarts; runtime policy retains its existing revision protection. Lowering
ceilings does not terminate existing work; existing leases drain. All workers must
use the same operator ceilings. Older workers must be drained before rollout.
No defaults raise the existing two-job ceiling. The existing 500-step agent
configuration and validation were preserved.

## Coverage and remaining work

| Feature | Before | After | Evidence |
|---|---|---|---|
| Agents | Async isolated jobs | Same, separate global cap | test_agent_capacity_does_not_block_crawls |
| Browsers | Process/context per job, shared total cap | Same, independent ceiling | test_browser_cap_across_distinct_domains |
| HTTP | Async network I/O | Unchanged | Existing outbound/browser tests |
| Background jobs | Async tasks with blocking queue calls | Queue calls offloaded | test_worker_execution_overlap_and_failure_isolation; executor tests |
| Database | Pooled sync SQLAlchemy | Coordination and scheduler calls offloaded, session ownership preserved | Existing automation tests |
| Scheduling | Priority/FIFO and single immutable dependency | Aging plus existing dependency semantics | test_priority_aging; existing dependency tests |

The dependency model is a forest with one existing prerequisite per job; creation
order and immutable links prevent cycles. Arbitrary multi-parent DAGs are not
implemented. Existing API status values are preserved (timeouts remain failed with
an explanatory error), rather than introducing incompatible status names.

`backend/app/resources.py` samples physical memory and host CPU on Windows/Linux
without additional dependencies. Workers sample every ten seconds and suspend new
claims above operator thresholds, keeping active jobs, lease renewal and recovery
running. Pressure clears on the next healthy sample. Unsupported sampling is
reported and fixed capacity limits continue to apply. Defaults are monitoring on,
`ADBOT_MAX_HOST_MEMORY_PERCENT=95`, `ADBOT_MAX_HOST_CPU_PERCENT=95`; disable with
`ADBOT_RESOURCE_MONITORING_ENABLED=false`. These are coarse host limits, not
per-task memory reservations or predictive admission. Tests inject samples and
exercise pressure and unsupported-host behavior.

Remaining limitations: inline runner/watch/API transactions can still block the
event loop during database contention; no full async-driver migration was made.
No predictive resource reservation, pooled browser reuse, CPU process executor,
new circuit breaker, provider-wide RPM/TPM limiter, or new remote shutdown endpoint
was introduced. Provider retries/budgets/fallback retain existing behavior. Native
threads cannot be force-stopped: cancellation keeps admission occupied until the
transaction finishes and shutdown waits for it. DB outages can therefore delay
shutdown by driver timeouts. Host process supervision remains necessary.

Existing recovery is at-least-once for safe reads and refuses ambiguous mutating
replays. This change does not claim exactly-once side effects. PostgreSQL/Redis
multi-host behavior, real-provider quotas, host termination, browser startup cost
and production resource usage require deployment-specific integration testing.

## Benchmark

Run `.venv\Scripts\python.exe scripts/benchmark_concurrency.py` from the repository
root. Raw measurements are in CONCURRENCY_BENCHMARK.json. Both modes run the same
10ms blocking-sleep workload; the comparison isolates blocking event-loop behavior
versus the new four-thread executor. It is not a before/after production benchmark.
Latency includes admission wait. Memory measures Python allocations with
tracemalloc, not process RSS; CPU percentage is relative to one core. This does not
measure AI waiting time, browser startup, database contention or network throughput.

At 100 tasks: blocking 1.0456s versus bounded threads 0.2884s; throughput
5,738 versus 20,803 tasks/minute; p95 0.9919s versus 0.2753s. CPU time was
0.015625s in both samples (coarse Windows timer resolution). Peak traced Python
allocations were 87,756 versus 177,585 bytes. Errors and retries were zero.
The complete 5/10/25/50/100-task series is recorded in the JSON artifact.

## Verification log

Commands executed from backend unless noted:

- `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py tests/test_automation.py -m "not browser"`: 27 passed (initial executor/limits implementation).
- `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py`: 9 passed after resource-monitor additions.
- `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py::test_blocked_domain_backlog_does_not_hide_eligible_work`: 1 passed after streaming candidate scan.
- `npm.cmd run build` from frontend: passed.
- `npm.cmd test` from frontend: 12 passed across 3 files.
- `.venv\Scripts\python.exe -m ruff check backend/app/concurrency.py backend/app/resources.py backend/app/config.py backend/app/jobs.py backend/app/worker.py backend/app/scheduler.py backend/tests/test_concurrency.py scripts/benchmark_concurrency.py` from root: passed after removing an unused test import.
- `git diff --check`: passed.
- Native Windows resource sampling: succeeded, reporting physical memory utilization.

The initial `npm run build` invocation was rejected by PowerShell script execution
policy. `npm.cmd run build` succeeded without changing that policy. Backend tests
emit an existing Starlette/httpx deprecation warning. A regression run was started
before editing, but was not an immutable checkout baseline; no production
before/after performance claim is made.

Initial broad regression command `..\.venv\Scripts\python.exe -m pytest -q -m
"not browser"`: 152 passed, 1 failed, 37 deselected (970.37s). Failure:
`test_user_agents.py::test_rotation_guards` inherited the operator's local browser
rotation opt-in from .env. The test environment now explicitly disables rotation
in conftest, leaving the operator setting unchanged. Isolated rerun: 1 passed.

Real-browser command `..\.venv\Scripts\python.exe -m pytest -q tests/test_browser.py`:
7 passed, 1 failed (71.68s). The crawl persistence test returned failed at its
20-second session boundary. Isolated rerun with `-vv`: passed in 18.44s. This remains a timing-sensitive test; the session limit was not raised.
Windows Proactor closed-pipe finalizer warnings occurred during the slow-page test.

Final capacity/scan checks after the full-capacity early return optimization:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py::test_browser_cap_across_distinct_domains tests/test_concurrency.py::test_blocked_domain_backlog_does_not_hide_eligible_work`: 2 passed (11.45s).
Final frontend `npx.cmd tsc -b`: passed.

Final targeted regression command:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency.py tests/test_user_agents.py tests/test_automation.py -m "not browser"`: **49 passed**, 1 deprecation warning, 232.92s. This includes all ten new concurrency tests, existing identity policy tests and automation coordination/recovery tests. No tests were skipped in this targeted run. The broad run excluded 37 browser-marked cases; only the eight cases in test_browser.py were subsequently executed, not the complete browser-marked suite.
