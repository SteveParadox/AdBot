# Executed checks and acceptance matrix

All browser work used controlled local fixtures, temporary databases and test-double models. No real Groq/Qwen quality evaluation or production submission was performed. The existing Windows/Python 3.11 environment has backend Playwright 1.56.1 while requirements declare 1.56.0; release/CI verification from pinned dependencies remains necessary.

## Results

| Command / check | Actual result |
|---|---|
| Ruff on backend application, fixture model, new accessibility tests and scripts | Passed |
| `git diff --check` | Passed |
| Initial existing `pytest -q tests/test_interaction.py` | 12 passed; 104.10s |
| Agent/planning/provider non-browser regression group during implementation | 49 passed, 15 deselected; 288.49s |
| Final selected non-browser group: agent, planning, provider handoff, security, privacy | 71 passed, 15 deselected; 476.92s |
| Combined browser group: accessibility, semantic agent/safety, interactions, agent and planning browser regressions | 35 passed, 1 failed, 19 deselected; 742.73s; failed Firefox inspection read fixed as described below |
| Corrected Firefox conformance rerun, `pytest -xq tests/test_accessibility.py -k firefox` | 1 passed, 3 deselected; 114.78s |
| Complete WebKit scenario rerun through the same test function using the controlled fixture | Completed successfully |
| End-to-end semantic tools → planner/worker/transport/evidence/steps | 1 passed; 41.60s |
| New selection crash recovery plus semantic safety/navigation checks | 3 passed; 36.46s |
| Final safety rerun including Space permission checks, hidden-value handling and interrupted-observation navigation | 1 passed; 21.70s |
| Frontend Vitest | 6 files, 18 tests passed |
| Frontend TypeScript/Vite build | Passed |
| Final dashboard E2E: semantic controls, preview, cited completion and extraction/CSV download | 4 passed; 56.8s |
| Final ID-less menu focus, selection authorization and interrupted-observation safety check | 1 passed; 16.03s |
| axe-core audit script with the actual 4.10.3 bundle | Passed reference assertions; violations recorded in AXE_RESULTS.json |

These overlapping runs are not counts of unique tests to sum. The mixed browser run's Firefox failure was an actual `Locator.element_handle` inspection timeout, not an application write. Inspection now drops transiently unavailable candidates and retries the observation once when incomplete, while retaining coherent document/URL provenance. The corrected scenario passed. The other 35 cases in that batch passed, including Chromium/WebKit control scenarios, existing interaction/agent coverage and the planner/browser profile checks. Tests were not disabled. A mistaken invocation that bound fixture ports concurrently was stopped and replaced with sequential fixture-dependent suites; its port errors are not counted as application regressions or successful checks.

Earlier failures also identified missing native dialog candidates, an ElementHandle focus signature mismatch, expected dialog focus leaving the document, malformed nested fixture HTML, a role-insufficient test selector for a tab versus tabpanel, an action trace field collision, and excessive context history. These were corrected and rerun. The test suite retains native assertions for the underlying behavior.

The positive control scenario exercises actual native input, names/labels/descriptions, hidden/disabled controls, duplicate names in distinct regions, native checkbox/radio/select/date/number controls, custom switch/combobox, readonly and native validation, dialogs/focus containment/restoration, disclosures, tabs, trees, grids, feedback, virtualized/replaced nodes, an imperfect DOM fallback, sanitized observations and bounded model requests. Browser-specific timing is allowed within the same bounded supported interaction configuration; no engine is silently replaced.

The safety scenario checks unresolved duplicate names, form-input authorization through both click and setter, protected fields/keyboard, readonly input, false expansion claims, unknown-role fallback, bounded traversal, unobserved Enter activation, public hidden-value collisions, and navigation during a semantic read. Worker recovery tests confirm that expired in-flight SET_CHECKED and SELECT_OPTION operations require manual inspection and retain the original task contract.

The agent integration uses real local HTTP model transport, the actual worker, durable plan state and observed controls. Its deterministic fixture chooses supplied element IDs and reads actual current values/states; it is explicitly not a live-model reasoning benchmark. The frontend workflow checks semantic control outcomes and readable diagnostics, task preview, cited completion and extraction/download regression behavior. Desktop semantic-agent and mobile agent captures were inspected. Screenshot review exposed an early verified-result panel while status was still running; the panel now requires both a completed task and completed verification. Input values are visibly masked in captures. The final safety check also verifies focus movement between ID-less same-tag menu items, so a real keyboard transition cannot disappear from change detection merely because the elements have no IDs.

## Acceptance matrix

| Acceptance criterion | Status | Evidence / scope |
|---|---|---|
| Identify controls using native roles and accessible names | PASS | Native snapshot headers plus exact role/name locators across Chromium, Firefox and WebKit. |
| Correct native/ARIA field labels and descriptions | PASS | Label and aria-labelledby precedence fixtures; native names and supplemental descriptions. |
| Keyboard-driven interaction | PASS | Actual Tab/Shift+Tab/arrows/Escape infrastructure, Enter/custom combobox and Space/checkbox checks; disallowed keys rejected. |
| Focus movement, containment and restoration | PASS | Real focus assertions, one bounded modal recovery, restoration diagnostics and traversal ceiling. |
| Dynamic ARIA checked/selected/expanded/active-descendant states | PASS | Native/custom controls and explicit positive/negative state checks. |
| Modal and custom widget support | PASS | Supported DOM dialogs, native controls, switch, autocomplete, tabs, tree and grid; unknown patterns remain bounded failures. |
| Resolve material ambiguity using context | PASS | Named region/heading scoping; indistinguishable duplicate controls rejected. |
| Controlled fallback for imperfect markup | PASS | Unique DOM/test identifiers and bound node fallback; unknown roles do not create executable selectors or code. |
| Refresh/invalidate stale references | PASS | Physical-node WeakMap/handles, same-markup replacement, virtual list replacement and coherent navigation retry. |
| Action-specific outcome checks | PASS | Actual values, checked/selected states, controlled visibility, focus and expected feedback; no-op clicks explicitly unverified. |
| Planner/model integration | PASS | Semantic availability and dialog context supplied; actual worker semantic tool flow and durable outcomes verified. |
| Browser/session consistency | PASS | Existing native configuration and identity preserved; three engine scenarios and existing profile/planning regressions. |
| Authorization, privacy and replay boundaries | PASS | Form/input guards, readonly/secret restrictions, screenshot masking, sanitized diagnostics, method/domain policy regressions, ambiguous selection crash tests. |
| Existing backend behavior | PASS | Selected agent/planner/provider/security/privacy tests and existing real-browser agent/interaction/planning cases; broader unmodified subsystems retain prior reports. |
| Dashboard diagnostics and complete UI flow | PASS | Frontend unit/build verification plus final local dashboard E2E result below. |
| Accessibility audit reporting | PASS | Clean reference zero WCAG-tagged violations; imperfect/known-bad fixtures report expected violations. |
| Manual screen-reader/assistive-technology certification | BLOCKED | Not performed in this environment; automated/native tests do not replace it. |
| Universal site compatibility or live-provider model accuracy | BLOCKED | Not established by these controlled fixture tests. |

PASS applies to the implemented/tested scope, not every widget on every website. No general production-readiness certification is claimed. See REPORT.md for unsupported frames/shadow roots, event-handler races, generic text privacy limitations, and the observation latency/context tradeoffs.

Warnings observed: current Starlette TestClient/httpx deprecation and Node NO_COLOR/FORCE_COLOR notices. Optional npm access failed; the actual audited bundle was obtained with normal Python TLS verification. No network or authorization guard was disabled to make tests pass.
