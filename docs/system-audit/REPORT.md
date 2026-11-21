# Adbot comprehensive implementation audit

> Scope update: the added browser-profile configuration, identity compatibility validation, and compatibility dashboard have since been removed. Historical manifests, coverage receipts, and execution logs in this directory describe the earlier audited snapshot, not the current source tree.


Audit began 2026-11-19 and continued 2026-11-20. This report concerns the existing working tree, including substantial implementations that have not been committed. It does not certify HEAD alone. See [repository baseline](BASELINE.md), [file inventory](INVENTORY.txt), and the verification artifacts in this directory.

## Repository state and scope

Branch `main`, HEAD `f1505355d251f040c88169b28f9c359904ce1cda`. Existing user work, runtime configuration and credentials were preserved. No production database was migrated, reset or recreated; no deployment, commit, push or production service restart was performed. Tests and benchmarks use isolated temporary databases, artifact directories, loopback fixtures and deterministic model endpoints.

The execution paths were inspected across React API calls, FastAPI validation and ownership, SQL snapshots/leases, scheduler enqueueing, worker dispatch, browser/network policy, semantic targets, model accounting, extraction persistence and authenticated artifact downloads. Historical reports were treated as background, not fresh verification.

## Confirmed findings and corrections

| ID | Severity | Component | Finding / root cause | Resolution and regression |
|---|---|---|---|---|
| A01 | High | Persistence | Page fingerprint dedupe discarded A→B→A changes within one job because A had previously been observed. | Compare previously seen fingerprints against current active record hashes and job ownership. Reprocess real reversions; retain idempotency and skip/review policy behavior. `test_reobserved_content_reversion_is_persisted`, `test_reobserved_review_candidate_is_not_duplicated`. |
| A02 | Medium | Export consistency | Unchanged record observations updated exported `last_seen` without changing the export snapshot version. | Version every existing-record observation that changes exported metadata, without creating false business change events. `test_export_version_tracks_last_seen_and_retention`. |
| A03 | Medium | Retention/export | Retention deleted records without invalidating in-flight exports. | Increment the dataset version atomically when retention actually deletes records. Same regression as A02. |
| A04 | High | Empty extraction/removal | Zero matched records could report complete and contribute to removal confirmations, even when selectors were broken. | Record an `empty_capture` issue and partial status unless a configured `empty_state_selector` is visibly present. Failed, invalid, bounded and unconfirmed empty runs cannot confirm removals. Browser visibility and exhaustive-removal regressions cover both cases. |
| A05 | High | Planning/keyboard | Critical ambiguity blocked clicking a button but allowed Enter/Space activation. | Share one activation predicate across pointer and keyboard guards. Both keys have regressions. |
| A06 | Medium | Literal constraints | Straight/curly apostrophe contractions such as “Don't submit” were omitted from preserved constraints and guards. | Preserve and enforce don't/mustn't variants. Explicit “don't download” also overrides an optional download permission. Parameterized negative-constraint regressions. This is a bounded literal guard, not a claim to solve arbitrary natural-language reasoning. |
| A07 | Medium | Semantic privacy/identity | Redaction changed target names, URLs or form metadata before live identity comparison, making unchanged authorized controls appear stale. | Keep raw metadata privately in a bounded observation-scoped map; expose sanitized metadata to models/UI and compare raw values only during private target resolution. Browser secret-collision regression performs the real input without exposing the secret in the observation. |
| A08 | Medium | Modal authority | Last dialog in DOM order could be a background modal; nested modal diagnostics required focus in every sibling. | Select the modal containing native focus, report the active modal last, and fail closed when focus authority is ambiguous. Native focus recovery only chooses a single unambiguous modal. Reversed native top-layer order regression. |
| A09 | Medium | Downloads | Downloads used a cached public link without validating current physical target identity. | Route downloads through the same live bound-target resolution as other actions. Long-sequence browser regression mutates the link and verifies rejection before a download begins. |
| A10 | High | Schema lifecycle | A populated dataset could be relabeled with incompatible record identities/types, mixing old data with a new export contract. | After obtaining the dataset's version fence, reject incompatible changes when records or nonterminal extraction jobs exist. Selector-only compatible evolution is retained; structural changes require a new dataset. API rollback/ownership regression. |
| A11 | Low | Architecture documentation | Architecture documentation still claimed buttons required a site attribute and all mutating requests were forbidden, contradicting intentional autonomous-click behavior. | Document actual per-activation write grants, task form permissions, navigation restrictions and policy-driven recovery. Existing autonomous click policy remains intact. |
| A12 | Low | Timeout regression test | The test required an outgoing timeout to equal the original seven-second allowance exactly, although constructing the request consumes some of that allowance. Windows clock granularity previously concealed this incorrect assertion. | Check that exactly one request receives a positive timeout no greater than seven seconds. SQLite and PostgreSQL focused verification pass. The earlier PostgreSQL full run's actual failure was `6.985 != 7`, not an exceeded timeout. |
| A13 | Medium | Test isolation/performance | SQLite legacy DDL behavior committed every schema statement separately during each fresh-database fixture, causing excessive disk synchronization. | Create the same isolated schema in one explicit transaction and drop it in the existing teardown transaction. Same focused check: 15.95 s before, 1.69 s after; full isolation/concurrency tests retained. |
| A14 | Medium | Dashboard navigation | Fixed desktop sidebar had no vertical scroll, placing Disconnect outside short viewports; the mobile layout hid it entirely. | Scroll the fixed sidebar and expose mobile Disconnect. Existing publishing E2E reproduces desktop reachability; journey now verifies mobile logout. |
| A15 | Medium | Job monitoring | SSE completion messages updated the event list while job status and page queries retained their old HTTP snapshots for up to the global polling interval. | Refresh only the current job's status/pages/log queries per received event batch. The real crawl dashboard E2E is the regression. |
| A16 | Low | Weighted rotation E2E | Exact `getByLabel` matching failed on the wrapped select label, leaving the test waiting before rotation selection; teardown then masked that original timeout. | Select the native combobox by its accessible role and name. Partial JSON and comma-separated input assertions remain intact. |
| A17 | High | Agent/extraction integration | The new zero-record safeguard initially treated an agent's navigation/index page as a failed required capture, poisoning a subsequent valid scoped export. The complete cross-feature browser test caught this audit-introduced regression. | Distinguish optional agent/workflow observations from explicit captures and exhaustive crawls. Empty discovery pages do not poison later captures; a run with no captured pages still reports partial. The real plan → navigate → capture → owned export regression is retained. |
| A18 | Medium | Readiness/empty state | A record-only readiness selector could never become visible on a legitimate empty result page; optional discovery also waited needlessly for records before opening their panel. | Wait for a visible readiness selector OR the configured visible empty-state marker. Optional observations skip absent readiness without claiming data success. A real browser regression first failed in 19.14 seconds, then checks disclosure, hidden markers and positive empty-state readiness. |

