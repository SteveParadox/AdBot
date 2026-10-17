# Autonomous agent implementation map

Audit date: 2026-10-17. Starting GitHub revision: `9dd3a00`.

| Existing component | Verified starting behavior | Agent integration |
| --- | --- | --- |
| FastAPI / bearer workspace keys | Target/job/workflow/schedule CRUD and ownership | Add task, decision-review, memory, provider-status and metrics endpoints |
| Playwright Runner | Isolated contexts, guarded navigation, screenshots, crawl and scripted actions | Reuse lifecycle/network boundary; add semantic observation and agent execution hook |
| SQL queue / worker | Durable frontier, capacity/domain leases, fencing, cancellation | Run agent jobs on the same worker; retain pause/cancel and heartbeat semantics |
| Scheduler | Durable timezone-aware crawl/workflow scheduling | Keep stable public interfaces |
| SSE / artifact API | Persisted events, replay and authenticated PNGs | Reuse for observations, decisions, review requests and live browser preview |
| SQLAlchemy / Alembic | Eight tables; SQLite and PostgreSQL support | Add agent task, step and reusable memory tables through a new migration |
| React dashboard | Targets, scripted runs, history, schedules, real analytics | Add goal entry, agent history, semantic actions, memory, provider status and review controls |
| Tests | 29 backend tests, parser tests, real-browser crawl/UI fixture journey | Extend with agent model contracts, recovery, memory isolation and real goal-driven browser fixtures |

No AI provider, planner, semantic page interpreter, tab manager, task memory or
goal verification existed in the starting revision. No obsolete AI subsystem
needs replacing. Existing crawling/workflow APIs remain intact.

The new path separates page observation, validated model decisions, controlled
browser actions, task memory, and goal verification. The SQL job remains the
execution authority. Provider settings use the existing ADBOT configuration
namespace. Page content is untrusted evidence, not instruction authority.

Implementation modules and final verification are documented in
`AGENT_GUIDE.md` and `AGENT_VERIFICATION.md`.
