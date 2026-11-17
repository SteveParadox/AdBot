# Automation verification

Verification uses temporary SQL databases and controlled fixture/model endpoints. Live advertising,
third-party account changes and paid provider calls are not part of these tests.

## Commands

From `backend` using the repository virtual environment:

```powershell
..\.venv\Scripts\python.exe -m ruff check app tests testsupport
..\.venv\Scripts\python.exe -m pytest -q -m 'not browser'
..\.venv\Scripts\python.exe -m pytest -q -m browser
```

From `frontend`: `npm.cmd test`, `npm.cmd run build`, and `npm.cmd run test:e2e`.
Use `ADBOT_E2E_API_PORT=8100`, `ADBOT_E2E_FRONTEND_PORT=5180` and `ADBOT_E2E_STARTUP_MS=60000`
when the development stack occupies the default API/frontend ports. Fixture ports 8765/8766 must be
free. Run backend browser tests and E2E serially because both use those controlled endpoints.

## Coverage

New automation suites exercise authorization, policy CAS/history/caps, manual release, pause/emergency,
priority/dependencies, cross-workspace rejection, schedule/backlog admission, retry/agent backpressure,
expired assignments, threads plus separate-process counters, shared proxy circuits, all User-Agent
strategies, compatible fallback, weighted selection, identity continuity, stale fencing, revision
watching, durable alerts, cleanup and migration history preservation/upgrade/downgrade/reapply.
Additional review cases cover fixed routing, protected authenticated sessions, persistent failover,
out-of-order health publications, running-job pause/resume and dependency-preserving retry.

Privacy regression tests use the actual Uvicorn AccessFormatter with colors both on and off, status
200/403/500, repeated handler installation and repeated filters. This reproduces and prevents
`ValueError: not enough values to unpack (expected 5, got 0)` while verifying secret redaction.

The existing GitHub workflow already discovers all backend tests, runs real browser/E2E journeys,
frontend unit/build/audit checks, migrations and PostgreSQL/Redis tests. New tests need no separate
competing CI workflow. Local results and remaining checks are recorded below once verification finishes.

## Local results

- Privacy suite: 18 passed; the specific new formatter cases also passed separately (2).
- Earlier API/User-Agent/outbound regression pass: 46 passed.
- Frontend: production build passed; 6 unit tests passed.
- SQLite backend: 125 non-browser tests passed; 28 browser tests passed after updating three outdated model test-double signatures.
- PostgreSQL 17 / Redis 7.4: migration upgrade and Alembic check passed. Initial full run: 124 passed, one failed because a diagnostics test assumed Redis was disabled. After correcting that expectation, all 42 outbound/automation/review tests passed against PostgreSQL and Redis.
- Later heartbeat/revision checks: 2 passed.
- npm audit: zero reported vulnerabilities. Python dependency audit was not completed.
- Latest full E2E run: 6 passed, 2 failed. Content publishing/conflict handling, Automation controls, ordinary User-Agent saving and crawl journey passed. The agent-result journey timed out, and the weighted User-Agent editor journey timed out with a cleanup error masking the original wait. These failures remain unresolved; no clean full-E2E claim is made.
- Subsequent identity/network presentation changes: production build and 6 frontend unit tests passed; full E2E was not rerun after those last presentation changes.

Observed initial failures were fixed rather than skipped: shared health required test isolation/recovery;
dependency constraints required test teardown to clear test-only edges; SQLite inline-FK reflection
required matching default NO ACTION semantics in model/migration. Final results supersede intermediate runs.

Production PostgreSQL/Redis multi-host behavior, external proxy exit allocation/TLS, hosting restart/load,
Cloudflare/DNS/firewall and a real backup restore remain external verification requirements. CI configuration
is evidence of configured checks, not proof that those remote checks have executed for this unpushed work.

## Groq / Qwen follow-up (2026-11-17)

- Real local Qwen3:4b + Playwright: passed the complete controlled browser task after simulated Groq
  429 in 131.35 seconds, with one job ID, actual stored evidence citation and successful verification.
- Primary errors/429/timeouts, early quota headers, task-local sticky fallback, native JSON output,
  malformed-output feedback, budget/deadline handling, warm-up and shutdown have focused regression tests
  in test_provider_handoff.py alongside the existing test_agent.py model tests.