Initial failing reproductions included the data reversion, metadata version, empty-success, keyboard ambiguity, contraction, redaction, modal-order and incompatible schema cases. Initial test harness errors (wrong expected creation status, missing required target, and an unsupported dataset-detail GET) were corrected before treating results as product defects. The early 13-case corrected regression run passed; final results are recorded separately below.

## Files and compatibility

Application corrections are in `backend/app/extraction/{api,schemas,service,persistence,exporter}.py`, `backend/app/agent/{planning,semantic_observer,semantics,interaction,controller}.py`, `frontend/src/App.tsx` and `frontend/src/style.css`. Behavioral regressions are in `backend/tests/test_system_audit.py` and `backend/tests/test_system_audit_browser.py`; the existing missing-record confirmation test now supplies explicit positive empty-state evidence. Dashboard export verification was strengthened in `frontend/e2e/extraction.spec.ts`, mobile logout in `journey.spec.ts`, and the weighted select locator in `user_agents.spec.ts`. Test fixture transactions and the timeout assertion were corrected in `backend/tests/{conftest,test_agent}.py`. Benchmark scripts now report SQL query counts, Windows peak working set and owned browser-process cleanup.

No new dependency or database migration was introduced by these audit fixes. `empty_state_selector` is an optional JSON configuration field, read with `.get()` so existing stored snapshots remain usable. Absence defaults conservatively to partial rather than treating selector failure as a valid zero-result dataset. Configure an actual visible empty-state marker on sites where an exhaustive successful run can legitimately contain no records. Positive empty-state evidence is necessary but does not override failed pages, truncation, unresolved frontier entries, limits or required-field errors.

## Feature execution and verification matrix

| Feature | Executable path / integration | Evidence scope |
|---|---|---|
| Structured extraction | DataExtraction → extraction API → job snapshot → browser `extract_page` → normalization/validation → fenced persistence | CSS, XPath, JSON-LD, dynamic pagination, invalid fields, AI evidence, empty-state, disclosure interaction |
| Task understanding | AgentPanel/API → immutable specification → typed intent/decision contracts | Multiple objectives, export ambiguity, preserved literal constraints; arbitrary live-model semantic quality remains unverified |
| Planning | TaskPlan graph → ready dependencies → action guards → final evidence verifier | Dependency/cycle/budget rejection, task ceiling and original-objective retention |
| Dynamic replanning | Classified failures → bounded recovery nodes → fresh observation | Durable failed-action recovery, stagnation and no replay after uncertain writes |
| Task memory | Bounded recent actions/evidence → owner/site historical hints → encrypted optional session | Memory isolation, stale evidence warnings, compaction, original specification retention |
| Accessibility / semantics | Native Playwright ARIA → bounded DOM supplement → exact physical binding → native action/state validation | Real engines, duplicate contexts, hidden/disabled/secret controls, replacement, redaction collision |
| Keyboard / focus | Targeted native keys and fill → focus/validation/state checks → bounded modal recovery | Tab, Enter, Space, checked/selected states, native modal top-layer order |
| Browser configuration | Immutable context profile and network assignment → native engine context | Engine/version identity, viewport, locale, timezone, cookies/storage, no navigator patching |
| User-Agent consistency | Admin profiles → job network assignment → proxy/browser/HTTP identity | Rotation reaches destination; active session is stable despite configuration edits |
| Proxy integration | Outbound manager → loopback policy proxy → validated pinned upstream IP | Controlled proxy/TLS/failure tests; external provider/OS-level egress certification remains separate |
| Scheduling | Cron/timezone → due-time CAS → snapshot queue → worker | Real changed-page scheduled repeat plus scheduling/idempotency tests |
| Persistence / dedupe | Dataset write serialization + job lease fence + identity/hash + observations | Concurrent observations, rollback, reversion, duplicate policies, revision bounds |
| Change detection | Normalized field deltas → durable events/revisions → exhaustive missing confirmations | Real scheduled price change, failed/empty/truncated safeguards and confirmed removal |
| JSON/CSV exports | Owned dataset → existing queue → bounded writer → version check → authenticated download | Actual content comparison, escaping/formula prevention, expiration, size bounds, workspace isolation |
| Worker recovery | CAS leases → expiry recovery → read checkpoint replay or fail uncertain mutation | Committed extraction retained, old-token write rejected, selections/clicks not blindly replayed |
| Security | Strict schemas + owner queries + transport/domain/DNS/method policy + bounded resources | Local hostile fixtures and negative API tests; website content cannot grant permissions |
| Frontend/backend | Typed API client and React query mutations → real API/worker/artifacts | Component tests, production build and full dashboard E2E suite |

