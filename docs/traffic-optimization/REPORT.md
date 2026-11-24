# Adbot API traffic optimization and event synchronization

24 November 2026. Baseline: `09139bb`. Implementation is in the working tree.

## Audit, causes and evidence

[AUDIT.md](AUDIT.md) traces production request families from components to SQL;
[INITIAL_INVENTORY.json](INITIAL_INVENTORY.json) records the original request,
effect, timer, retry and invalidation sites before changes.

Confirmed causes were broad invalidation after every workspace event, a second
per-detail stream, job timers overlapping healthy streaming, repeated full-step
reads, duplicate save/refetch paths, component lifecycle connection churn,
uncancellable shared reads, and N+1 task/run/export collection queries. Development
Strict Mode exposed the ownership problem; it was retained.

The initial inspection also found a logging mismatch: the redactor formatted
`record.msg` and cleared its arguments while Uvicorn's colored template still
contained placeholders. Both templates now use the same redacted rendered text.

[RESEARCH.md](RESEARCH.md) links primary references and explains why SSE, SQL and
the installed TanStack Query were retained. No dependencies or third-party source
were added.

## Implemented architecture

1. A single shared authenticated workspace stream supplies each visible tab.
   Detail views consume the Query cache instead of opening a per-job stream.
   Short bounded ownership/transport grace periods handle Strict Mode remounts.
2. Initial authenticated queries wait for the stream's cursor. If startup fails,
   fallback reads are released; a later stream connection reconciles that gap.
   Public reads and explicit API actions are independent of this startup barrier.
3. Concurrent GET identity includes the token, URL/parameters and extra headers.
   The agent form and extraction view share one dataset metadata cache across target
   changes. Each cancellable consumer releases independently; the transport aborts after
   its last consumer leaves. There is a 30-second HTTP deadline and a bounded
   pending-read registry. Mutations are never deduplicated.
4. Stream batches contain authoritative job/task patches and the referenced
   execution steps, loaded with batched SQL. Only the last event per job in each
   server batch carries its current snapshot. Large session memory stays in the
   initial or explicitly refreshed task snapshot rather than every event frame.
5. Cached rows and steps update by ID; task and job pagination/filter membership
   remain intact. Logs merge incrementally, retain 200 entries, and use a tail
   snapshot on first inspection. Initial GETs and subsequent patches are fenced
   against stale responses; reset generations discard pending old-session reads.
6. Incomplete/legacy or oversized payloads trigger narrow reads; small routing
   hints survive snapshot stripping so terminal memory/extraction updates remain targeted. Relevant dataset
   events invalidate selected outputs, not unrelated agent events. Mutations map
   to affected cache families; tombstones also invalidate cached child resources.
7. SQL-backed resource-change notices commit with API database writes, including
   bulk ORM updates. File-only configuration writes have a logged best-effort
   fallback notice. Resource paths carry no payloads or credentials. Opaque
   request IDs suppress duplicate local-save and echoed-SSE invalidations.
8. Same-owner tabs exchange modification notices on a SHA-256-scoped
   BroadcastChannel. Credentials and resource contents are not broadcast. Each
   visible tab keeps its own stream; no cross-tab leader-election dependency was
   introduced. Server SQL replay remains authoritative across processes.
9. Frames, replay-deduplication sets, patch versions, invalidation queues, pending
   GETs, cooldowns, acknowledgment sets and server batch caches have explicit
   bounds. Overload triggers an owned-query reconciliation. Server SQL sessions
   close before network yields, so slow readers do not pin pooled connections.
10. Worker pause acknowledgment now closes its action gate before publishing
    paused status. Read-only control checks avoid unnecessary write transactions;
    actual control transitions publish events for the dashboard.

## Refresh and recovery contract

