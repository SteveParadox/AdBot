# Concurrency and security audit — 19 November 2026

## Executive summary

Nine confirmed defect groups were identified and corrected with targeted changes (9 fixed, 0 unresolved within those groups). Three unresolved release gates and two operational constraints remain, listed below. No new
dependencies or database migrations were introduced. Existing local changes,
including docs/OPERATIONS.md, were preserved. No commits or pushes were made.

Production verdict: **NOT READY for unrestricted multi-instance production**.
This is not a claim that the fixes failed: the release assessment also requires
provider-wide account admission, production load/soak verification and resolution
of the remaining synchronous database hot paths. These gaps are documented below.

## Findings

| ID | Component | Severity | Verified root cause | Fix | Regression evidence |
|---|---|---|---|---|---|
| AUD-001 | I/O executor shutdown | P1 | Cancelling close() cancelled its gather and wrapped executor futures, removing still-running native calls from tracking | One retained, shielded shutdown task owns draining; all close callers await it | Cancellation test failed before correction; tracked count was zero while the thread still ran |
| AUD-002 | Job cancellation/completion | P1 | Cancellation made a terminal decision using a stale ORM read, overwriting a concurrently committed completed state | Conditional SQL update excludes terminal states and refreshes the response; claim rechecks cancellation; finalization locks the job row on PostgreSQL | Injected concurrent completion was overwritten as cancelled before correction |
| AUD-003 | Agent approval | P1 | Concurrent readers could both see approved=None and overwrite the first committed answer | Compare-and-swap update requires waiting_user and an unanswered step; loser receives 409 | Injected committed refusal remains false when the stale approval request returns 409 |
| AUD-004 | Forward proxy admission | P1 | Each accepted socket allocated a handler without a connection ceiling | Per-job connection cap with immediate excess-socket closure; closing state prevents late admission during teardown | With cap=1, second idle socket timed out before correction; closes promptly after correction |
| AUD-005 | Model retry timing/accounting | P1 | Retry-After was truncated to 30 seconds; HTTP-date values were treated as parse failures; retry sleeps could exceed remaining deadline; final HTTP attempt slept despite no retry | Parse seconds/date, add nonnegative jitter, preserve minimum delay, reject waits exceeding deadline, settle each reservation once, skip final-attempt wait | Parser and actual ModelClient 429/deadline tests; existing model retry/fallback tests |
| AUD-006 | Worker startup | P2 | Redis ping occurred before the try/finally owning Redis and executor cleanup | Bring resource acquisition inside the cleanup scope; tolerate absent configuration watcher | Injected Redis startup failure left connection unclosed before correction |
| AUD-009 | Agent test configuration | P2 | Prompt-compaction test directly changed the shared Settings request limit and leaked it into later browser tests | Use monkeypatch.setattr so the 8,000-character limit is restored on teardown | Encrypted-session test passed alone, failed immediately after compaction test before correction |
| AUD-008 | Egress monitoring | P1 | Policy SQL errors terminated monitor/publisher; a failed probe publication could leave other gather children unjoined | Recover policy reads with jittered waits and join all probes with per-cycle diagnostics | Fault-injected policy outage terminated monitor before correction |
| AUD-007 | SSE database use | P1 | Generator yielded events while its SQL session still held a pooled connection, allowing slow consumers to exhaust the pool | Materialize bounded event payloads and close the session before yielding | Suspended generator held one checked-out connection before correction; zero after correction |

The initial audit-test run recorded three failures plus one test-setup error: the
proxy test originally tried setting a not-yet-declared Pydantic field. After adding
the validated setting, the isolated proxy test reproduced the intended socket
timeout. The startup and SSE regressions were independently executed and failed
before their respective corrections. The approval test uses explicit interleaving
to exercise the stale-read condition; its pre-fix implementation was inspected,
rather than rerun in a separate pristine checkout.

## Repository execution trace and subsystem review

Creation: authenticated, owner-scoped API requests validate website/agent options,
check backlog, snapshot configuration, and persist jobs/events in a transaction.
Unique owner/idempotency keys and frontier constraints constrain duplicates.
API rate limits use Redis INCR+EXPIRE Lua in shared deployments and fail closed
when Redis fails. The development in-memory fallback is process-local.

Scheduling: SQL is authoritative; Redis wakes workers. Cron advancement and job
creation share a transaction with a schedule-specific idempotency key. Immutable
references to existing parent jobs form an acyclic single-parent graph. Priority
aging and streamed candidates avoid the previously fixed first-50 starvation.
The migration seeds the singleton policy row used for PostgreSQL claim locking.
Test create_all() schemas do not automatically seed that row, a material difference
when interpreting concurrency tests versus migrated deployments.

