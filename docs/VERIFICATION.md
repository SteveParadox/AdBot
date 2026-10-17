# Implementation and verification report

Date: 2026-10-17. Repository started empty. This report distinguishes executed
checks from deployment work that requires another environment.

## Implemented

- FastAPI API with bearer-key workspace ownership, validation, pagination,
  idempotent enqueueing, request-size bounds, rate limiting and OpenAPI.
- SQLAlchemy SQLite/PostgreSQL models and initial Alembic migration
  `bafc4dc14d9a` covering eight tables, indexes, relationships and uniqueness.
- Asynchronous Playwright worker with fresh browser contexts, navigation,
  bounded scrolling/captures, internal-link discovery and breadth-first traversal.
- Persistent URL frontier, page outcomes, status codes, timings, content hashes,
  screenshot paths, retries and cancellation. API restarts do not lose the queue.
- Global capacity leases, conservative domain serialization, heartbeats, lease
  fencing, expired-worker recovery and bounded browser-crash retries for crawls.
- Strict versioned workflows with twelve action types, safe click restrictions,
  assertions, extraction, captures, URL history, checkpoint pause/resume and
  cancellation. Ambiguous click workflows fail for manual review after a crash.
- Persisted one-time/cron schedules with timezone support, pausing, resuming,
  atomic scheduling and schedule-specific idempotency keys.
- Same-origin React/TypeScript dashboard using TanStack Query, Tailwind,
  shadcn-style Radix button primitives and Recharts. Real target/job/workflow/
  schedule CRUD, job monitoring, page filters, captures, logs and analytics.
- Persisted SSE events with replay/reconnect; no API keys in stream URLs.
- Operator and per-target allowlists, public-IP DNS checks, an IP-pinning egress
  proxy, request/redirect restrictions, robots compliance, Retry-After handling,
  and guarded authenticated artifact serving.
- Docker Compose for PostgreSQL, Redis, migration, API, worker, scheduler and
  frontend; resource limits, volumes and readiness checks.
- Windows CMD, PowerShell, Linux, Docker, configuration, API, security, backup,
  troubleshooting and architecture documentation; GitHub Actions verification.

## Checks executed successfully

| Check | Result |
| --- | --- |
| `python -m pytest -q` | 29 passed; includes real Chromium browser execution |
| `ruff check app tests` | Passed |
| `alembic upgrade head` on SQLite | Passed |
| `alembic check` | No model/schema drift |
| PostgreSQL offline migration SQL generation | Passed; no PostgreSQL server involved |
| `npm test` | 2 SSE parser tests passed |
| `npm run build` | TypeScript and Vite production build passed |
| `npm run test:e2e` | Full UI-driven fixture journey passed |
| `npm audit --audit-level=moderate` | 0 known vulnerabilities |
| `pip-audit -r backend/requirements.txt` | No known vulnerabilities |
| Compose/CI YAML parsing and service wiring checks | Passed |

Browser tests cover persisted titles/statuses, deliberate 404, URL deduplication,
robots exclusion, page/depth limits, captures and authenticated retrieval,
scrolling, approved clicks, text assertions/extraction, URL history/back action,
cancellation, navigation timeout, blocked metadata redirect, and bounded 429
retries. Other tests exercise ownership, key authentication, idempotency
conflicts, immutable job configuration, concurrent claiming, global/domain
capacity, expired leases, stale worker fencing, workflow versions/validation,
schedule enqueueing, SSE replay and real-data analytics. Browser-process loss is
simulated for retry-budget testing; an actual crashed browser process was not
injected into the deployment.

The UI journey starts its own API, worker, scheduler, fixture and Vite server,
registers a website through the dashboard, runs a real crawl, inspects persisted
results and a PNG, confirms execution events, and creates/pauses a schedule.

One test-client deprecation warning remains: current Starlette prefers `httpx2`
for its test client. Tests currently use its supported compatibility path with
httpx; runtime network requests use httpx directly.

## Limitations and unverified deployment checks

- Docker is unavailable in the implementation environment. Images were not built
  or booted here. A live PostgreSQL/Redis integration run was not possible here;
  a dedicated CI job is supplied. Offline SQL generation is not a substitute.
- Only Chromium execution was verified. Firefox/WebKit launch paths are present;
  their binaries downloaded, but the host lacks required shared libraries for
  complete engine validation. Docker installs browser OS dependencies.
- Native Windows commands are documented but were not executed on Windows.
- No public production site, load test, backup restore, external TLS endpoint or
  OS firewall/sandbox certification was executed. Validate those on your server.
- Application-layer domain/IP checks and the proxy do not replace OS-level
  browser isolation. Complete production egress tests for each selected engine.
- API keys represent workspaces; there is no account login, RBAC, team management
  or target-site credential storage. Key rotation requires ownership planning.
- Dashboard dropdowns/configuration lists currently load up to 200 targets,
  workflows or schedules; jobs and page history have pagination. APIs paginate
  every collection.
- Workflow checkpoints retain URL history and completed action position, not
  arbitrary transient DOM state. The global session budget continues during
  pause and after crash recovery. Click workflows require manual review after
  ambiguous failures.
- Per-domain locking deliberately over-serializes shared hostname suffixes.
  Ad/engagement evasion, form submission and account-changing automation are
  excluded from the product.
- Browser/runtime versions are pinned for reproducibility. Package audits do not
  certify bundled browser binaries; review browser security updates before
  exposing workers to production targets.

## Start commands

See the root README for copyable Windows and Linux installation commands.
Once dependencies, `.env` and migrations are ready, from `backend/`, run these
in separate terminals:

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.worker
python -m app.scheduler
```

Use the virtual environment's Python executable. From `frontend/`, run
`npm run dev`, then connect at http://127.0.0.1:5173 using your generated key.
For containers, run `docker compose up -d --build --wait` from the root and open
http://127.0.0.1:8080.

Assessment: working and locally tested monitoring application with production
deployment scaffolding. Production readiness remains conditional on the
deployment checks listed above; it is not represented as certified or fully
verified in an environment that was unavailable.
