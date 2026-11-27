# Category enumeration audit

The failed task `1e733133-4766-4733-9e29-7d4d812c74d1` consumed 52,890 tokens, 16 model calls and approximately 154 seconds. Its 21 excerpts yielded no requested list. The recorded trace reached an article about creating comparison pages and then repeatedly scrolled within that article. The original authorization remained in effect, including disabled form input.

## Assessment

| Area | Baseline | Correction or retained behavior |
| --- | --- | --- |
| Intent and decomposition | Regressed for category subjects containing comparison language | The router and planner share leading operation recognition. Explicit enumeration takes precedence over words inside the subject, and an ambiguous category fragment does not become a comparison. |
| Enumeration | Partially resolved | Existing exhaustive directories and structured capture remain available. Non-exhaustive category requests demand captured records and scoped qualification before completion. A model cannot add an exhaustive requirement to that request. |
| Record extraction | Partially resolved | Browser semantics already surfaced groups but lacked a proper single-record detail path. Cards, links, rows and detail pages can supply candidates. Non-exhaustive mapping retains independently valid rows when unrelated fields are clipped. |
| Evidence and source relevance | Partially resolved | The research pipeline could cite contextual text that did not support a list. Listing verification uses per-record observed descriptions, and rejects a name-only verdict. Its prompt distinguishes an entity's own purpose from content it creates or describes. An unsuccessful group can be abandoned in favor of another authorized source. |
| Checkpoints and verification | Partially resolved | Generic observation and text checkpoints did not prove the list. Enumeration waits for qualified structured records and sends the captured result to verification. Explicit source rejection reopens discovery. Qualified partial results can preserve checked records. |
| Progress and recovery | Partially resolved | The previous duplicate-action detector eventually stopped the loop. Enumeration suppresses already explored destinations without new evidence and stops unchanged scrolling while allowing scrolls that reveal new groups. |
| Provider resilience | Partially resolved | Provider-specific schemas, cooldowns, shared quotas and context rejection handling already existed. A three-second connection cap bounds slow connections independently of the inference read timeout. Transport fixtures verify that fallback retains the request and read budget. |
| Comparison performance | Preserved in live replay | The previously authorized Notion AI and Obsidian comparison completed with verified evidence in 32.06 seconds, 7,429 tokens and two model calls. |

## Upstream references

- Haystack's conditional router illustrates a typed strategy boundary. AdBot shares the operation decision between its own router and planner. [Conditional router](https://github.com/deepset-ai/haystack/blob/main/haystack/components/routers/conditional_router.py)
- Crawl4AI separates structural mapping from semantic extraction. AdBot reuses its visible DOM groups, applies mappings locally and calls the configured model for ambiguous category membership. [Extraction strategies](https://github.com/unclecode/crawl4ai/blob/main/docs/md_v2/api/strategies.md)
- Playwright already provides actionability and identity-bound interactions. The existing controller continues to own navigation, permissions and browser mutations. [Actionability](https://github.com/microsoft/playwright/blob/main/docs/src/actionability.md)
- LangGraph illustrates checkpointed recovery and the distinction between observations and durable progress. The current SQL checkpoints and worker result publication remain the integration points. [Persistence](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/persistence.mdx)
- LiteLLM separates cooldowns, retry policies and timeout configuration. AdBot keeps its current provider adapters and isolates connection timeout from model read timeout. [Router settings](https://github.com/BerriAI/litellm-docs/blob/main/docs/proxy/config_settings.md)

No third-party code or dependencies were added. Source checks, read permissions and the existing form and download gates apply to the listing route.

## Verification

The browser fixtures exercise an unrelated storefront-category listing, a misleading editorial source, a false positive with a name-only citation, cards and single detail pages. The record must qualify before the final listing publishes it. Separate fixtures cover ranking, recommendation and general research, and the existing comparison, directory, provider failover and security suites cover the shared pipeline.

An intermediate live replay reached the tools catalog and failed in 35.70 seconds with 20,542 tokens and four model calls. That trace identified the over-strict row-mapping check. The comparison replay from the same build completed in 32.06 seconds with 7,429 tokens, two calls and three observed excerpts.

The final replay `b924a202-4d27-44b6-a5ab-a46a31fa24b4` started at the original homepage with the original objective and permissions. It opened an observed utility link, captured the visible title and description, then classified and verified the record. The task completed in **14.33 seconds, 3,028 tokens and two model calls**, publishing one qualified comparison utility. The source documents side-by-side software tradeoffs for purchase decisions. It does not establish built-in purchase transactions or an exhaustive catalog. [Live source](https://xavkit.com/compare-tools)

The targeted suites passed 155 tests during the audit. Later runs passed 24 structured-discovery and category checks, 55 category and provider failover checks, and 16 final category tests, with overlap between the runs. The card and individual-page listing fixtures took 3.08 and 3.16 seconds in a measured run with simulated providers. Ranking, recommendation and research checks use fixtures. The two published live performance figures describe individual replays, with variation from website and provider latency.

The original listing does not explicitly request exhaustive coverage. Records found on one verified source can support a scoped listing. Large catalogs, unavailable sources and insufficient descriptions can still prevent completion, and the task cannot infer membership from a link name alone.
