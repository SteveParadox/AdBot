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
