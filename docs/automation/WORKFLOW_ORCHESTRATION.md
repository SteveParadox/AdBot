# Workflow orchestration

Use existing website/workflow/agent APIs. No advertising or other new business workflow is invented.
Authorized jobs already execute automatically; schedules already create durable jobs. New controls add
policy coordination around those mechanisms.

`POST /api/jobs` and `POST /api/agent/tasks` accept `priority` (-10 through 10, default 0) and optional
`depends_on` (one existing job in the same workspace). Larger priority runs first, with creation time as
the tie-breaker. Dependency edges are immutable after creation and point only to existing jobs, so normal
API creation cannot create a cycle. Multiple parents / generic workflow graphs are not supported.

```json
{"website_id":"approved-website-uuid","priority":4,"depends_on":"existing-parent-job-uuid"}
```

Only successful parent completion releases the child. Failed or cancelled parents fail their queued
children with a durable explanation; dependencies are resolved during normal pickup. Domain and global
slot leases still bound simultaneous work. Idempotency keys cover priority/dependency changes while
retaining compatibility for old requests using default fields. SQL queue state remains durable if a Redis
wakeup is unavailable.

Automation defaults preserve existing automatic operation. `enabled:false` stops automatic pickup and
schedule creation; an administrator can release an owned queued job explicitly. `paused:true` also stops
manual releases from being claimed and pauses active jobs at existing action gates. Per-website and
job-type exclusions stop new eligible pickup; active excluded jobs are cancelled by their watcher.

`max_backlog` caps new queued jobs from API requests, agent tasks, manual retries and scheduled ticks.
PostgreSQL policy-row locking serializes capacity checks. An existing idempotent request can still return
its already-created job when full. Full queues leave due schedules pending; they do not silently consume
their due occurrence. Overdue recurring schedules coalesce using the existing next-occurrence behavior.

Job control endpoints stay `/api/jobs/{id}/pause`, `/resume`, `/cancel` and `/retry`. Manual retry retains
priority and dependency and creates a new history record; it cannot bypass a failed dependency. Agent
tasks and CLICK workflows require explicit reviewed relaunch. Completion events and optional durable
in-app notifications appear centrally. There is no unsolicited email or webhook integration.

Existing session duration, per-destination delays, Retry-After, budgets and approval gates remain.
Pause time counts toward the existing total session deadline. Cancellation cannot undo a request already
sent. Expired read-only work can recover within its budget; ambiguous mutation outcomes cannot be replayed
automatically. See [self recovery](SELF_RECOVERY.md).
