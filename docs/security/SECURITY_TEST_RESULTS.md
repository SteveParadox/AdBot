# Security test results — 2026-11-13

## Latest verified results
Final non-browser backend run: **50 passed, 28 deselected**; additional log-handler/configuration guard
focused test: **1 passed**. Browser journeys: **4 passed**. Frontend unit tests: **4 passed**.
TypeScript/Vite build, app-wide Ruff, whitespace, Compose config and pip consistency checks passed.
Fresh npm audit after the Vitest patch: **0 vulnerabilities**. Nginx container validation remains
blocked by Docker Hub DNS; real TLS/origin/Cloudflare checks remain pending. Earlier attempts below
are retained as evidence and are superseded by these final successful local application runs.


Only commands actually executed are recorded. No production network scan or external account change
was performed. External firewall/DNS/TLS/Cloudflare protections remain unverified.

| Check | Command / method | Actual result |
|---|---|---|
| Initial backend regression | From backend: `../.venv/Scripts/python.exe -m pytest tests/test_privacy.py tests/test_content.py tests/test_api.py tests/test_security.py -q` | 33 passed; one Starlette/httpx deprecation warning |
| Broad backend non-browser | From backend: `../.venv/Scripts/python.exe -m pytest -q -m 'not browser'` | 48 passed, 28 deselected; one deprecation warning; includes new distributed-limit unit test |
| Lint | `.venv/Scripts/python.exe -m ruff check backend/app/privacy.py backend/app/main.py backend/app/config.py backend/tests/test_privacy.py` | Passed |
| Whitespace | `git diff --check` | Passed; Git may display normal LF/CRLF conversion warnings |
| Frontend build/typecheck | From frontend: `npm.cmd run build` | TypeScript and Vite production build passed |
| Frontend unit tests | From frontend: `npm.cmd test` | 4 passed across 2 files |
| Build source maps | Enumerate `frontend/dist/**/*.map` | 0 map files in default production build |
| Python environment consistency | `.venv/Scripts/python.exe -m pip check` | No broken requirements |
| Python CVE scanner availability | `.venv/Scripts/python.exe -m pip show pip-audit` | Not installed; no Python advisory scan claimed |
| Initial npm advisory scan | From frontend: `npm.cmd audit --json` | 2 moderate findings, Vitest/mocker; no high/critical. Patch attempt recorded below |
| Compose syntax/interpolation | `docker compose config --quiet` | Passed; configuration was not printed, to avoid exposing interpolated secrets |
| Docker daemon | `docker info --format '{{.ServerVersion}}'` | Responded 29.9.2 |
| Nginx container config test | `docker run --rm --network none --add-host api:127.0.0.1 --mount ... nginxinc/nginx-unprivileged:stable-alpine nginx -t` | Blocked: image unavailable locally and Docker Hub DNS lookup failed. No successful Nginx runtime/container build claimed |
| Browser run 1 | `npm.cmd run test:e2e` | Startup failed: existing service occupied API port 8000; not stopped |
| Browser run 2 | `ADBOT_E2E_API_PORT=8100 npm.cmd run test:e2e` (PowerShell env syntax used) | Isolated API ready; Vite did not become ready within default 20-second startup deadline. Browser assertions did not run |
| Targeted repository scan | Tracked text files scanned for private-key blocks/email patterns; inspect tracked .env paths | No matches and no tracked .env. No history, image EXIF, deployed database or external-provider audit implied |

## Coverage and limits
Tests exercise trusted versus untrusted peer IPs, spoofed XFF/CF headers, invalid proxy IP fallback,
HTTPS rejection, trusted HTTPS/HSTS, absence of session cookies, security headers on errors/rate limits,
local and Redis-adapter counters, Redis outage fail-closed behavior, redaction, safe unexpected errors,
validation input removal, Host rejection, disallowed CORS, production API-doc configuration, static
deployment guards, API ownership and existing SSRF/security/content behavior.

Redis tests use an instrumented adapter; real multi-instance Redis behavior and actual edge-origin
connections need staging verification. No cookie sessions exist; there is no Secure/HttpOnly/SameSite
cookie flow to exercise. Existing bearer-token authentication/ownership regression tests pass. Browser
responsive layout, SSE/agent operation behind the new proxy, TLS certificates and origin isolation need
successful staging tests. Dependency advice is a dated snapshot, not a guarantee of vulnerability absence.

## Final dependency and review results
- `npm.cmd install --save-dev --save-exact vitest@4.1.12 --ignore-scripts --fetch-retries=0 --fetch-timeout=15000`:
  completed; changed 8 packages; installation audit found 0 vulnerabilities. Manifest and lockfile updated.
- Fresh `npm.cmd audit --audit-level=moderate`: **found 0 vulnerabilities**.
- `npm.cmd test` on Vitest 4.1.12: **4 passed**.
- Final review added Retry-After on 429, tolerant invalid proxy-proto parsing, and coverage for secure
  413 responses. Nginx caches only successful versioned asset responses; private/error responses use no-store.
- Settings errors hide validation inputs; environment variants and key material are excluded from Docker context.

- Post-upgrade TypeScript/Vite build: **passed**.
- Focused privacy rerun after final header/proxy handling changes: **9 passed**.
- Readiness error redaction test added after replacing dependency-specific health error text:
  `pytest tests/test_privacy.py::test_readiness_hides_dependency_details -q`: **1 passed**.
- Full non-browser suite was not repeated after these final small adjustments; the focused checks above
  complement the earlier 48-test run rather than constituting another complete suite run.

## Browser verification after remediation
The isolated run with ADBOT_E2E_API_PORT=8100, ADBOT_E2E_FRONTEND_PORT=5180 and
ADBOT_E2E_STARTUP_MS=60000 completed: **4 passed (28.7 seconds)**. It exercised the real local
Vite/API/database/worker/fixture flow: agent task completion; draft/privacy/publication and mobile
content rendering; dynamic title/Open Graph/canonical plus backend-failure fallback; crawl, screenshot,
SSE/job status and schedule operations. This is application-level evidence, not deployed Nginx/TLS evidence.

Earlier intermediate run: 2 passed, 2 failed. Browser diagnostics exposed missing asyncio/time imports
in existing agent code and a select locator relying on exact label text containing option text. Imports
were restored and the locator now selects the status combobox by role/name. No security assertions or
rate limits were weakened. The runner now preflights ports, supports isolated frontend/API ports, and
fails instead of silently testing an unrelated existing service.

Log redaction is installed for API, Uvicorn, workers and scheduler; routine HTTP client request logging
is suppressed and worker completion logs use a generic failure marker rather than raw error text.
- Additional Uvicorn-handler redaction and invalid proxy/HSTS configuration guard test: **1 passed**.
- Final application-wide Ruff scan (`ruff check backend/app backend/tests/test_privacy.py`): **passed**.

- Final complete non-browser rerun after agent import/logging integration: **50 passed, 28 deselected**, in 167.25 seconds.

## Follow-up oversight review
Six additional issues were corrected; see REVIEW_FINDINGS.md for severity, conditions and remediation.
Browser rerun after these changes: **4 passed (38.3 seconds)**. App-wide Ruff, whitespace and Compose
configuration checks passed. A focused quoted-secret test after the final malformed-quote adjustment
passed (1 test). Combined backend review results are appended when complete.
Combined review regression command (`pytest tests/test_privacy.py tests/test_api.py tests/test_security.py tests/test_content.py -q`): **42 passed**, one existing Starlette/httpx deprecation warning. The final malformed-quote addition was separately retested successfully after this run started. No live Nginx, Redis-cluster or external origin security claim is made.
