# Research intelligence and context audit

The audit starts from commit `30684e1` on PR #19. The recorded comparison failed at 42,804 tokens, nine calls, approximately 195 seconds and zero evidence. PR #19 already restored verified completion on the same authorized site using 7,040 tokens, two calls and 24.38 seconds. Its fixtures cover durable capture, rejected navigation loops, partial publication and provider context rejection. [Previous verification report](RESEARCH-VERIFICATION.md)

## Findings at the audit baseline

| Issue | Initial assessment | Confirmed behavior and correction |
| --- | --- | --- |
| A. Context | Partially resolved | Provider request estimation, reserved output and rejection recovery existed. `bounded_request_text` still sliced evidence and selected controls by position. Controls now rank by observed actionability, focus and objective overlap. Research quotes remain intact or are dropped as a whole. Recovery drops supplementary history and retains exact task criteria and schemas. Irreducible requests identify the largest serialized components by byte count. Retry admission recalculates the complete provider request. [Model transport](../../backend/app/agent/model.py#L111) |
| B. Evidence | Partially resolved | The existing observer automatically captured and checkpointed rendered evidence. Its first-220-snippet cutoff starved later content, and it only inspected the first 700 characters of each block. A bounded scan now retains high-relevance candidates throughout the document, considers overlapping windows in long blocks and includes short structured rows. [Rendered extraction](../../backend/app/agent/research.py#L9) |
| C. Checkpoints | Partially resolved | Research already required evidence, but one comparison excerpt advanced both phases. Research now waits for evidence on all identifiable subjects, and collection checks each explicit comparison dimension against each subject. Checkpoints record matching evidence IDs. Independent verification can resolve lexical misses using cited source evidence. [Evaluation](../../backend/app/agent/planning.py#L317) |
| D. Recovery | Partially resolved | Typed provider failures, quota handoff, stale-target checks, lease handling and uncertain-submission protection already existed. Native retries could change the request after estimation, and irreducible diagnostics exposed little about the cause. The changes keep the typed error and re-estimate before retries. [Provider transport](../../backend/app/agent/model.py) |
| E. Progress | Resolved for the reference failure | Research already tracks evidence gain independently of UI fingerprints and rejects exhausted destinations. The local missing-source fixture exercises that guard and qualified partial publication. Interaction and pagination retain the browser's established paths. [Research workflow tests](../../backend/tests/test_research_pipeline.py) |
| F. Retrieval and synthesis | Partially resolved | Authorized rendered DOM, observed links, aggregation and partial verification had been implemented. The same route now captures additional structured rows and explicitly instructs independent verification to account for contradictory sources. Source quality and contradiction judgments remain model-assisted. |
| G. Efficiency | Partially resolved | PR #19 removed redundant inspections and crawling work from research navigation. This audit reduces unnecessary browser-to-worker candidate transfer, avoids repeated schema serialization within a compaction pass and gives compacted controls a relevance order. |

## Open-source research

| Project | Relevant pattern and decision |
| --- | --- |
| Browser Use | Compacted history and bounded browser context support keeping controls separate from source text. AdBot reuses its existing Playwright observer and identity checks. [Migration guide](https://github.com/browser-use/browser-use/blob/main/MIGRATING.md) |
| Playwright | Rendered observations and actionability are already available through the installed browser runtime. The reader runs inside the authorized page and keeps navigation in the same controller. [Page API](https://github.com/microsoft/playwright/blob/main/docs/src/api/class-page.md) |
| Crawl4AI | Link-density pruning and query-ranked blocks motivate scoring before transferring candidates. The Apache-2.0 crawler was used as a reference for the filtering pattern. [Content filters](https://github.com/unclecode/crawl4ai/blob/main/crawl4ai/content_filter_strategy.py) |
| Firecrawl | Separating rendered content retrieval from browser interaction makes sense architecturally. Its AGPL-3.0 server and hosted service would introduce an additional execution or egress boundary. [Repository and license](https://github.com/firecrawl/firecrawl) |
| LangGraph | Durable checkpoints and error-specific retry boundaries map to AdBot's existing SQL checkpoints and controller. The protected action and lease model stays in the current runner. [Persistence](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx) · [Error handling](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/thinking-in-langgraph.mdx) |
| Haystack and LlamaIndex | Retrieval and synthesis can be independent phases. A lexical ranker fits the bounded evidence collection without embeddings, new services or an index lifecycle. [Haystack BM25 retriever](https://github.com/deepset-ai/haystack/blob/main/haystack/components/retrievers/in_memory/bm25_retriever.py) · [LlamaIndex](https://github.com/run-llama/llama_index) |
| AutoGen | Separate agent roles were evaluated. Additional agents would duplicate context and quotas, and the repository describes the framework as in maintenance mode. [AutoGen](https://github.com/microsoft/autogen) |
| LiteLLM | Provider normalization and separate usage accounting inform request admission. AdBot keeps its existing provider adapter, cooldowns, quotas and egress policy. [LiteLLM utilities](https://github.com/BerriAI/litellm/blob/main/litellm/utils.py) |

This change adds no dependencies and incorporates no upstream code. It reuses the existing browser session, SQL lease and checkpoint, source URL and step provenance, and model provider accounting.

## Measurements

| Comparison replay | Time | Input | Output | Calls | Evidence | Outcome |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| Recorded failure | ~195 s | 40,685 | 2,119 | 9 | 0 | Failed after 10 steps, two blocked repetitions and two context overflows |
| PR #19 | 24.38 s | 6,379 | 661 | 2 | 3 | Verified |
| Audit replay | 23.48 s | 6,689 | 613 | 2 | 3 | Verified |

Audit replay `1fda2af7-f244-48e6-9314-151a5bf2f50f` used two browser actions and one verification step. Two excerpts supported the objective and both subject checks. No navigation cycle or overflow occurred in that replay. The replay includes the new context and checkpoint behavior and predates the final short-row and diagnostic-output adjustments. These are single live runs, with a 262-token increase from PR #19 and a 35,502-token reduction from the original failure.

The simulated provider rejection reconstructed the request from an estimated 13,150 to 5,583 input tokens and held 800 tokens for output. Provider request estimates differ from recorded provider usage.

## Regression verification

The targeted Windows suite passed 138 tests covering research, model contracts, provider failover and context windows, planning, failure diagnostics, authorization and directory pagination. Browser fixtures exercised durable evidence before model decisions, a relevant passage following 300 unrelated paragraphs, a script-rendered table, a rejected navigation cycle, missing subjects and a comparison which the simulated verifier leaves incomplete when its sources disagree. After the final attribution change, 12 focused checks passed, including a fixture that retains an irrelevant candidate in the evidence store and excludes it from completed checkpoints and published citations. The simulated verifier covers result handling, while the authorized live replay covers the configured inference providers.

## Limits

Research still runs within the authorized browser session. A separate HTTP crawler and concurrent independent browsing would require a source-isolation design that shares the current DNS, redirect, rate and permission checks. This audit leaves those integrations out. The DOM scan is bounded and can miss content beyond its scanning limits or content that requires interaction to render. Lexical coverage is a navigation and checkpoint signal. Semantic verification still evaluates cited facts, source relevance and conflicting evidence. Preflight token counts remain estimates for providers with no local tokenizer, and reported usage settles the reservation where available.
