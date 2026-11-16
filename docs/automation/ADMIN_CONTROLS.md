# Automation Control Center

Use a valid workspace key which is also listed in operator `ADBOT_CONTENT_ADMIN_KEYS`. The Automation
tab polls actual backend state every five seconds and embeds network diagnostics and User-Agent
management. Global counts and controls span workspaces; recent detailed jobs and job actions remain
limited to the administrator key's own workspace.

`GET /api/admin/automation` returns policy/revision, job counts, unexpired worker heartbeats, active
browser assignment count, last successful job, last 50 operational events, last 20 approved policies and
last 20 owned jobs. Operational events expose safe IDs and approved policy, not proxy credentials or
browser storage. Historical policy selection loads an editable draft and requires a new save.

`POST /api/admin/automation` takes `{revision, policy}`. Revision is required; stale saves return 409.
The editor keeps the revision at the start of editing and preserves conflicting text. Discard/reload
and review your changes before saving again. Quick pause/emergency actions preserve existing drafts.

Policy fields:

| Field | Effect |
|---|---|
| `enabled` | Automatic worker pickup and schedule creation; false requires manual queue release |
| `paused` | Stop pickup/ticks and gate active actions; existing session deadline still applies |
| `emergency_stop` | Cancel queued jobs, request cancellation of active jobs; clearing does not revive cancelled work |
| `concurrency` | Runtime global slot count, bounded by operator `ADBOT_MAX_CONCURRENCY` |
| `recovery_retries` | 0–3 lease/browser recovery attempts; browser site limit may be lower |
| `max_backlog` | 1–100000 queued-job admission cap |
| `disabled` | Excluded `crawl`, `workflow`, `agent` and/or `schedules` integration classes |
| `disabled_websites` | Website IDs excluded from pickup/ticks; active jobs cancelled |
| `health_interval_seconds` | 10–3600 seconds between proxy health passes |
| `proxy_strategies` | Strategy overrides for already approved, rotatable required integrations |
| `maintenance_enabled` | Enable hourly approved-retention cleanup; essential lease/session reconciliation continues |
| `notifications` | Completion/failure and supervisor in-app notifications; security/policy audit remains enabled |

Example conservative rollout: fetch current revision, set `enabled:false` and `paused:true`, retain the
remaining fields, save, migrate/deploy, inspect readiness/heartbeats, then resume an explicitly released
owned read-only job. Enable automatic pickup after verification. Existing operator security capabilities
cannot be enabled by this JSON.

Use `POST /api/admin/automation/jobs/{id}/release` for an owned queued job in manual mode. The dashboard
also provides existing cancel/safe-retry actions. Configure schedules in the existing Schedules tab and
inspect job/agent action history in Jobs/AI Agent. Workflow/agent approvals, publishing CMS changes,
changing credentials and provisioning infrastructure still require the corresponding authorized action.

Emergency stop is cooperative and bounded by existing action/connection timeouts; it cannot recall
external requests already sent. Cleanup and audit continue. Keep host/service controls available for an
unresponsive process. Administrator 403 means the key lacks the existing admin role; it is independent
of the Uvicorn logging error fixed in `privacy.py`.
