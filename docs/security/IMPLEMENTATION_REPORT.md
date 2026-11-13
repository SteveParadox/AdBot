# Security implementation report

Repository changes implement privacy boundaries without changing ownership records or deploying infrastructure.
See SECURITY_AUDIT.md for verified findings versus conditional risks and SECURITY_TEST_RESULTS.md for evidence.

## Changed or created files for this task
- backend/app/privacy.py: explicit proxy boundary, forwarding removal, pre-auth IP limits, bounded local
  counters, atomic expiring Redis counters, safe unexpected failures, restrictive API headers, redaction.
- backend/app/worker.py and backend/app/scheduler.py: install shared log redaction for background processes; Uvicorn handlers also filtered.
- backend/app/agent/interaction.py and backend/app/agent/runner.py: restore missing asyncio/time imports discovered during browser regression; unused imports removed from runner/controller.
- frontend/playwright.config.ts: honor isolated test frontend base URL.
- backend/app/main.py: production API docs disabled, allowed Host validation, safe validation and readiness messages,
  route-template logging, installed redaction and outer privacy middleware.
- backend/app/config.py: explicit proxy/host/HTTPS/HSTS/rate settings and safety validation.
- backend/tests/test_privacy.py: proxy/spoofing, headers, HTTPS, rate, error, redaction, host/CORS,
  production docs and static deployment regression tests.
- docker/backend.Dockerfile: disable Uvicorn's implicit proxy processing, server header and access log.
- docker/frontend.Dockerfile: build static frontend, serve through unprivileged Nginx.
- docker/nginx.conf: header policy, deny sensitive paths/maps, sanitize proxy headers, disable raw access logs.
- docker-compose.yml: select production backend policy, remove Redis host port, keep frontend loopback
  on host 5173 mapped to internal Nginx 8080. Backend worker/scheduler/database behavior is retained.
- frontend/package.json and frontend/package-lock.json: patch Vitest to 4.1.12 to resolve the mocker advisories.
- frontend/vite.config.ts: default sourcemaps off, opt-in hidden maps for private tooling only.
- .dockerignore: exclude environment variants and key material from build context.
- scripts/e2e.mjs and frontend/e2e/content.spec.ts: configurable isolated API port/readiness timeout, relative proxied content requests and explicit Uvicorn proxy settings.
- .env.example: document new security settings, no real credentials.
- docker/security/compose.tunnel.yml, tunnel.example.yml, origin-tls.example.conf: optional templates;
  placeholders must be replaced and topology verified before use. No certificate or token is supplied.
- docs/security/{SECURITY_AUDIT,CLOUDFLARE_SETUP,DOMAIN_AND_IDENTITY_PRIVACY,
  EXTERNAL_SECURITY_CHECKLIST,IMPLEMENTATION_REPORT,SECURITY_TEST_RESULTS}.md: operator evidence and runbooks.

No database migration is needed for these security controls. The preceding content migration is unchanged.
No new runtime dependency was introduced. Existing unrelated working-tree edits were retained.

## Operator configuration
Compose now requires existing production prerequisites: PostgreSQL, Redis, authorized target domains.
Set ADBOT_ALLOWED_HOSTS to real app hostnames and ADBOT_CORS_ORIGINS to exact permitted origins. Keep
ADBOT_TRUSTED_PROXY_CIDRS empty for direct connections; behind Nginx set its precise source IP/CIDR.
Do not trust the entire Docker network unnecessarily; use an operator-managed dedicated network/static
proxy address. All custom Uvicorn launches must include --no-proxy-headers. Do not enable a second
framework proxy parser before the application policy. The checked-in image does this explicitly.

Base Nginx accepts HTTP only on a loopback-published port, and sets the API scheme from its own socket.
It is not an externally complete TLS deployment. Configure a verified TLS listener or dedicated
connector-only ingress using the template before enabling enforcement. Do not blindly pass external
X-Forwarded-Proto. CF-Connecting-IP is never accepted directly by the app; validate Cloudflare at the
edge and translate it to X-Real-IP there. With no translation, ingress limits conservatively aggregate
at the final proxy address. Keep key-based owner limits as the additional authenticated boundary.

Authentication uses explicit bearer headers and sessionStorage, with no auth/session cookies to mark
Secure/HttpOnly/SameSite. CSRF cookie-session mitigations are therefore not applied to a nonexistent
cookie flow. Any future cookie login needs explicit CSRF tokens and Secure/HttpOnly/SameSite policy.
Public CMS text remains administrator-controlled and React-escaped; no upload service, advertising,
analytics or payment integration was added or silently disabled. External integrations require staging
verification if operators add them. Development API docs retain a narrowly scoped compatible CSP;
production docs remain absent. HSTS is opt-in and validated against HTTPS enforcement.

## Release gate
Do not call this production-verified until Docker/Nginx configuration, current dependency advisories,
real host/proxy addresses, TLS, direct-origin rejection and browser journeys pass in staging. Neither
Cloudflare protection nor origin IP privacy can be established by repository tests alone.

## Exact task file inventory

- `.dockerignore`
- `.env.example`
- `backend/app/privacy.py`
- `backend/app/main.py`
- `backend/app/config.py`
- `backend/app/worker.py`
- `backend/app/scheduler.py`
- `backend/app/agent/interaction.py`
- `backend/app/agent/runner.py`
- `backend/app/agent/controller.py`
- `backend/tests/test_privacy.py`
- `docker/backend.Dockerfile`
- `docker/frontend.Dockerfile`
- `docker/nginx.conf`
- `docker-compose.yml`
- `docker/security/compose.tunnel.yml`
- `docker/security/tunnel.example.yml`
- `docker/security/origin-tls.example.conf`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/playwright.config.ts`
- `frontend/e2e/content.spec.ts`
- `scripts/e2e.mjs`
- `docs/security/SECURITY_AUDIT.md`
- `docs/security/CLOUDFLARE_SETUP.md`
- `docs/security/DOMAIN_AND_IDENTITY_PRIVACY.md`
- `docs/security/EXTERNAL_SECURITY_CHECKLIST.md`
- `docs/security/IMPLEMENTATION_REPORT.md`
- `docs/security/SECURITY_TEST_RESULTS.md`
