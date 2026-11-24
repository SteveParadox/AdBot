# Initial architecture audit ? baseline 09139bb

The machine-readable INITIAL_INVENTORY.json records every frontend request,
query, invalidation, timer, subscription and network-related effect before edits.

| Request family | Initiator / trigger | Backend and database work |
| --- | --- | --- |
| websites, workflows | App, initial load or mutation | Owner-filtered SQL collections; count + rows |
| jobs/recent-jobs | App and Jobs, 30s timer AND every workspace event | Owner/filter SQL collections; count + rows |
| overview | App, 60s | Aggregate SQL across jobs, visits, schedules |
| agent tasks | AgentPanel; every workspace event | Job page + count + per-row AgentTask lookup (N+1) |
| task detail | AgentDetail; task-stream event coalescing | Owned Job + AgentTask |
| steps | AgentDetail; same stream batches | Ownership checks + count + up to 100 full steps |
| logs | useJobEvents, initial | Owned Job + count + latest bounded events; stream merge afterward |
| datasets/schemas/templates | Extraction / agent form; global invalidation | Collections/counts/schema; templates static |
| records/changes/runs/exports | Selected extraction panel; global invalidation | Dataset ownership then paginated SQL |
| memories/config | AgentPanel; initial and mutations, memory also terminal/sync | Owner SQL / settings |
| content/admin-content | Content hooks; initial/save | Published or admin-authorized sections |
| schedules/network/automation | Relevant panels, 30s; schedules App defaults | SQL jobs/workers/schedules or connection-health snapshot |
| artifacts/export downloads | Screenshot effect or user click | Owned job/artifact metadata + disk file |
| workspace SSE | App effect / reconnect / visibility | Max owner event ID on every connection, then SQL each second |
| per-job SSE | Detail effect / reconnect / visibility | Owned Job + event SQL every 0.5s |

Confirmed causes: broad global event invalidation, overlapping job timers, a
second per-detail SSE connection, duplicated local invalidation after centralized
mutation invalidation, reconnect sync invalidation even without a gap, and an
in-flight refresh helper that may deliberately fetch twice. Strict Mode makes
setup/cleanup visible but is not itself a production polling bug. No unstable
array dependencies drive the current stream effect. Completed details stop
streaming, but cached live logs can be overwritten by an older initial GET.

GET coordination shares promises by credential/URL/headers but has no consumer
cancellation. Query functions do not consume TanStack AbortSignals. SSE has no
shared ownership, idle watchdog, jitter, state reporting, or bounded frame parser.
Backoff retries forever at a bounded interval; active normal streams close after
55 seconds. No cross-tab coordination or observability counters exist.

Logging: Redact renders record.msg and clears record.args, but leaves the original
color_message format placeholders. Uvicorn DefaultFormatter can then print an
unformatted colored startup message. Preserve the same rendered template in both.

Existing security: owner filtering, artifact ownership, API-key rate limits,
no-store responses and redaction must remain. Keep SQL as the durable replay
source; Redis is optional and adding Redis Streams/Iggy/Temporal is unjustified
for this scoped refinement. Multi-process safety must not rely on a local-only
publisher. No third-party source code will be copied.
