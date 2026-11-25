# Evidence-driven execution

The runner selects a route from the task, output requirements, and dataset configuration. It recognizes scoped exhaustive inventory and table requests, including "Give me a comprehensive list of conversational AI platforms." When a provider is available, a bounded model request can identify the literal entity in an unfamiliar exhaustive request. The runner validates the phrase and scope before choosing the directory route. Research, comparison, document retrieval, forms, navigation, and multi-step workflows receive route-specific guidance in the existing planner. The configured dataset route retains its extraction and export phases.

The directory observer reads visible cards, accessible repeated listings, and native tables. It can scan the document body when a main landmark is absent. Explicit totals support paginated collection. A single fully observed static table can establish its row count directly. Listings with no verifiable total preserve the rows they collected and return partial results. The runner checkpoints each batch and follows controls present in the current document. When a page repeats, it considers an unused numbered page, a bounded wait and revalidated click for a same-URL pager, or bounded scrolling where more content is visible. The browser's existing URL policy and authorization gates apply to every transition.

Clear category or description evidence can classify records without a model. Ambiguous listings are assessed together in bounded batches. A returned match or exclusion must use the requested record ID and a contiguous quote from the observed listing. Exact quotes establish provenance. Semantic classification remains a model judgment. Missing, conflicting, or unsupported determinations remain unresolved. A verified inventory needs consistent coverage equal to the observed count, classified records, and no detectable filter, truncation, or remaining forward page. Results cite the observed record text and retain source URLs.

| Configuration | Default | Scope |
| --- | ---: | --- |
| `ADBOT_AGENT_COLLECTION_BATCH_ROWS` | 250 | Rows read per observation |
| `ADBOT_AGENT_COLLECTION_MAX_ROWS` | 2,000 | Unique rows in a task |
| `ADBOT_AGENT_COLLECTION_MAX_BYTES` | 4,000,000 | Serialized record bytes in a task |
| `ADBOT_AGENT_CLASSIFICATION_BATCH_ROWS` | 12 | Rows per semantic classification call |
| `ADBOT_AGENT_CLASSIFICATION_MAX_CALLS` | 12 | Semantic classification batches per task |

Storage, step, time, and model token budgets preserve collected evidence when reached. Increase collection limits in line with the worker's memory and task deadline. The limits are deployment settings shared by the API and workers.

Model context includes the original objective, current phase, compact live observation, and a small evidence selection ranked by task and phase terms, source, and recency. Durable checkpoints retain the full bounded evidence used to verify the final answer. During directory collection, a short-lived per-document cache reuses the scan while URL, viewport, and DOM revision match. Actions use freshly bound controls. General browser observations still capture live page state.

The provider chain reserves output tokens separately from input estimates and settles against provider usage when available. `ADBOT_AI_CONTEXT_WINDOWS` accepts a JSON map keyed by provider or model ID for deployment-specific windows. Estimated over-window requests are skipped before dispatch.

No migration is needed. Route and collection state use the existing checkpoint and result JSON. Restart the API and workers to pick up deployment settings. Exhaustive collection still depends on evidence exposed by the site. Unmarked dynamic listings, virtual grids, and products that require detail-page inspection can return partial results or continue through the general planner.
