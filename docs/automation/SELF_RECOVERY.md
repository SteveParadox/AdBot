# Failure detection and recovery

The existing scheduler now supervises jobs every 30 seconds. Workers also reconcile expired job leases
before pickup. CAS and lease tokens prevent concurrent recovery from granting duplicate ownership.

| Failure | Automatic response | Operator action when persistent |
|---|---|---|
| Worker disappears | Lease expires; safe frontier/action state reconciled; compatible session assignment reused | Inspect supervisor logs and last durable action |
| Ambiguous CLICK / agent mutation | Fail task for manual review rather than replay | Inspect external result and explicitly create a new reviewed task |
| Browser disconnect | Existing safe recovery with min(site retry budget, global recovery budget) | Inspect browser installation/resources and job logs |
| Job timeout | Cancel browser tasks, close context/guard, mark failed | Adjust approved budget or reduce workload |
| Database outage in worker/scheduler | Bounded exponential retry (2–30 seconds), exit after six consecutive failures | Deployment supervisor applies bounded backend restart policy; repair database |
| Redis wakeup unavailable | SQL polling continues; authoritative API rate-limit outages fail safely | Restore Redis and readiness |
| Proxy failure | Shared circuit opens; permitted replacement only; fixed/protected sessions fail closed | Repair endpoint/credentials/CA or review provider routing |
| Revision watcher failure | Log exception class, retry with backoff up to 30 seconds; normal read fallback remains | Repair configuration or SQL; do not bypass validation |
| Queue full / no workers | Durable in-app alert at most once per code per 60 seconds | Review workload, workers, leases and configured capacity |

The dashboard shows live worker leases, active browser assignments, queue outcomes, last successful job,
operational alerts and network diagnostics. Heartbeat state includes PID, process CPU seconds and active
job count. CPU seconds are cumulative process measurements, not host CPU percentage. Use the hosting
monitor for RSS, host CPU, disk capacity, container health and external alert delivery.

Readiness validates required schema tables and database/Redis connectivity. It does not assert that a
worker exists; the supervisor/dashboard provides that separate signal. A live but unhealthy container is
not automatically restarted by plain Docker Compose health checks. Use the hosting supervisor/monitor
to act on persistent readiness failures. Bounded process restarts handle actual failed process exits.

Hourly maintenance uses operator `ADBOT_RETENTION_DAYS` (default 30) for terminal job history/artifacts,
retains parents while children reference them, removes expired memory, one-day stale heartbeats and
leases expired for more than an hour. Network assignment deactivation runs during supervision.
Global operational/policy audit records are not automatically purged; define approved archival/retention
in the database operations policy. Emergency stop never disables audit logging or necessary cleanup.

No host-wide arbitrary process scan/kill, self-modifying application code, backup-provider provisioning
or infinite application retry is introduced. Abrupt host/container failure still requires the deployment
supervisor, storage durability, monitoring and a tested restore procedure.