- Local inference is CPU-only here; observed cold loading took about 103 seconds. Worker warm-up moves
  that delay before pickup. Routing handoff and inference completion latency are different measurements.
- The test fixture simulates Groq responses and uses real local Ollama; no live Groq quota was consumed.
- Final focused regression: 34 passed (test_provider_handoff.py plus non-browser test_agent.py);
  13 existing browser tests were deselected in that command. Backend Ruff checks passed.
- Real local compatibility/negative-verification probe passed in 42.19 seconds: simulated Groq 429,
  one valid Qwen extraction decision, then Qwen correctly rejected an unsupported 2030 launch claim
  against evidence stating 2026. Calls were Groq-stub once, real Qwen twice.
- Frontend production build and all 7 unit tests passed for the backup readiness badge.
- No full unrelated project E2E rerun is claimed for this follow-up. Previously documented unrelated
  E2E failures remain recorded above.

## User-Agent rotation simulation (2026-11-17)

Real browser destination-header capture passed: five jobs, ten page visits, round-robin A/B/A,
mid-session configuration edit with identity continuity, next-session revision activation, disabled-profile
exclusion, robots identity matching, disclosure headers and assignment cleanup. Runtime: 25.91 seconds.
[Detailed evidence](../testing/USER_AGENT_ROTATION_E2E.md).

## Click recovery and observation loops (2026-11-17)

- Added recovery for an unchanged ordinary observed link when its pointer trial times out
  before dispatch. Recovery uses the existing permitted navigation path. Forms, review-required
  actions, changed targets, buttons and ambiguous actual-click timeouts do not receive this recovery.
- Repeated unchanged OBSERVE decisions now receive recovery feedback instead of counting as
  successful progress. An exhausted model deadline exits without another observation/replan;
  this also covers a network timeout arriving after the deadline.
- Four real-browser recovery cases passed: covered link navigation, covered button rejection,
  ambiguous dispatched-click rejection and changed-target rejection.
- Latest complete interaction test run: 7 passed, 4 failed in 135.18 seconds. All four new recovery
  cases passed. The failures were existing hover, focus, no-effect click and delayed-confirmation
  cases hitting their 700 ms action deadlines. This is not a clean full-suite result.
- Runner observation/deadline browser regressions: 2 passed. Focused model/agent non-browser
  regressions: 35 passed before adding the final network-timeout deadline case; both deadline
  variants subsequently passed (20 other provider cases deselected).
- Backend Ruff and git diff whitespace checks passed. The external website from the reported
  job was not retested; these reproductions use the controlled local browser fixture.
- Restart the API and worker to load the changes, then submit a new task. The already-expired
  job does not resume automatically. Local CPU inference can still consume the task time budget.

## Worker source recovery and search fallback (2026-11-17)

The reported import failure was reproduced: model.py contained only null bytes. Two local
fallback test files had the same corruption. Recovered the files from recorded source edits,
preserving the native Ollama, sticky failover, warm-up and deadline behavior. Compilation of
app/tests/testsupport, explicit worker/model imports, changed-text null-byte scanning, Ruff
and whitespace checks passed after recovery. The cause of the file corruption is undetermined.

Read-only inspection of job 1d9a40e6-c02a-4cbd-af9d-97f102ec3286 showed a 600-second site
limit, seven model calls and about 559 seconds of model latency. Form input was disabled.
The Search textbox appeared in a later observation; no successful query submission is recorded.
Updated the prompt to explain automatic observations and explicit SEARCH parameters, and to
request permission when form input is disabled. Validation feedback now names invalid/missing
fields. An exhausted runner deadline is rejected before opening another model request.

These changes do not grant form permission or extend the website time limit. Enable form input
when creating a task that should type a search query. Restart the worker after loading the repaired
source; no live queue jobs were executed as part of the import check.

Post-recovery regression: provider handoff plus non-browser agent tests passed, 37 passed /
15 deselected in 200.76 seconds. The separately added runner pre-request deadline regression
also passed (1 passed / 23 deselected). This run uses simulated provider responses; real Qwen
inference and the external website were not rerun after recovery.

## Agent outcome UI (2026-11-17)

Interaction results can omit scroll metadata, including ordinary link navigation recovery.
The task detail view now renders these outcomes without reading a missing scroll.y and retains
valid zero scroll positions. All 12 frontend unit tests and the production build passed.
