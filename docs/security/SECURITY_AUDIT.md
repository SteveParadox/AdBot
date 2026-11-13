# Security audit — 2026-11-13

Scope: repository and locally executable tests only. No production domain, Cloudflare account,
host firewall, registrar or deployment was accessed. Existing user changes and content CMS work
were preserved. Severity denotes potential impact in a public deployment, not proof of exploitation.

## Architecture and inventory
React 19/Vite 7 SPA; FastAPI/SQLAlchemy/Pydantic backend; Alembic; PostgreSQL/Redis in Compose;
Playwright workers and scheduler; API-key bearer authentication, per-key hashed ownership and
content administrator allowlist. Browser keys stay in sessionStorage, not cookies. Existing SSRF
policy rejects private/mixed DNS addresses and unauthorized domains through an egress proxy.
GitHub CI and Docker are present; no verified Cloudflare, DNS, registrar or hosted-platform setup.

Reviewed app routes, schemas, security/egress, worker and agent logging, frontend entry/metadata/API
client/content renderer, Docker/Nginx/Compose, ignore rules, environment example, scripts and CI.
The fixture server and test URLs are test infrastructure, not public business contact details.
No personal business identity was supplied or replaced. Public branding and required licenses remain.
No domain, email, payments, campaigns, password reset, registration, cookie sessions or analytics
integration is implemented. The workspace API key is the login credential; job/agent endpoints are
resource intensive. Dynamic public CMS content must still be reviewed by administrators for PII.

| ID | Evidence before change | Severity | Remediation / status |
|---|---|---|---|
| A1 | docker/frontend.Dockerfile ran Vite dev server; source module service publicly deployable | High | Static multi-stage production build with unprivileged Nginx |
| A2 | api_support.authenticate counted only authenticated keys | Medium | Early per-client ingress limiter, Redis atomic expiring counters; existing key limit retained |
| A3 | Backend Uvicorn default proxy handling, no app trust boundary | Medium | Disable Uvicorn proxy rewriting; explicit trusted CIDRs and single sanitized X-Real-IP/proto; ignore XFF/CF/Forwarded |
| A4 | main.py exposed /docs, /redoc, /openapi.json in production | Low | Disabled in production; Compose explicitly selects production |
| A5 | Default validation responses include rejected input; unexpected failures lack consistent safe responses | Medium | Strip validation inputs/context; generic JSON failures; no stack traces in public response |
| A6 | Request logs used raw path; no root handler credential redaction | Medium | Route templates, no query/body/header logs, credential filter; Uvicorn access logs disabled in image |
| A7 | Host validation absent; API missing CSP/permissions policy | Medium | Explicit host allowlist, restrictive API CSP, permissions policy, no-store on early failures |
| A8 | Redis had a loopback published port | Low | Remove host publication; DB/Redis/API remain internal; frontend remains loopback only |
| A9 | Nginx SPA fallback could serve index for sensitive-looking paths; source-map policy implicit | Low | Deny dotfiles/config/map extensions; explicit map opt-in with hidden maps denied by Nginx |
| A10 | HTTPS/HSTS deployment readiness unknown | Conditional risk | Opt-in API HTTPS rejection/HSTS with validation; manual TLS/edge verification required |

Dependency audit also confirmed two moderate findings in Vitest/mocker 4.1.11 (GHSA-qxg6-89mg-rqv8
and GHSA-xp26-3454-mjgp). Upgraded the pinned dependency and lockfile to 4.1.12; installation's advisory
check reported zero vulnerabilities. These were development-tool exposures, not proof of production compromise.
[Upstream patch](https://github.com/vitest-dev/vitest/releases/tag/v4.1.12).

## Existing protections retained
Parameterized ORM queries; workspace ownership checks; admin key subset authentication; bounded
JSON input; CORS explicit origins; plain-text React content; safe URL validation; screenshot ownership
and retention; SSRF controls; ignored .env/database/artifact paths; non-root backend user. No Git history
rewrite. No verified committed production secrets or personal contacts were identified by the targeted
scan; this is not a forensic secret-history audit. Source maps and built bundles need artifact checks.

## Residual risks
A trusted proxy must overwrite headers, not merely forward them. Same-network compromised containers
may impersonate an overly broad proxy CIDR. Configure the final proxy IP precisely. Defaults intentionally
trust nobody. Local fallback limits are process-local; production requires Redis. Fixed windows permit
boundary bursts and shared NAT users share ingress quota. Volumetric DDoS requires upstream protection.
TLS/certificates/firewall/Cloudflare are not deployed by these changes. CSP permits inline styles needed
by charts and HTTPS images selected by administrators; no ad/analytics scripts are currently needed.
SessionStorage keys remain accessible to any successful same-origin XSS; CSP and React escaping help
but do not eliminate that risk. Operational target URLs/evidence remain visible to their authorized owner.
Nginx still identifies itself generically; server_tokens removes its version, not the product name.
