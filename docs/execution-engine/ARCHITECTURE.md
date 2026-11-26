# Evidence-driven execution

## Discovery on unfamiliar websites

The general planner can inspect and capture a previously unknown record shape in an authorized browser. The observer identifies native tables, ARIA grids and repeated visible sibling structures using browser semantics. It provides short examples, nearby headings, observed field labels and counts. The planner selects a region for the objective, assigns fields to the observed segments and chooses a record identity. It uses the existing browser actions for navigation, pagination and scrolling. Native selections and forms retain their existing permission gates.

The runner applies the field mapping to the observed rows, remaps labeled fields when their order varies, rejects missing or conflicting identities and retains the source URL and step. A mixed group can be classified in bounded batches using the original objective and captured field values. Exhaustive verification requires an exact count quote from the relevant source, matching unique coverage and a separate verification response that cites captured evidence. The verifier receives the captured values and the original success criteria. Missing proof, ambiguous mappings and resource limits produce an unverified result with any captured rows preserved. One-off text, unsupported layouts and configured datasets can use their established workflows.

## Deterministic inventories and execution budgets

The runner selects a route from the task, output requirements, and dataset configuration. It recognizes scoped exhaustive inventory and table requests, including "Give me a comprehensive list of conversational AI platforms." When a provider is available, a bounded model request can identify the literal entity in an unfamiliar exhaustive request. The runner validates the phrase and scope before choosing the directory route. Research, comparison, document retrieval, forms, navigation, and multi-step workflows receive route-specific guidance in the existing planner. The configured dataset route retains its extraction and export phases.

The directory observer reads visible cards, accessible repeated listings, and native tables. It can scan the document body when a main landmark is absent. Explicit totals support paginated collection. A single fully observed static table can establish its row count directly. Listings with no verifiable total preserve the rows they collected and return partial results. The runner checkpoints each batch and follows controls present in the current document. When a page repeats, it considers an unused numbered page, a bounded wait and revalidated click for a same-URL pager, or bounded scrolling where more content is visible. The browser's existing URL policy and authorization gates apply to every transition.

Clear category or description evidence can classify records without a model. Product inventories skip recognized ranking and article listings. Ambiguous product listings are assessed in bounded batches. Each answer uses a request-local record ID and the number of a source excerpt. The runner resolves that number to the exact observed text. Invalid references fail over through the provider chain. Chatbot matches require evidence that supports the product's conversational role. A bounded second pass can use additional source text for unresolved entries. A verified inventory needs consistent coverage equal to the observed count, classified records, and no detectable filter, truncation, or remaining forward page. Results cite the observed record text and retain source URLs.

For typed inventory requests, the entity noun determines the expected catalog and any qualifier determines the classification topic. The runner compares that type with the visited page's visible count and heading before collecting records. When those do not support the requested type, the runner selects a matching authorized link from the current observation. If deterministic discovery cannot establish the source, the planner can continue discovery while the verification gate remains closed. The result records separate checks for source relevance, coverage, extraction, entity classification, and overall satisfaction.

Topic classification prefilters from observed tags and specific purpose text. Exact duplicates reuse a classification when their name, category, description, quote, and topics match. Other records use compact numbered excerpts. `ADBOT_AGENT_CLASSIFICATION_CONCURRENCY` limits parallel batches per agent to two by default. Batch provider failover is independent, and budget accounting for the task is serialized.

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