Allocation: global slots, separate agent slots and sorted domain leases use SQL
conditional writes and unique lease names. Each claim also conditionally changes
queued to running. Same-domain serialization is deliberately conservative. Active
agents, paused jobs and jobs awaiting review retain their slots and browser state.
This avoids silently discarding authenticated state, but pausing does not release
memory. All workers must use consistent ceilings and old workers must be drained
before deploying the new separate-slot semantics.

Execution: each job has a distinct runner, browser process/context, gate, agent
memory, model budget and egress session. Observe/decide/act remains sequential per
agent. Step validation still supports the configured maximum of 500. Browser
objects remain on their owning event loop; they are not sent to executor threads.
Independent jobs overlap. No CPU process pool exists: local inference is an
external service and no CPU hotspot was demonstrated that justifies adding a pool.
Entrypoints remain guarded for Windows and do not nest asyncio.run().

Persistence/recovery: owned_job validates lease token and expiry and locks the job
on PostgreSQL before durable action checkpoints. Heartbeats extend job, assignment
and capacity leases together. Recovery uses conditional ownership changes and
refuses ambiguous mutating agent/CLICK replays. Safe reads are at-least-once; no
exactly-once side-effect claim is made. SQL exceptions stop affected execution;
existing task isolation prevents one runner failure terminating unrelated jobs.

Network/security: destination/method checks, IP-pinned DNS resolution, robots,
redirect restrictions, service-worker/WebSocket blocking, identity pinning,
workspace ownership, encrypted sessions and operator-approved egress were retained.
The new proxy cap supplements header/body/connection timeouts. It is per job; the
existing global job cap bounds aggregate admitted proxy handlers. It does not cap
raw kernel SYN queues or replace host firewall/rate controls.

Lifecycle: worker task sets, browser/watcher pairs, warmup tasks, configuration
watchers, proxy pipe tasks and outbound monitoring have cancellation/join scopes.
The executor fix maintains admission until native calls truly finish. Native
threads cannot be killed safely; driver timeouts still bound how long shutdown
may wait. Docker supplies init and restart policy; worker termination grace is
20 seconds, which may be shorter than an outstanding database timeout.

Observability: the existing authenticated Automation Center polls worker pulses,
queue statuses, lease counts, I/O utilization and host pressure. Existing agent
metrics include tokens, model latency, retries and outcomes. This audit did not
add frontend functionality or expose secrets. The existing module inventory and
architecture documents accompany this report.

## Synchronization ownership and ordering

- I/O admission and pending-future bookkeeping belong exclusively to the event
  loop constructing IOExecutor. Worker threads execute submitted functions only.
  One shielded drain task owns shutdown. Each database callable creates its own
  SQLAlchemy session; sessions are never passed across threads.
- Claim transactions acquire the policy row lock, then agent capacity (if needed),
  domain leases in sorted order, total capacity and the conditional job change.
  Candidate savepoint rollback releases provisional assignments.
- Job finalization locks the job row before examining cancellation and ownership.
  Cancellation uses a single conditional update; it cannot rewrite a terminal row.
  Approval uses an unanswered-step predicate, not a process-local lock, so it
  works across API instances. No new global mutex serializes unrelated jobs.
- SSE snapshots contain serialized values only; client backpressure holds no SQL
  connection. Proxy admission checks/count changes contain no await and are atomic
  relative to callbacks on their owning event loop.

## Modified files in this audit

| File | Change |
|---|---|
| backend/app/concurrency.py | Shielded, retained shutdown owner |
| backend/app/main.py | Atomic cancellation and release SQL session before SSE yields |
| backend/app/jobs.py | Recheck cancel_requested in claim CAS |
| backend/app/worker.py | Lock finalization row; cleanup covers startup failures |
| backend/app/agent/api.py | Atomic review answer |
| backend/app/agent/model.py | Deadline-aware, jittered retry waits and single settlement |
| backend/app/retry.py | Retry-After parser and wait calculation |
| backend/app/outbound.py | Keep monitoring alive through policy SQL outages and join all probes |
| backend/app/egress.py | Bounded connection admission and teardown gate |
| backend/app/config.py, .env.example | ADBOT_MAX_PROXY_CONNECTIONS, default 64, range 1–1024 |
| backend/tests/test_agent.py | Restore request-size limit after the compaction test |
| backend/tests/test_concurrency_audit.py | Reproductions, failure injection, stress, real browser and Redis verification |
| docs/automation/CONCURRENCY_AUDIT_BENCHMARK.json | Raw post-fix synthetic measurements |
| docs/automation/CONCURRENCY_AUDIT.md | Findings, verification and release assessment |