| Resource | Normal operation | Recovery |
| --- | --- | --- |
| Active task/job status, steps and logs | Stream patches/appends | Targeted 30s reads while stream is degraded; none for known terminal details |
| Task and job collections | Patch known rows; reconcile creation/filter membership | Bounded degraded-mode refresh and reconnect reconciliation |
| Dataset records, changes, runs, exports | Relevant dataset/job events | Selected runtime outputs refresh in degraded mode |
| Configuration, websites, workflows, content, memories, dataset metadata | Initial snapshot and actual modification notices | Explicit Refresh, server-epoch/retention reset or necessary reconciliation |
| Agent metrics | 15s, visible tabs | Auth expiration stops private queries |
| Analytics | 60s, visible tabs | Explicit Refresh |
| Automation/schedules/network health | Existing bounded 30s operational snapshots | Explicit Refresh |

Connections use 15s handshake and 45s idle watchdogs, heartbeats, replay cursors,
monotonic cursor advancement, bounded duplicate detection, exponential backoff
with jitter and Retry-After. Nine consecutive failed attempts exhaust automatic
retry until visibility/online/explicit refresh initiates recovery. Authentication
failure returns to login. Hidden tabs close streams; backend jobs continue.

The workspace endpoint stays open rather than rotating every 55 seconds. The
legacy per-job endpoint is preserved. A process epoch detects API restarts and
reconciles configuration; a cursor reset clears ordering fences and stale logs.
Retention gaps force a complete owned-cache reconciliation.

PostgreSQL sequence reservation is not commit ordering. An intentional repair
sync every 60 seconds over the existing socket reconciles active cached state;
this is a consistency tradeoff, not an exactly-once event bus. SQLite's single
writer does not require that periodic repair. Normal updates remain event driven.

## Performance results

See [BENCHMARKS.md](BENCHMARKS.md) and the raw BEFORE/AFTER JSON artifacts.

| Controlled workload | Before | After |
| --- | ---: | ---: |
| Idle dashboard, 62.1 virtual seconds | 9 HTTP reads | 6 HTTP reads |
| Active task, same duration | 142 HTTP reads | 17 HTTP reads |
| Unrelated task while viewing extraction | 165 HTTP reads | 10 HTTP reads |
| Dataset reads in that extraction workload | 32 | 1 |
| Active-view connection opens including Strict Mode | 3 | 1 |
| SQL statements per 25-task collection | 27 | 3 |
| Local TestClient p95, 50 warm reads | 54.913 ms | 33.350 ms |
| Four-owner / four-thread SQL statements, 40 reads | 1,080 | 120 |

The browser workload uses real React/Chromium with mocked API responses; it
measures request counts and JSON bytes. The backend workload uses actual
FastAPI/SQLite and checks each owner's response IDs. The report explicitly
separates these from unmeasured production latency, total wire bandwidth, RSS
and cluster capacity. Do not extrapolate these small fixtures to a production SLA.

## Observability

`window.adbotTraffic()` exposes bounded aggregate frontend counters: HTTP requests,
deduplicated/cancelled requests, query fetches/invalidations, observer cache hits
and misses, stream opens/reconnects/active count, duplicate events, delivery and
processing time totals, bounded queue depth/high-water, overflow recovery, and development Profiler commits.
It exposes no tokens, resource IDs, query strings or payloads. Observer mounts
are cache-hit/miss samples, not a packet-level global cache-hit rate.

`GET /api/admin/traffic` is authenticated and scoped to the caller's workspace in
this API process. It reports endpoint-template counts, request rate, SQL statement
counts, errors, first-response latency samples and active workspace streams.
`X-Request-ID`, UTC timestamps and structured request logs correlate diagnostics.
Streaming body duration and SQL work after initial headers are not represented
as ordinary request-response latency. Public traffic remains in request logs;
these workspace counters are not a cluster-wide telemetry backend. Existing
ResourceMonitor host sampling remains available to the worker. The benchmark
separately measures Python process CPU and traced heap.

## Automated verification

