# Architecture and durability

## Process boundaries

The Vite/React dashboard uses a same-origin `/api` proxy. FastAPI validates and
persists configuration and control requests. Browser work runs exclusively in
`app.worker`; recurring execution runs in `app.scheduler`. Neither background
process lives inside the API, so restarting the API does not discard jobs.

SQLAlchemy supports SQLite/WAL locally and PostgreSQL in production. Alembic's
initial migration creates websites, automation_jobs, page_visits,
discovered_links, workflows, schedules, automation_events, and leases. Foreign
keys cascade owned data on deletion; schedule/workflow dependencies restrict
unsafe deletion. `source_page_id` is a provenance identifier, not a circular
foreign key; `page_visits.frontier_id` enforces frontier/visit association.

## Queue and execution

The SQL `automation_jobs` table is the durable queue and authoritative state.
Redis delivers bounded wakeups and provides shared API rate counters; losing a
wakeup cannot lose the job. Workers also poll SQL, so local SQLite operation does
not need Redis. Production startup requires Redis and PostgreSQL.

Claiming a job acquires a compare-and-swap database lease, one global capacity
slot, and conservative domain leases in a consistent sorted order. Defaults allow
two browser jobs globally, while each domain group has only one active job.
Domain groups use the last two hostname labels; this deliberately over-serializes
some public suffixes such as `co.uk`, preventing excess concurrency at the cost
of throughput. This is not a public-suffix parser.

Workers heartbeat every ten seconds. Every persistence operation checks the
lease token and expiry. A dead worker's lease expires after 90 seconds; recovery
requeues unfinished crawl URLs, retaining committed results. Recovery has a
policy-configured retry ceiling and preserves the original session deadline. This provides
at-least-once read-only navigation, not exactly-once HTTP execution. A page read
can repeat if a worker dies between its network request and database commit.

Jobs snapshot target configuration and workflow definitions at creation time;
later edits apply to new jobs. The unique `(owner, idempotency_key)` constraint
prevents duplicate manual creation. A mismatched request with the same key
returns 409. A unique `(job_id, normalized_url)` frontier entry prevents duplicate
visits from fragments and repeated links. URL query strings are retained because
they can identify distinct pages; page/depth/frontier/session limits bound loops.

The scheduler stores timezone-aware instants as UTC epoch seconds and evaluates
cron expressions in IANA timezones. A compare-and-swap update advances the due
instant in the same transaction that creates the job. A schedule-specific
idempotency key prevents duplication. Missed recurring runs coalesce into one
run on recovery, and the next occurrence is computed after the current time.
One-time jobs are disabled after enqueueing. DST behavior follows croniter and
zoneinfo; review schedules near transitions for your own timezone requirements.

Cancellation stops browser work and closes resources. Pausing gates the next
action/page while heartbeats continue. Shutdown cancels owned active runs;
ungraceful process loss is recovered after lease expiry. CLICK workflows never
auto-recover and cannot be retried through the retry endpoint, since a click
may have happened before its checkpoint committed. Review the result and start a
new job explicitly. Read-only workflows restore their last durable URL history
and action index; transient DOM state is not snapshotted.

## Browser and network boundary

Each job launches a fresh browser and context. A temporary loopback forward proxy
resolves destinations, rejects any DNS answer containing a non-public address,
and opens its upstream socket to that validated IP. HTTPS uses CONNECT, leaving
certificate verification to Playwright/httpx. This pins sockets against DNS
rebinding rather than validating DNS and then letting the browser resolve it
again. Proxy connections are limited by timeouts and header-size limits.

Context routing independently checks every request's destination and method,
including redirected navigations, and validates robots rules for document
navigation. Service workers and WebSockets are blocked. Chromium disables
non-proxied WebRTC UDP and QUIC; Firefox disables peer connections. Network-level
egress enforcement remains necessary for production isolation, particularly for
browser-internal channels and WebKit. Application routing is not an OS sandbox.

An operator allowlist narrows user allowlists in production. Agent clicks run
autonomously within that boundary. Form input requires the task's explicit
permission; secret, payment and file controls are unavailable. A validated
activation can grant one matching mutating request, after checking the form and
destination; arbitrary background writes remain denied. Links and downloads
must pass navigation policy. No user-provided code runs. Ad identification is not universally
inferable from markup: operator authorization must exclude ad selectors and
destinations. Do not schedule this software to inflate visits or engagement.

Robots files are fetched through the same proxy, bounded to 512 KB, and redirects
must remain permitted. 404/410 means no rules; other retrieval failures deny the
navigation. Crawl-delay increases the per-page delay. HTTP 429/503 honors
Retry-After with bounded retries; a backoff beyond the session budget ends the
job rather than retrying early.

## Events and artifacts

Events commit with job/page state. SSE accepts Last-Event-ID, replays persisted
events, sends keepalives, and rotates connections every 55 seconds. The dashboard
reconnects with its cursor and also polls persisted state. API-key headers are
used instead of placing credentials in event-stream URLs.

Screenshot names are generated UUIDs under a configured directory. Serving a
capture checks the job owner and containment within that directory. Captures
use viewport bounds to avoid unbounded images. Retention removes old terminal
jobs and screenshot files hourly. Screenshots and extracted text can contain
target-site information; they are deliberately available only to the owning key.


### Dashboard refresh and cache policy

See [the traffic architecture and verification report](traffic-optimization/REPORT.md)
for the audit, research, event contracts, bounds and measured results.

A single bearer-authenticated workspace SSE connection per visible tab patches
cached job/task rows, execution steps and logs. Initial authenticated snapshots
follow the stream cursor; degraded startup releases reads and later reconciles.
TanStack Query owns authorization-scoped caches and cancellation. Identical GETs
share a transport; obsolete consumers cancel independently. Metadata invalidates
on modification, while related extraction events refresh only affected outputs.
Task-specific HTTP fallback runs at 30 seconds only while streaming is degraded,
and stops for terminal details. Metrics refresh at 15 seconds and analytics at
60 seconds. Hidden tabs stop intervals and close streams. A backend worker remains
independent of frontend visibility.

SQL resource-change notices commit atomically with API database writes. Replay,
process epochs, retention-gap resets and bounded recovery restore consistency.
PostgreSQL additionally emits a 60-second safety reconciliation because sequence
IDs can commit out of order. SQLite uses its single-writer ordering. The server
polls both durable logs with one idle SQL statement and holds no database session
across a network yield. No new broker dependency is required.

Deployment requires Alembic `021a00000001` before starting the new backend. The
legacy per-job SSE endpoint remains compatible; the new frontend consumes the
workspace stream. Configuration writes that bypass API notices still require an
explicit workspace refresh. Full task-memory snapshots are refreshed on demand.
