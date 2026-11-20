# Verification ledger

All tests ran against temporary fixture databases and artifacts. Production credentials, databases and running user services were not modified. Repeated subsets below overlap and must not be added together as a unique-test total.

| Check | Command / configuration | Completed result | Evidence |
|---|---|---|---|
| Baseline planning/recovery | `pytest -q tests/test_planning.py tests/test_accessibility_recovery.py` | 8 passed | Baseline tool output |
| Early audit reproductions after fixes | `pytest -q tests/test_system_audit.py tests/test_system_audit_browser.py` (early 13-case version) | 13 passed | `targeted.log`, `targeted.xml` |
| Complete non-browser suite, SQLite | `pytest -vv -m "not browser"` | 213 passed, 1 skipped, 56 deselected; 263.55 s | `sqlite-final.log`, `sqlite-final.xml` |
| Focused PostgreSQL + Redis | concurrency, concurrency audit, extraction and new system audit tests; browser marker excluded | 50 passed, 3 deselected; 111.43 s | `postgres-redis.log`, `postgres-redis.xml` |
| Complete non-browser suite, PostgreSQL + Redis | `pytest -vv -m "not browser"` with isolated container URLs | 214 passed, 56 deselected; 273.57 s | `postgres-verified.log`, `postgres-verified.xml` |
| Frontend component/contract tests | `cd frontend; npm.cmd test` | 6 files, 18 tests passed | Tool output, 10.45 s final run |
| Frontend production build | `npm.cmd run build` | TypeScript and Vite passed | Tool output, 41.52 s final build |
| Complete dashboard E2E | `ADBOT_E2E_API_PORT=18000 ADBOT_E2E_FRONTEND_PORT=15173 ADBOT_E2E_STARTUP_MS=180000 node scripts/e2e.mjs` | 11 passed; 1.3 min | `dashboard-verified.log` |
| Application/fixture lint | `ruff check backend/app backend/testsupport` plus new audit tests/benchmark scripts | Passed | Tool output |
| Whitespace | `git diff --check` | Passed | Tool output |

The SQLite skip is the real-Redis test, which passed with the isolated Redis container. The final PostgreSQL run covers it without a skip. Source configuration is Groq `openai/gpt-oss-120b` first, local `qwen3:4b` fallback; the read-only check printed only provider/model names. Both provider-order/fallback tests and budget tests ran in the complete non-browser suites.

## Failure history retained

Earlier runs are not clean final passes:

- Corrected initial test harness mistakes before relying on bug reproductions: expected 201 rather than 202, supplied mandatory observed targets, used the supported dataset collection endpoint.
- `integration.log`: 24 passed, 4 failed. Incorrect localhost fixture configuration was corrected; native engine timeouts were retained for follow-up.
- `browser-isolated.log`: 6 passed, 1 failed at a 500 ms click dispatch. New cross-feature tests now use the controller's actual 3000 ms input budget rather than an artificially short test-only budget.
- Earlier long SQLite runs were explicitly stopped while diagnosing fixture disk synchronization; their logs remain. The final complete SQLite run uses atomic schema setup/teardown and passes.
- `postgres-full.log`: 213 passed, one timeout-test assertion failed because an outgoing `6.985` second timeout was correctly less than the original `7` second allowance. The assertion now checks the actual bound. Focused verification passed on both databases and the subsequent full PostgreSQL run passed all 214 tests.
- `frontend-e2e.log`: frontend readiness exceeded the harness's original 20-second startup budget. The retry uses its existing configurable 180-second readiness ceiling, without adding sleeps or weakening interaction assertions.
- `frontend-e2e-final.log`: 8 passed, 3 failed. This exposed the unscrollable Disconnect button, stale job/page HTTP queries despite SSE completion, and an invalid exact-label test locator. All three corrections passed in the subsequent complete 11-test run.
- `weighted-isolated.log` preserves the locator reproduction; `dashboard-verified.log` includes the corrected partial-JSON/weighted-rotation flow.
- `browsers-verified.log` preserves the native Windows Python 3.11.2 run, including timeout diagnostics and an access violation reported during stack inspection. It is not a clean browser-suite result.

The Starlette/httpx deprecation warning and Node's conflicting color-environment warnings were not hidden. The Windows native access violation is not attributed conclusively to application code, the interpreter or a dependency without an isolated reproduction.

## Reproducible environments

Windows development checks: Python 3.11.2, Playwright 1.56.0, existing installed native Chromium/Firefox/WebKit. Test databases are independent of the user database. Dashboard tests start their own API, worker, scheduler, deterministic model service and fixture site, then stop only those processes.

Database integration: temporary containers `adbot-audit-pg-20261120` (`postgres:17-alpine`) and `adbot-audit-redis-20261120` (`redis:7-alpine`), labeled `adbot.audit=20261120`, with loopback-only dynamically allocated ports 51762 and 51782. Redis test database 15 and database `adbot_audit` contain test data only. Container cleanup is recorded after verification.

Browser fallback qualification: existing `adbot-worker:latest` image, Python 3.12.15; current repository backend bind-mounted read-only at `/app` and audit outputs mounted at `/audit`. It runs in its own network namespace, with a 2 GiB memory limit, 2 CPU limit and 512 MiB shared memory. This tests current source rather than the image's older copied application. The final browser result is recorded in `REPORT.md` after completion.

## Performance artifacts

- `agent-benchmark.json`: real browser + deterministic model fixture; completion, latency, calls, tokens and action dispatch timing.
- `semantics-benchmark.json`: three real observations, serialized/model request sizes and only this benchmark's browser process descendants before/after close.
- `extraction-benchmark.json`: 1,000 records, persistence and JSON/CSV throughput, SQL counts, CPU/allocation/working-set peaks, and expired read-job SQL requeue overhead.
- `concurrency-benchmark.json`: bounded four-thread I/O stress at 5/10/25/50/100 tasks; synthetic workload, not a browser throughput claim.

Historical reports in other documentation directories are not counted as fresh passes for this audit.
