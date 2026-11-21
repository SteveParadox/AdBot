# Extraction verification and acceptance

Commands run from backend unless a different directory is specified. Counts
overlap; they are not added together as distinct test cases. No production
deployment or production database migration was performed.

## Executed checks

| Command / configuration | Result |
|---|---|
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py -m "not browser"` (initial five cases) | 5 passed, 2 deselected, 51.55s |
| Same command after added evidence/removal/export checks | Initially 7 passed, 1 failed: test counted earlier tests' CSV files; isolated its artifact directory. Subsequent nine-case run: 9 passed, 2 deselected, 93.50s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py -m browser` | Initial mixed JSON-LD/DOM root error corrected. First successful run: 2 passed, 5 deselected, 19.55s. Final expanded metadata run: 2 passed, 10 deselected, 18.34s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py tests/test_api.py tests/test_automation.py -m "not browser"` with dedicated PostgreSQL | 47 passed, 2 deselected, 143.73s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py::test_concurrent_observations_are_idempotent_and_transactional` with dedicated PostgreSQL | 1 passed, 3.10s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py::test_concurrent_observations_are_idempotent_and_transactional tests/test_extraction.py::test_export_limits_cleanup_and_stale_worker_fencing` with SQLite | 2 passed, 19.22s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_agent.py tests/test_browser.py` | 41 passed, 394.58s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_interaction.py tests/test_user_agent_rotation_e2e.py tests/test_concurrency_audit.py::test_real_parallel_browser_context_storage_isolation tests/test_extraction.py tests/test_local_qwen.py -m browser` | 15 passed, 1 failed, 1 skipped. New metadata fixture used about:blank, correctly rejected as source URL. Corrected fixture navigates an intercepted HTTP URL; final extraction browser rerun passed both cases. Existing interaction/identity/isolation cases passed |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py::test_agent_enrichment_cannot_bypass_agent_token_budget tests/test_agent.py::test_token_budget_prevents_request tests/test_agent.py::test_fallback_budget_is_reserved_from_primary` | 3 passed, 26.67s |
| `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py::test_agent_enrichment_cannot_bypass_agent_token_budget tests/test_agent.py -k "goal_driven_real_browser or token_budget or fallback_budget or enrichment"` after shared budget integration | 8 passed, 26 deselected, 81.51s |
| `alembic upgrade head`, `alembic check`, `alembic downgrade a20d00000001`, `alembic upgrade head` against dedicated PostgreSQL | All succeeded; no schema drift detected |
| SQLite Alembic head → a20d00000001 → head | Passed in migration regression |
| `node scripts/e2e.mjs extraction.spec.ts` from root, isolated API/UI ports | First two attempts failed on exact label-text lookup of a nested select. Accessible combobox selector corrected the test. Final: 1 passed, 17.1s |
| `npm.cmd test` from frontend | 14 passed across 4 files |
| `npx.cmd tsc -b` and `npm.cmd run build` from frontend | Passed; production Vite build completed |
| `.venv\Scripts\python.exe -m ruff check backend/app backend/tests scripts/benchmark_extraction.py` from root | Passed |
| `git diff --check` | Passed |

The final full non-browser regression and frozen extraction-module results
are appended below. Tests were run during incremental development;
final targeted checks cover the later changes rather than misrepresenting early
runs as an immutable final checkout.

## What the tests verify

- Single/repeated CSS records; relative XPath; Product/JobPosting/Article/
  LocalBusiness JSON-LD; nested/malformed metadata; actual Chromium execution.
- Delayed JS content, readiness and pagination through the real worker and fixture
  HTTP server, preserving the existing crawl frontier and authorized egress proxy.
- Required/optional/type errors; ISO timezone/date, decimal/currency and URL
  normalization; field/schema complexity and allowlisted transformations.
- Unique identities, repeated-page idempotency, stable IDs, price changes,
  bounded revisions, concurrent writes, rollback and stale-token rejection.
- Failed/truncated runs cannot confirm missing records; successful repeated
  exhaustive runs transition active → missing → removed.
- Immutable schema versions, workspace isolation, schedule binding, actual queued
  JSON/CSV exports, byte-limit failure cleanup, formula escaping, download ownership
  and expiration. The 1,000-record benchmark exercises multi-batch JSON/CSV export.
- AI exact-quote support, invented-value rejection, untrusted-content instructions,
  persisted usage and shared agent-token enforcement with mocked provider output.
