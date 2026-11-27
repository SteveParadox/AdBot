# Evidence-driven execution

## Informational research and recovery

Routing and the plan specification share objective recognition. A straightforward
question gets a short research path. A brief ambiguous subject can receive one
structured lookup assessment. A topic classification never changes permissions.
Read-only search is derived from the saved autonomous task option and explicit
constraints. It uses the Playwright observation and live binding for the specific
control. The execution boundary checks target semantics, allowed URLs, the query
and the exact attested POST endpoint when applicable.

The worker captures ranked passages by heading and retains literal quotes and
stable IDs. Exact compound requests separated by ellipses or paragraph breaks
can yield several evidence IDs, with each passage checked against authorized
observations. Synthesis cites the stored IDs. Verification tests objective
coverage and paraphrased claims, and can split a context-limited request by
criterion while keeping all citations for each claim. Previously verified
excerpts can be published as partial results if the whole answer cannot be
verified.

An action denial can trigger alternative navigation without changing the
original objective. Dependency evaluation uses topological order. A legacy
research or collection checkpoint blocked by a form-input denial can reconcile
when verification and evidence satisfy the read-side task. Hard failures and
mandatory authorization retain their gates. Failed completion signatures limit
retries based on the evidence and normalized claims.

Research uses an adaptive finalization reserve inside the configured token and
time budgets. Lightweight decisions can use lower automatic reasoning effort.
The provider adapter preserves structured validation and emits fixed diagnostic
categories for identifiable HTTP request rejections. It does not retain provider
error bodies in task logs. The live dashboard reads URL, screenshot, semantic
controls and active tab from a common step observation. The 100-row live cache
uses newest-first ordering and paginated history keeps its own cursor.

The implementation follows checkpoint dependency recovery, live locator
validation and bounded observation patterns. [LangGraph persistence](https://docs.langchain.com/oss/python/langgraph/persistence),
[Playwright locators](https://playwright.dev/docs/locators), [Browser Use](https://github.com/browser-use/browser-use/blob/main/AGENTS.md)
and [Stagehand](https://github.com/browserbase/stagehand).

### Loopback research benchmark

The same local Chromium fixtures and OpenAI-compatible model double ran against
the baseline merge `2f3a8af` and the orchestration branch. Timing covers worker
execution. Fixture token usage estimates serialized characters divided by four.
Live-provider tokenization, reasoning and latency will vary.

| Interface | Baseline calls / tokens / seconds | Updated calls / tokens / seconds | Baseline to updated result |
| --- | --- | --- | --- |
| Native GET search | 7 / 22,780 / 13.91 | 2 / 1,334 / 6.02 | 3 failed completions to verified, zero failed completions |
| Scripted AJAX search | 7 / 22,196 / 10.78 | 2 / 1,321 / 3.73 | 3 failed completions to verified, zero failed completions |
| Search with no results and an observed fallback link | 7 / 22,796 / 8.20 | 5 / 10,513 / 11.64 | 3 failed completions to verified, zero failed completions |

The fallback fixture took longer after the change because the updated worker
actually submitted the authorized search and waited for its outcome before
following the observed link. All updated runs stayed below 90 seconds and 25,000
estimated tokens. Direct search needed only synthesis and verification calls.
The historical live-provider HTTP 400 cannot be attributed to a particular
request field from status alone.

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
| `ADBOT_AGENT_COLLECTION_MAX_ROWS` | 5,000 | Unique rows in a task |
| `ADBOT_AGENT_COLLECTION_MAX_BYTES` | 8,000,000 | Serialized record bytes in a task |
| `ADBOT_AGENT_CLASSIFICATION_BATCH_ROWS` | 24 | Rows per semantic classification call |
| `ADBOT_AGENT_CLASSIFICATION_MAX_CALLS` | 32 | Semantic classification batches per task |

Storage, step, time, and model token budgets preserve collected evidence when reached. Increase collection limits in line with the worker's memory and task deadline. The limits are deployment settings shared by the API and workers.

Model context includes the original objective, current phase, compact live observation, and a small evidence selection ranked by task and phase terms, source, and recency. Durable checkpoints retain the full bounded evidence used to verify the final answer. During directory collection, a short-lived per-document cache reuses the scan while URL, viewport, and DOM revision match. Actions use freshly bound controls. General browser observations still capture live page state.

The provider chain reserves output tokens separately from input estimates and settles against provider usage when available. `ADBOT_AI_CONTEXT_WINDOWS` accepts a JSON map keyed by provider or model ID for deployment-specific windows. Estimated over-window requests are skipped before dispatch.

No migration is needed. Route and collection state use the existing checkpoint and result JSON. Restart the API and workers to pick up deployment settings. Exhaustive collection still depends on evidence exposed by the site. Unmarked dynamic listings, virtual grids, and products that require detail-page inspection can return partial results or continue through the general planner.
