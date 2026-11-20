# Worker responsiveness, shared model quotas, diagnostics and dataset queries

## Database work

Worker initialization, heartbeats, pause/cancel control polling, finalization, model accounting, agent review polling, checkpoints, dataset-scope validation and export preparation submit complete operations through the bounded IOExecutor. Sessions open and close inside those operations. Browser/page operations remain on the event loop. The worker shares its configured executor across jobs. Cancellation does not release a running operation's admission slot early; shutdown drains outstanding operations.

Executor heartbeat snapshots include operations, queue_ms and work_ms. Operations taking at least 100 ms log their callback name and duration without SQL parameters or credentials. The regression suite injects a 150 ms heartbeat delay and verifies that the event loop keeps making progress. This is a responsiveness check, not a production throughput benchmark. Other existing browser/agent per-step transactions remain synchronous and should be profiled before further offloading.

## Shared provider quotas

Run the new Alembic migration before starting updated services: from backend, use the virtualenv Python to run `-m alembic upgrade head`. Revision c42f00000001 follows the existing extraction revision b31e00000001. This change does not migrate the real database automatically.

ADBOT_AI_PROVIDER_RPM and ADBOT_AI_PROVIDER_TPM default to zero (each cap disabled). Every worker sharing the database coordinates admission using a locked provider_quotas row. The provider endpoint and credential determine a SHA-256 key; raw credentials are not stored. Different endpoint/credential pairs, including a local fallback, have separate counters. Limits apply to each pair and must be configured consistently across workers. Accounts whose provider quota spans several API keys/endpoints require a common upstream allocation or lower individual limits.

Windows are fixed UTC epoch minutes, not sliding provider windows. Request reservations count all attempted requests. Token reservations conservatively use serialized request UTF-8 bytes plus maximum output tokens, then reconcile reported actual usage in the same window. Unknown/failed transport retains its reservation. HTTP 429 publishes a shared Retry-After cooldown, including when numeric caps are disabled; a single published delay is capped at 24 hours. Admission denial fails promptly or uses an already configured fallback; it never sends the denied request. This protects configured application budgets; it does not certify arbitrary provider-specific token accounting or replace provider limits.

## Job diagnostics

Job and agent API responses include failure: category, stage, last_successful_action, retry_eligible, automatic_retry_scheduled and suggested_recovery. The jobs and agent dashboard display the same summary. Categories distinguish provider throttling, provider errors, navigation, extraction, export, configuration, browser failure, timeout and uncertain submission. Partial extraction can have a diagnostic while its enclosing browser job completed. Retry advice does not enqueue work. Uncertain submissions require inspecting the destination and are never presented as safe to retry. Diagnostics use bounded action identifiers and generic recovery text; existing owner checks still apply.

## Deterministic dataset selection

Exports accept an optional query object. The agent task API accepts the same shape as dataset_query; the dashboard provides JSON editors and shows the resolved selection in task previews.

```json
{"filters":[{"field":"price","op":"lt","value":"100"}],"sort":[{"field":"price","direction":"asc"}],"limit":10}
```

All filters are ANDed. Supported operators: eq, ne, lt, lte, gt, gte, contains, in, is_null. Scalar schema fields only; nested/list/object queries are rejected. Strings compare exactly and case sensitively. Numbers compare with Decimal, dates and timezone-aware datetimes use normalized values, nulls sort last in either direction, and record ID breaks ties. Currency values must already use comparable units; no currency conversion occurs.

A simple command such as "Export the cheapest ten products as CSV" (also items/records, one through ten or numeric counts through 9999) compiles deterministically to a numeric price sort, excluding missing prices. Negative, conditional, multi-clause and otherwise unsupported phrasing needs explicit query configuration; it is not silently compiled. The preview discloses the resolved query. Natural-language constraints still require final verification; the compiler does not interpret arbitrary filters or guarantee that captured records cover an entire website.

Selection is bounded to 10,000 active records and rejects larger datasets rather than silently sampling. Empty standalone query results produce a valid empty export. Agent completion continues to require a nonempty verified artifact. Queries operate inside existing dataset ownership, source-record hash scopes, version checks, export-size limits, cancellation and artifact expiry. Exports retain selected record IDs and hashes; semantic verification uses the selected export scope and order. JSON artifacts record the applied query. Existing exports without a query retain their previous behavior.


## Executed validation

- Broad backend non-browser suite: 224 passed, 1 skipped (opt-in Redis), 55 browser tests deselected. A warm-up unit test previously depended on real host pressure; it now disables that external input in its simulated environment.
- Final focused backend regression batch after quota-accounting changes: 82 passed, 17 browser tests deselected.
- Latest dedicated reliability tests, including the final workflow checkpoint diagnostic: 14 passed. These overlap the other runs and must not be summed as unique tests.
- Frontend: 20 tests passed; TypeScript and Vite production build passed.
- Dashboard: semantic controls and preview scenarios passed in the combined run. Research and filtered CSV/JSON export scenarios initially exceeded timing limits while the broad backend suite was running; both passed when rerun alone (46.1s and 22.4s). This is not a claim that the combined run passed.
- Python lint, diff whitespace checks and source null-byte integrity scan passed. Recently interrupted source writes were recovered from local editing history before these final checks.
- Example executor samples from the loaded local dashboard run: heartbeat 614.1 ms, model account 159.7 ms, checkpoint 119.7 ms. These identify work kept off the event loop; they are not a before/after production throughput measurement.

All runtime tests used temporary databases and local fixture services. The real database was not migrated, and production services were not restarted. Apply the migration and configure appropriate provider caps before using the updated services.
