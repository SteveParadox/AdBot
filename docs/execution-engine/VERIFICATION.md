# Verification and benchmark

## Semantic source selection and independent catalog comparison

The original prompt task completed after reading the wrong catalog, 119 tools, and returning four software products. With typed source verification, the first corrected run collected all 142 prompts and stayed partial with 58 unresolved classifications. It used 29,685 tokens. Grounded topic prefiltering reduced the final prompt run to 2,470 tokens and two model calls with no unresolved prompts.

| Objective | Verified catalog coverage | Independently checked matches | Elapsed | Tokens |
| --- | ---: | ---: | ---: | ---: |
| List all business prompts | 142 prompts in 10 batches | 65 | 13.49 s | 2,470 |
| List all AI chatbots | 119 tools in 8 batches | 5 | 25.75 s | 17,345 |

Both live runs started at the XavKit homepage and used the normal task API, worker, local Chromium, configured providers, and a 60,000-token cap. A separate browser pass enumerated the two public catalogs. Manual review used the visible tags and stated purpose of each listing. Business matches had a direct organizational use such as marketing, sales, operations, hiring, or customer support. Generic and primarily personal tasks fell outside that rubric. Chatbot matches included standalone conversational assistants and answer engines. Catalog URLs, matched URLs, titles, and cited evidence all agreed with the independent review. Record counts reflect the live catalogs observed on November 25, 2026.

Authenticated local dashboard retries of the original tasks returned the same independently verified sets. The business-prompt job returned 65 of 142 in 16.08 seconds with 1,325 tokens and one model call. The chatbot job returned five of 119 in 36.80 seconds with 21,233 tokens across 14 model calls, including provider failover. Both served verified results with all five checks and zero unresolved records. Browser checks also confirmed the typed source, the final verification decision, the completed saved plan, and the warning on the historical result.

## Live acceptance from the original XavKit start page

The merged PR #16 baseline ran the original objective, "list all ai chatbots", from the public [XavKit rankings page](https://xavkit.com/best). It treated 26 ranking entries as products, used 6,523 tokens, and failed verification. The follow-up skips recognized ranking inventories and follows the observed Tools link. Numbered excerpts keep classification responses compact and allow the provider chain to reject invalid record or evidence references. The acceptance check for chatbot matches also rejects citations that describe features in streaming or editing products.

The final isolated run used the normal API, worker, local Chromium, configured cloud providers, and the default 60,000-token budget. It followed the product directory through all eight batches, recovered from one repeated batch, and finished with status `completed` and verification `complete: true` in 37.14 seconds. It classified all 119 advertised records, returned five sources for Kimi, Perplexity, ChatGPT, Claude and Gemini, and left 44,053 tokens available. The reported token usage was 12,553 input and 3,394 output tokens across 10 model calls. The matches represent products presented as assistants or answer engines in the visible directory. The source audit excluded streaming or editing products whose listing mentioned chat as a feature.

## Follow-up verification on November 25, 2026

The normal Chromium fixture accepted the paraphrase "Give me a comprehensive list of conversational AI platforms." It collected 119 unique records, produced 23 cited matches, and completed in 10.14 seconds with zero model calls or tokens. The stalled Next fixture revisited the first batch, recovered through an observed numbered page, and met the same coverage and evidence checks in 6.38 seconds. The unrecoverable cycle fixture retained 105 unique records and 21 cited matches as a partial result.

