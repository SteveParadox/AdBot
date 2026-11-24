# Reproducible traffic benchmarks

Baseline: immutable Git commit `09139bb`. After: this implementation's working tree.
All workloads use fixture data, temporary SQLite databases and local model/browser
fixtures. No production database or live model provider was benchmarked.

## Actual browser, controlled API

The same `scripts/benchmark_traffic.mjs` ran against a source copy of the baseline
and the updated application. Chromium mounts the real React application, including
Strict Mode. An authenticated mocked SSE connection sends a valid initial sync;
the active scenarios deliver three progress events per virtual second. The same
fixture event payload is supplied to both versions. Browser time advances through
62.1 seconds after a brief initialization warmup. Results include initial reads.
The API responses are mocked: these are traffic counts, not server latency claims.

| Metric | Before | After | Change |
| --- | ---: | ---: | --- |
| Idle dashboard HTTP reads | 9.000 | 6.000 | 33.3% reduction |
| Active-task HTTP reads | 142.000 | 17.000 | 88.0% reduction |
| Unrelated task while viewing extraction: HTTP reads | 165.000 | 10.000 | 93.9% reduction |
| Active-task reads per virtual minute | 137.198 | 16.425 | 88.0% reduction |
| Connection opens during active-task mount | 3.000 | 1.000 | 66.7% reduction |
| Active-task JSON response bytes | 30,051.000 | 1,695.000 | 94.4% reduction |
| Task detail reads | 32.000 | 1.000 | 96.9% reduction |
| Execution-step reads | 32.000 | 1.000 | 96.9% reduction |
| Dataset reads during unrelated task | 32.000 | 1.000 | 96.9% reduction |

A connection-open count includes development Strict Mode's cancelled initial
connection; it is not a claim about simultaneous production sockets. Steady-state
active detail views previously owned both a workspace and a per-job connection;
now there is one shared workspace connection per visible tab.

The initial preflight measurements, taken before any implementation changes,
remain in BEFORE_INITIAL.json and AFTER_INITIAL.json. The final BEFORE.json and
AFTER.json use the refined, identical harness with explicit initial SSE sync and
an immutable baseline source copy. Initial numbers are not mixed into the final
comparison. Small timer-boundary differences are not statistically significant.

## Actual FastAPI and SQLite reads

`scripts/benchmark_backend_traffic.py` creates four isolated owners with 25 tasks
each. After one warmup, it measures 50 sequential collection GETs, then 40 GETs
across four threads. Every response's IDs are checked against the requested owner.
SQL counts come from SQLAlchemy's statement-execution hook, excluding driver-level
pool pre-ping. Request timing includes TestClient and JSON validation overhead.

| Metric | Before | After | Change |
| --- | ---: | ---: | --- |
| SQL statements per 25-task collection | 27.000 | 3.000 | 88.9% reduction |
| SQL statements across 50 reads | 1,350.000 | 150.000 | 88.9% reduction |
| TestClient latency p50 | 50.869 ms | 31.469 ms | 38.1% reduction |
| TestClient latency p95 | 54.913 ms | 33.350 ms | 39.3% reduction |
| TestClient latency p99 | 56.971 ms | 34.316 ms | 39.8% reduction |
| Python process CPU for 50 reads | 2,468.750 ms | 1,578.125 ms | 36.1% reduction |
| Traced Python heap peak | 805,902.000 bytes | 709,664.000 bytes | 11.9% reduction |
| SQL statements across 40 concurrent reads | 1,080.000 | 120.000 | 88.9% reduction |
| Four-thread / four-owner read workload | 655.054 ms | 366.326 ms | 44.1% reduction |

REST JSON response body bytes remained identical: 1,030,600 across
50 reads. Query batching preserves the task API schema. The concurrent workload
verified all four owner-specific response ID sets. These small local samples are
not production throughput or capacity limits.

## Metrics without a defensible before/after value

- Total wire bandwidth, including SSE payloads, headers, TLS and compression, was
  not captured. JSON response bytes above must not be labelled total bandwidth.
- System CPU percentage, process RSS and production memory pressure are not
  attributable to this app on a shared workstation. Process CPU time and traced
  Python heap are measured above; they are different metrics.
- No baseline event-to-UI latency instrument existed. The browser regression
  attaches a synthetic driver-observed event-to-render wall-time sample; it is
  not a production latency percentile or a before/after improvement claim. The
  two recorded 300-event burst samples were 477 ms and 428 ms; see EVENT_UI_LATENCY.json.
- Concurrent duplicates were already deduplicated in the baseline; the new
  cancellation/deduplication tests preserve that property. Repeated endpoint
  reads caused by invalidation are not classified as simultaneous duplicates.
- PostgreSQL, Redis, production reverse proxies, Firefox and WebKit were not
  load-benchmarked. PostgreSQL has an intentional 60-second repair sync for
  sequence/commit-order gaps; these SQLite workload counts do not include it.

## Reproduction

From the repository root, with existing dependencies installed:

```text
node scripts/benchmark_traffic.mjs docs/traffic-optimization/AFTER.json
.venv/Scripts/python.exe scripts/benchmark_backend_traffic.py --output docs/traffic-optimization/BACKEND_AFTER.json
```

Use `BENCHMARK_FRONTEND_ROOT` for an immutable baseline frontend source directory
and `--source` for its backend. The frontend copy must resolve the same installed
node_modules. The harness creates a separate temporary Vite cache. On Unix use
`.venv/bin/python` instead. The backend harness always overrides its database,
authentication and provider settings with fixtures. It does not launch workers.