Final results and commands are recorded in [TEST_RESULTS.json](TEST_RESULTS.json).
Frontend: 59 unit tests passed, and the TypeScript/Vite build passed. The full
browser regression passed 18 cases; the final focused traffic run passed 8 cases,
including a new dataset-cache reuse case (19 distinct browser scenarios overall).
Backend snapshot: 305 cases passed with one skipped; three static deployment
checks initially lacked copied Docker fixtures. All three passed after copying
those existing fixtures, yielding 308 verified passing cases across the full run
and focused recheck. Ruff and isolated Alembic upgrade/schema checks passed.
This is not represented as a single zero-failure full-run transcript. The final
oversize-routing and explicit-publication fixes were subsequently checked with
the focused event suite (16 passed, including one new case beyond that snapshot);
the recorded hashes distinguish these from the frozen full-suite snapshot.
The browser cases cover real agent execution, planning preview, browser crawls,
artifacts, extraction/export downloads, content publication and conflict handling,
automation controls, desktop/mobile navigation, a 300-event burst, Strict Mode,
visibility/replay, outage/fallback recovery, credential expiry, cross-tab isolation,
cursor reset and initial snapshot ordering. Unit and backend tests additionally
cover cancellation, stale GET races, authorization isolation, ordering, payload
limits, SQL query counts, tombstones, transaction notices, retention gaps and
logging. PostgreSQL repair control flow is unit tested; a live PostgreSQL load
test is not claimed.

Intermediate checks caught an incorrect explicit step-table join and a pause
acknowledgment race; both were fixed. The final audit also prevents duplicate file-only change publication. Early runs also encountered browser cold
startup and a development-source reload during editing; frozen-source runs were
used afterward. Later full-suite subprocess failures reflected unrelated provider
configuration edits arriving concurrently. Those edits were preserved. The final
backend verification uses the source snapshot fingerprinted in
[QA_SOURCE_HASHES.json](QA_SOURCE_HASHES.json), without copying a developer .env.
The E2E harness supports that backend snapshot and explicit fixture provider settings.

## Deployment and rollback

Apply Alembic revision `021a00000001` before the updated backend: it creates the
resource-change table and adds the `(job_id,id)` event replay index. From the
backend directory run `python -m alembic upgrade head`, then `python -m alembic check`.
Deploy backend first, then the frontend build. Existing endpoints remain valid;
new stream fields are additive. Old/incomplete task events retain a targeted-read
fallback. Mixed-version metadata invalidation is less complete, so finish the
backend-first rollout rather than relying indefinitely on an old server.

Forward Authorization, Last-Event-ID and X-Resource-Cursor through the proxy;
disable stream buffering/caching and allow heartbeat traffic. Prefer HTTP/2 when
many visible tabs share an origin. The implementation requires no new Redis or
broker service. Retain the existing production PostgreSQL/Redis/security settings.
Resource-change history is lazily retained for 24 hours; expired history is
repaired by snapshots, not replayed indefinitely. Do not downgrade the new table
while the updated backend is still running. A code rollback can retain this
additive schema, then downgrade after stopping new code if required.

## Final audit and limits

Authorization and artifact ownership are preserved; protected responses remain
no-store. Cache and subscription identities include authorization context. All
benchmark databases and model requests are local fixtures. Request logs and
notices contain templates/paths and correlation metadata, not credentials or
private resource contents. No new remote service, package or deployment was
introduced.

Remaining limits: one stream per visible tab rather than one across all tabs;
process-local counters and batch caches; SQL polling behind SSE rather than
native database push; conservative reconciliation when payloads/history are
insufficient; eventual repair for PostgreSQL commit-order gaps; large task memory
requires explicit refresh for its latest full contents; and writes that bypass
the API/event path require explicit Refresh. Anonymous public pages fetch published
content on load and do not subscribe to an authenticated workspace stream.
Live PostgreSQL/Redis load, Firefox/WebKit and production proxy behavior were not
benchmarked here. No production-scale guarantee is inferred from the fixtures.

[IMPLEMENTATION_FILES.json](IMPLEMENTATION_FILES.json) lists traffic-scope files.
Unrelated provider/model edits and deletions in this shared working tree were
not reverted or included as traffic implementation work.