- Dashboard schema/dataset creation, dynamic extraction, history inspection and
  an actual CSV download using Playwright.

Explicitly not certified: live Groq extraction quality, real authenticated third-party
sites, arbitrary adversarial browser CPU workloads, multi-host network partitions,
paid-provider account quotas, or a production-scale soak test. The optional real
local Ollama model test was skipped because it was not enabled. Existing
Starlette/httpx deprecation warnings and Windows subprocess closed-pipe finalizer
warnings were visible and were not suppressed. This environment is Python 3.11;
the deployment/CI Python 3.12 matrix still needs normal CI execution.

## Final acceptance matrix

| Criterion | Status | Evidence / limit |
|---|---|---|
| Configure structured schema | PASS | Backend validation + dashboard field/JSON builder |
| Select built-in template | PASS | Five validated editable seeds; E2E selects products |
| Visit authorized site and extract | PASS | Real worker/catalog browser integration |
| JavaScript-rendered pages | PASS | Delayed catalog fixture with visible readiness |
| Normalize and validate | PASS | Numeric/date/URL/null/schema tests |
| Persist structured records | PASS | SQLite and PostgreSQL integration |
| Repeated runs avoid unwanted duplicates | PASS | Idempotency and concurrent observation checks |
| Detect real record changes | PASS | Stable ID, revisions and price-increase assertions |
| Failed crawls do not imply removal | PASS | Failed/truncated-run confirmation checks |
| Scheduled extraction | PASS | Existing tick + fixed dataset Schedule binding |
| Browse datasets in dashboard | PASS | Real API explorer and browser journey |
| JSON and CSV downloads | PASS | Queued exports + authenticated download assertions + UI CSV |
| Workspace ownership | PASS | Cross-workspace records/downloads denied |
| Existing workflows and agents | PASS | 41-test regression + later eight budget/goal checks |
| New feature tests | PASS | Completed grouped checks; final frozen module result below |
| Existing regression suite | PASS | 187 passing non-browser cases plus separate crawler/agent/interaction/identity browser runs; corrected fixture rerun recorded |
| Operational documentation | PASS | Implementation, API, usage, migration and benchmark docs |
| Unrestricted production readiness | BLOCKED | Inherited quota/SQL hot-path gates, live deployment/soak/interpreter matrix not certified |

## Second-pass review and concrete corrections

The second pass followed job snapshot creation through capture, persistence,
missing confirmation, export and retention. It corrected HTTP-error and truncation
removal hazards; per-record versus whole-page AI evidence; agent-budget bypass;
dataset creation/deletion locking; stale dataset edits; raw capture/JSON-LD limits;
fuzzy comparison work; spreadsheet formula handling; CSV nested-object loss; and
export pause/stop/orphan lifecycle. Regression tests cover the observable failures
and the shared authorization/lease paths were retained. No safety guard or failing
assertion was disabled to obtain a pass.

## Final verification results

- Complete non-browser regression: `..\.venv\Scripts\python.exe -m pytest -q -m "not browser"`:
  **187 passed, 1 skipped, 40 deselected**, 1294.52s. The skip requires explicitly
  configured test Redis. The 40 deselections are browser-marked tests, covered by
  the separate commands above except the explicitly disabled live Ollama case.
- Final extraction module: `..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py`:
  **12 passed**, 102.15s. Later tiny export batching/list cleanup safeguards receive
  a targeted export/normalization rerun recorded below.
- The benchmark was rerun with final provenance and lifecycle behavior; BENCHMARK.json
  contains that result and IMPLEMENTATION.md summarizes its measured values.
- Dedicated PostgreSQL container was stopped and removed after validation. The e2e
  harness stopped its isolated API/worker/scheduler/fixture/UI processes. Existing
  application services and credentials were left unchanged.

No failed check is hidden: earlier failures and their causes/reruns are preserved
above. These results establish the implemented acceptance paths on controlled
fixtures, not unrestricted production certification or a live-provider quality claim.

Final targeted export/normalization check:
`..\.venv\Scripts\python.exe -m pytest -q tests/test_extraction.py::test_normalization_schema_limits_and_templates tests/test_extraction.py::test_persistence_versions_dedup_changes_exports_and_ownership`:
**2 passed**, 13.63s. This includes revision-inclusive JSON export with one-record
batches, CSV output, normalization, ownership and artifact expiration. Final Ruff
and whitespace checks were also rerun successfully.
