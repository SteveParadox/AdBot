# Collaborative research agents scaffold

Status: read-only research role contracts and DAG validation. No supervisor inference, worker dispatch, browser access, or messaging runtime.

## Boundaries
- Start with authorized research, document analysis and report composition. The original user objective and authorized source scope remain immutable.
- Existing SQL queue and worker leases remain the execution authority; Redis is a notification mechanism, not authoritative state.
- A future supervisor may propose a bounded DAG, but must not broaden permissions, spawn recursively, or grant tools. Child tasks inherit the parent's authorized sources and budgets. No new browser capabilities.
- Keep browsers isolated and use existing destination checks, per-domain limits, concurrency, cancellation and verification. Shared evidence must retain original provenance and workspace ownership.
- Reconcile dependency failure, partial results, lease expiry, cancellation and restart before enabling execution. A verifier checks source evidence independently of worker summaries.
- Use single-agent execution for simple tasks; no runtime routing changes in this scaffold.

## Next implementation
Design durable plan/item records, scope-checked evidence workspace, atomic dependency transitions and parent resource accounting. Add integration fixtures for fan-in, restart, duplicate delivery, isolation and cancellation. Gate the feature behind explicit opt-in.