Earlier changes to scheduler, resources, dashboard and concurrency tests remain
present from the prior implementation. No migration was required for this audit.

## Tests executed

Commands below run from backend unless otherwise noted. Runs overlap in coverage;
counts must not be summed as unique test cases.

| Command | Result |
|---|---|
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py tests/test_concurrency.py tests/test_api.py` | 30 passed, 123.90s (first three audit tests plus existing tests) |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py tests/test_agent.py -m "not browser"` | First run: 23 passed, 15 deselected; subsequent run: 26 passed, 16 deselected, 128.19s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py tests/test_automation.py tests/test_security.py tests/test_outbound.py tests/test_provider_handoff.py -m "not browser"` | 68 passed, 303.14s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py::test_real_parallel_browser_context_storage_isolation tests/test_browser.py` | 9 passed, 66.92s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py -m "not browser"` | 13 passed, 1 deselected, 73.36s (before adding optional real-Redis case) |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py::test_model_retry_delay_respects_remaining_deadline` | 1 passed, 12.11s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py::test_real_redis_atomic_rate_counter_across_clients` with isolated test Redis | 1 passed, 6.46s; 100 atomic increments across two clients, TTL verified |
| `.venv\Scripts\python.exe -m ruff check backend/app backend/tests backend/testsupport` from root | Passed |
| `git diff --check` | Passed |

The browser isolation fixture launches two real browser processes concurrently,
fulfills pages in memory without external traffic, verifies different cookies and
localStorage, and closes one process while continuing to use the other. It does
not prove production proxy credentials or real authenticated application sessions.
Stress cases exercise 5/10/25/50/100 tasks with four threads and injected independent
failures, asserting capacity, settlement and zero remaining executor work.

Warnings were not suppressed: existing Starlette/httpx deprecation warnings and
Windows Proactor closed-pipe subprocess finalizer warnings occurred. The interpreter
here is Python 3.11.2, while CI/deployment specifies 3.12. The finalizer warnings
still require verification under the supported deployment interpreter; they are
not counted as a resolved resource-leak finding.

## Performance evidence

From root: `.venv\Scripts\python.exe scripts/benchmark_concurrency.py`.
The benchmark is a 10ms blocking-I/O simulation with queue-inclusive latency,
tracemalloc peak allocations, process CPU time and zero external requests.

At 100 tasks, the prior recorded four-thread implementation measured 0.28842s,
20,803 tasks/min, p95 0.27527s, 0.015625 CPU seconds and 177,585 peak Python bytes.
This audit measured 0.30380s, 19,750 tasks/min, p95 0.28915s, 0.03125 CPU seconds
and 180,257 peak Python bytes. Both recorded zero failures/retries. The roughly
5% wall-time difference is an uncontrolled single-sample comparison on a shared
host, not evidence of a significant regression or optimization. CPU measurements
have coarse Windows timer resolution. Raw 5/10/25/50/100 measurements are retained.

No production throughput claim is made. Browser startup, real-model quota waiting,
RSS, database contention and long-running memory growth need representative soak
benchmarks. The prior baseline was already modified, rather than a pristine Git
checkout; this audit preserves that distinction.

## Remaining risks and release gates

1. Provider-wide RPM/TPM/account concurrency admission is still absent. Per-task
   token budgets, bounded jobs, backoff and configured fallback do not replace an
   account-wide distributed quota. Keep worker capacity within provider allocations
   and implement explicit shared admission before unrestricted scaling.
2. Runner/watch, configuration refresh, some outbound policy reads and API/SSE
   queries still perform synchronous database I/O on event loops. Coordination and
   scheduler offloading reduces blocking but does not eliminate it. Database stalls
   can delay lease renewal and other tasks; async-driver migration or carefully
   bounded transaction offloading needs dedicated follow-up and outage testing.
3. Windows subprocess finalizer warnings remain unexplained on this Python 3.11
   environment. Run the supported Python 3.12 Windows/Linux matrix and process-leak
   soak tests before releasing.
4. Host CPU/memory sampling does not reserve per-task resources, measure all open
   sockets or account for every cgroup limit. Containers still need memory/CPU/PID
   limits and a restart supervisor. Browser processes remain isolated per job.
5. Abrupt host failure, multi-host partitions, actual provider outages and external
   non-idempotent effects cannot be certified by fixture tests. Existing ambiguous
   mutation recovery remains conservative; no exactly-once guarantee is offered.

The second pass reviewed each modified integration point, conditional terminal
updates, SQL/session lifetime, cancellation ownership, retry settlement/deadlines,
proxy teardown and lock ordering. It found and fixed AUD-007/AUD-008 and extended retry
deadline checks to network/schema retries. No broad framework rewrite or speculative
process pool was introduced. The production verdict remains constrained by the
explicit release gates, irrespective of passing local tests.

## PostgreSQL and Redis verification

Dedicated, uniquely named `postgres:17-alpine` and `redis:7.4-alpine` containers
were created for this audit with ephemeral local-only ports. Existing application
containers were not modified. PostgreSQL required initialization time before it
accepted connections; Redis was checked with PING. Tests used only the isolated
`adbot_audit` database and isolated Redis instance.

With `ADBOT_TEST_DATABASE_URL` pointing to that PostgreSQL database and
`ADBOT_TEST_REDIS_URL` pointing to that Redis instance:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py tests/test_concurrency.py tests/test_automation.py -m "not browser"`:
**46 passed, 1 deselected**, 75.09s. The deselected test is the real-browser case,
which passed in the separate browser run. This includes migration roundtrip,
shared counters across threads/processes, capacity, cancellation, recovery and
all non-browser audit regressions including the actual Redis counter test.

