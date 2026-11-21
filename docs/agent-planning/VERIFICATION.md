# Executed verification

All commands used isolated temporary test databases and local fixtures. Tests never used the real Groq key or production website credentials. Commands below are PowerShell paths from the repository root unless a working directory is specified.

Runtime: Windows, Python 3.11 in the existing `.venv`, backend Playwright 1.56.1. The backend requirements declare Playwright 1.56.0; this preexisting environment difference was not silently changed. Reinstall from the pinned dependencies and rerun deployment/CI checks for release certification. The project's deployment Python runtime was not separately certified by this local run.

| Check | Actual result |
|---|---|
| `ruff check backend/app backend/testsupport` plus new planning/browser tests and benchmark script | Passed |
| `git diff --check` | Passed |
| Backend broad `pytest -q -m 'not browser'` | 194 passed, 1 skipped, 43 deselected; 1656.22s |
| Backend `pytest -q tests/test_agent.py -m 'not browser'` | 18 passed, 15 deselected; 125.42s |
| Backend `pytest -q tests/test_agent.py -m browser` | 15 passed, 18 deselected; 224.50s |
| Backend `pytest -q tests/test_planning_browser.py tests/test_interaction.py tests/test_browser.py -m browser` | 22 passed; 267.17s |
| Scoped-export/concurrent-read and uncertain-submission browser tests rerun | 2 passed; 59.26s |
| Planning plus extraction non-browser checks after scope changes | 16 passed, 2 deselected; 202.93s |
| Planning contracts/checkpoints/scope checks | 6 passed; 47.75s; final focused rerun also recorded below |
| Planning, full-record artifact verification and configured Groq-first handoff tests | 33 passed; 266.57s |
| Planning + browser plan/export + extraction regression batch | 20 passed; 171.84s |
| Final scope/export and no-replay browser rerun after redundant post-action capture reduction | 2 passed; 39.34s |
| Agent completion through Adbot's actual policy proxy on Firefox and WebKit | 2 passed, 2 deselected; 63.84s |
| Frontend `npm.cmd test` | 5 files, 16 tests passed |
| Frontend `npm.cmd run build` | TypeScript and Vite production build passed |
| `ADBOT_E2E_API_PORT=18000`, `ADBOT_E2E_FRONTEND_PORT=15173`, `node scripts/e2e.mjs agent.spec.ts extraction.spec.ts` | 3 passed; 35.4s |

The dashboard E2E tests cover a literal-constraint preview, invalidation on form edits, actual worker completion, plan display, evidence, browser captures, interaction trace, desktop/mobile layout, dynamic dataset extraction and CSV download. Desktop and 390px mobile screenshots were inspected. The task E2E initially reached its overall 60s test timeout on the loaded machine; its local timeout is now 120s. A new preview assertion initially incorrectly expected sentence punctuation inside a parsed constraint fragment; that assertion was corrected. The final run passed all three tests.


New contracts tests exercise simple/multi-objective/conditional/export instructions, immutable literal requirements through prompt compaction, disclosed defaults and conflicting formats, malformed/injected plans, fabricated outcomes, dependency bypass/cycles, hierarchy, retries and checkpoint serialization, blocking authorization, stagnation, verification gating, owner-scoped preview. Scoped record tests reject changed concurrent data while retaining records when another task merely changes `last_job_id`. The browser export test excludes a historical unrelated record and rejects another workspace's download. The uncertain-write test dispatches one submission with deliberately missing expected confirmation and verifies that it is not replayed or reported successful.

Warnings observed: current Starlette TestClient/httpx deprecation; Windows Python 3.11 Proactor/subprocess finalizer warnings after the combined browser batch; Node NO_COLOR/FORCE_COLOR notice. These are recorded rather than represented as warning-free execution. No opt-in real local-Qwen test or live-provider model-quality benchmark was run.

The broad non-browser run covered API, agent transport/budgets, automation, ownership/security/privacy, concurrency/worker/scheduler, extraction/export, outbound policy/proxy and UA regressions. It ran alongside iterative implementation. Later focused suites checked the final scope/hash handling, full-record artifact verification, ambiguity handling, no-replay behavior and provider handoff; the last browser checks also covered Firefox/WebKit through the policy proxy. Counts from overlapping runs must not be summed as unique tests. Every run listed above completed; no background test was left running at handoff.

The single broad-suite skip requires an explicitly configured isolated test Redis. The opt-in live local-Qwen browser test was not enabled.