The read-only [XavKit smoke](https://xavkit.com/tools) used a temporary local database and disabled model providers. It traversed all eight visible batches and preserved 119 unique records against the advertised total of 119 in 23.77 seconds. All classifications remained unresolved in that run. The live result therefore verified traversal coverage and remained partial. Test doubles verified a model-inferred entity route, source-quoted semantic classification, and failover when the primary classification response violated the schema. Live semantic accuracy and cloud throughput remain unmeasured.

The focused browser suite passed 17 cases, including all directory regressions, observation cache reuse and invalidation, two-source comparison, source-document download, multi-step form execution, and verified dataset export. The agent robustness and directory suite passed 40 cases in a separate, overlapping run. The frontend passed all 59 tests and built successfully.

## Measured regression of November 25, 2026

The local Chromium test uses the normal task API, worker, browser controller and SQLite checkpoints against a deterministic fixture. The fixture contains 119 unique tools across eight batches, repeated entries, two card layouts, controls for search, tags and price, and a JavaScript pager. It includes 23 known chatbot products. The test fails if any provider call is attempted and uses a 2,000-token task budget.

| Metric | Reported original XavKit run | Local fixture, final implementation |
| --- | ---: | ---: |
| Worker execution duration | 203 s | 10.22 s |
| Model calls | 18 | 0 |
| Input plus output tokens | 40,049 | 0 |
| Largest diagnostic observation | 101,156 characters | 13,295 characters |
| Unique records collected | No verified inventory reported | 119 |
| Matched chatbot records | Unverified | 23 |
| Linked evidence entries | 0 | 23 |
| Classification | Unverified | 23/23 matches and 96/96 exclusions |
| Browser traversal | Failed | Completed across 8 batches |

These columns compare a user-reported live failure with a controlled local run, so the durations do not establish a production speedup. Earlier local implementation runs measured 94.16 s before candidate binding was narrowed, 23.89 s afterward, and 12.22 s with the first overlay-card variant. Host load varied across those runs. The final fixture recorded 1,860 ms in inspection, 345 ms in decision, 125 ms in loading, 343 ms in resolution, 798 ms in action and 155 ms in waiting. Worker startup, checkpointing and publication are included in the wall time.

The repeated-page fixture stopped in 2.72 s, retaining 3 matches and their citations from 15 unique records. The three-step fixture stopped in 3.61 s, retaining 6 matches and citations from 30 unique records. Neither claimed complete coverage. Both ran with zero tokens and zero provider calls. Separate unit checks cover discrepant totals, unclassified rows, filtered scope, unavailable Next, cross-domain records, semantic action identity and preflight fallback for a small provider context window.

## Public read-only smoke test

On the public [XavKit tools directory](https://xavkit.com/tools), the first integration run exposed heading-free cards represented by repeated containers and accessible overlay links. The extractor now supports that general structure. An isolated repeat reached HTTP 200 and collected 30 unique records across two visible batches in 4.94 s with zero model calls. The step limit then stopped the smoke test. A longer attempt stopped on a repeated batch after 15 unique records in 4.31 s. No chatbot match was verified in either live sample. Live exhaustive classification is still unverified. No production job or credentials were used for these runs.

## Regression checks

- Backend non-browser suite: 351 passed, 1 skipped. The new context preflight case was added afterward and passed with the three final directory browser cases.
- Frontend: 59 unit tests passed and the production build succeeded.
- Ruff and `git diff --check` passed.
- Review tightened forward-control coverage against raw visible controls, excluded unsafe record URLs, kept the review path for assisted navigation, and prevented automatic pagination from granting write permission. The fixture confirms contract-equivalent read paths and leaves additional site layouts to the general strategy or partial results.

To reproduce the fixture from `backend`, run `python -m pytest -s tests/test_directory_workflow.py` with Chromium installed. The tests print a `DIRECTORY_RECEIPT` containing measured timing, counts, and phase totals.

Additional browser verification was split across runs. The initial run passed
17 cases, including Chromium and Firefox accessibility. The remaining 13
Chromium planning, export, recovery, lease, provider and response-contract cases
passed separately. Both Firefox and WebKit policy-proxy workflows passed. The
long WebKit accessibility case did not finish during two local attempts. The
isolated attempt's stack was inside Playwright locator inspection, so that
case remains unverified. The three new directory regressions passed separately.

The [hosted GitHub Actions run](https://github.com/SteveParadox/AdBot/actions/runs/45610064804)
marked both jobs failed and exposed no job steps or downloadable logs. The
available run metadata does not establish a cause.
