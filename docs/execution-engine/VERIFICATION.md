# Verification and benchmark

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