## Mandatory cross-feature scenarios

| Scenario | Actual integration boundary / test |
|---|---|
| A Planning + accessibility | `test_planner_semantic_tools_transport_and_durable_traces`: deterministic model endpoint chooses real browser form/selection controls; durable traces and final verification |
| B Accessibility + extraction | `test_semantic_disclosure_extraction_and_confirmed_empty`: native disclosure click exposes product; extraction service captures and persists it; hidden empty marker rejected |
| C Pagination + dedupe | `test_real_worker_dynamic_pagination_pipeline`: two real catalog pages with repeated listing produce one persisted identity |
| D Session + proxy + UA | `test_rotation_reaches_destination_and_preserves_active_session` and outbound transport tests |
| E Long-running planning | Existing multi-step agent objectives and independent budget tests plus 25 real semantic action/observation/planning cycles; no invented final success. This is deterministic fixture evidence, not a 500-step live-LLM endurance claim. |
| F Scheduler + changes | `test_scheduler_executes_repeat_and_persists_real_change`: run, change fixture price through source URL, schedule repeat, assert updated durable price and event |
| G Crash + recovery | `test_expired_worker_preserves_extraction_and_fences_old_writer`, interrupted mutation and uncertain-dispatch tests |
| H Multiple concurrent jobs | Real two-worker browser/egress execution with separate workspace jobs and cleanup, plus global capacity/domain admission/failure-isolation tests. A test-only exact localhost:8765 extension supplies the second loopback origin; production SSRF rules are unchanged. |
| I Compatibility + accessibility | Same semantic laboratory in Chromium, Firefox and WebKit, plus policy-proxied agents in Firefox/WebKit |
| J Extraction + exports + dashboard | Dashboard queues extraction, inspects revisions, downloads CSV and JSON, and compares data with persisted records |

## Verification status

Final verification is in progress. Do not interpret the feature matrix as a clean test result until the command ledger and final readiness statement below are filled from completed runs.

Baseline: Ruff and whitespace checks passed; planning/recovery subset 8 passed; frontend 18 passed and production build passed. Corrected early audit regression: 13 passed. Initial broader integration: 24 passed, 4 failed. One failure was a test fixture using localhost outside the deliberately exact fixture exception; that harness has been corrected with a scoped second-origin exception. The three engine failures were timeouts at different actions/navigation while the host also delayed routine file reads and a normally short Vite build to four minutes. They are retained as failures and require a final isolated browser run; timeout limits have not been relaxed to conceal them.

## Performance

The isolated 1,000-record benchmark reports real normalization/persistence/export throughput, query counts, Python allocation peak, CPU time and Windows peak working set in `extraction-benchmark.json`. It performs no external network or model calls. Observed 7,100 persistence queries demonstrate that per-record lookup/revision/change writes dominate this workload; this audit preserves transactional correctness rather than introducing a speculative bulk-write rewrite. Host scheduling delays make end-to-end wall-time comparisons from separate runs unreliable; historical results are not presented as a controlled before/after speedup.

## Remaining validation boundaries

- Live Groq/Qwen reasoning quality and a 500-step live model endurance run are not demonstrated by deterministic fixtures. New tasks must still start on Groq; provider fallback is checked by transport tests. Credentials/configuration were not changed or printed.
- PostgreSQL multi-process contention, a deployed Redis outage, external proxy providers and production network egress need their own environment qualification. Local SQLite/loopback passes are not equivalents.
- Automated ARIA/browser testing does not certify a site with manual screen reader or other assistive technology use.
- General-language requests for arbitrary filtering/sorting are bounded by configured schemas, available tools and final evidence validation. A typed plan is not proof that every user intent can be fulfilled.

Final readiness is pending completed regression evidence; this document must not be used as production approval in its current state.
