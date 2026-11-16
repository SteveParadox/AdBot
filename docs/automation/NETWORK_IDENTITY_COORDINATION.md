# Network identity coordination

`app.coordination.assign()` joins the existing job lease to browser identity and routing. It verifies
the current worker token, restores any previous assignment, selects a compatible identity and approved
route, then persists the assignment before Playwright starts. No credentials are stored in these rows.

`network_assignments` has one record per logical job: job ID, worker token, exact User-Agent, endpoint
identifier (null for explicit direct networking), lease expiry and active state. Job heartbeat extends
the matching assignment lease. Worker completion deactivates it; supervisor deactivates expired rows.
History remains until the associated job is removed under the operator's retention policy.

On worker recovery, the original identity is reused and a new fenced worker token is recorded. An
unapproved/removed route, incompatible new mandatory identity, expired lease or stale token fails closed.
Authorized non-authenticated route failover updates the durable endpoint without rotating the identity.
Agent sessions with session persistence or form input enabled prohibit route failover. Proxy guard exit
releases local route bindings, protected-session flags and token mappings even after launch failure.

Counter increments are transactional SQL writes, including insertion races. PostgreSQL locks worker job
rows during owned transactions. Shared circuit updates use compare-and-swap on observation time, so
out-of-order publications cannot erase newer failures. Policy changes use revision CAS. SQLite/WAL is
supported for development; production configuration requires PostgreSQL and Redis.

Workers do not write SQL on every browser resource request: selection is at session creation, routing
strategy/shared health reads have short caches and healthy circuit publication is throttled. Local
connection counters still reflect process-local measurements. Round-robin shared writes are unavoidable
at actual new selections. SQL is part of required routing availability; there is no unsafe local/direct
fallback if authoritative coordination cannot be accessed.

Host clock synchronization and database availability are required. These mechanisms provide fenced
execution and bounded recovery, not exactly-once external side effects. Ambiguous mutations still require
review. Tests cover concurrent threads, a separate counter process, separate managers, expired leases,
new worker tokens, stale writes, changed revisions, shared failure recovery and protected sessions.