With isolated Redis and local SQLite:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_security.py tests/test_privacy.py -m "not browser"`:
**22 passed**, 90.17s. These tests include authorization, SSRF and Redis outage
handling. They do not simulate a multi-host network partition.

The two dedicated audit containers were stopped after the PostgreSQL/Redis runs;
`--rm` removed them. No existing application service was stopped or restarted.
Python bytecode compilation (`.venv\Scripts\python.exe -m compileall -q backend/app`)
also passed. No frontend files changed during this audit; earlier frontend build,
TypeScript and 12-test verification remains recorded in CONCURRENCY_REPORT.md.

Additional claim-contention check:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py::test_parallel_claims_are_unique_and_respect_capacity`:
1 passed, 8.13s. Twenty-five claim calls across eight threads produced exactly two
unique identifiers/tokens under the configured two-job ceiling. It was added
after the broad run was collected and executed separately.

Second-pass monitor verification:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_concurrency_audit.py::test_egress_monitor_survives_policy_database_outage tests/test_outbound.py tests/test_automation_review.py`:
21 passed, 90.65s. The isolated outage reproduction failed before AUD-008 was
corrected, with the monitor task terminated by SQLAlchemyError. The successful
run covers the corrected implementation. The full-suite run was already in
progress when this last monitor fix was made; this targeted run verifies that
final change independently.

Frontend regression checks were also rerun during this audit: `npm.cmd test`
from frontend: 12 passed across 3 files; `npx.cmd tsc -b`: passed. No frontend
source changes were needed for these audit fixes.

## Complete backend regression and follow-up

`..\.venv\Scripts\python.exe -m pytest -q`: **212 passed, 2 skipped, 1 failed**,
1092.17s. Failure was `tests/test_agent.py::test_real_session_state_is_encrypted`.
Its isolated diagnostic rerun (`-vv --showlocals`) passed in 12.12s. This was not
accepted as sufficient: the ordered pair
`test_model_compacts_oversized_observation_before_request` followed by
`test_real_session_state_is_encrypted` reproduced the failure (1 passed, 1 failed,
14.52s). The first test directly assigned the shared Settings request-size limit
to 8,000 without restoring it. That limit then leaked into real Decision-schema
requests in later agent tests. AUD-009 changes only the fixture-setting assignment
to monkeypatch.setattr; no production limits, deadlines or assertions were relaxed.
After correction, `..\.venv\Scripts\python.exe -m pytest -q tests/test_agent.py` passed **33/33**, including the encrypted-session case in its normal order, in 309.13s. The full 215-case run was not repeated after this one-line test-isolation fix; its original failed result remains recorded above.

The two skips are the optional real-Redis test without a default Redis URL and an
existing opt-in local Ollama qwen3:4b test (`ADBOT_TEST_LOCAL_QWEN` was not enabled).
The exact real-Redis audit case passed against the isolated service. The live local
model test was not executed; mock provider and fallback tests do not substitute
for that external model verification.

## Final status

All nine confirmed defect groups have fixes and relevant executed regression
coverage. Final backend-wide Ruff and whitespace checks passed. PostgreSQL/Redis
containers created for testing were removed. The complete backend run reported
212 passed, 2 skipped and one failure, whose deterministic test-configuration root
cause was corrected and verified with the full 33-test agent module. Two additional
audit cases (claim contention and monitor outage) added after broad collection
also passed in dedicated runs. Results are intentionally not combined into a
fabricated all-green full-suite count. The live Ollama test remains unexecuted.

Verdict remains **NOT READY for unrestricted production** pending the three
release gates above. This assessment is independent of test pass counts.
