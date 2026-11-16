# AdBot Monitor

AdBot is a workspace for **authorized website monitoring and browser automation**: crawls, workflows,
schedules, AI-assisted research, screenshots and live execution events. Administrators also manage public
content, outbound proxy routing and User-Agent identities. It does not generate artificial advertising
engagement or authorize bypassing destination access controls, quotas or service policies.

## Architecture

| Component | Responsibility |
|---|---|
| React/TypeScript/Vite dashboard | Workspace operations and administrator forms |
| FastAPI/Pydantic API | Authentication, ownership, validation, jobs and administration |
| SQLAlchemy/Alembic | Durable SQL data and versioned migrations |
| Playwright worker | Isolated browser execution, downloads, captures and results |
| Scheduler | Enqueues due recurring/one-off jobs; does not execute them itself |
| PostgreSQL/Redis | Required production database, queue coordination, distributed limits/diagnostics |
| Local egress guard | Validates destination/domain/DNS and pins destination IPs |
| Optional approved upstream proxies | Explicit service routing, health, circuits and permitted failover |
| Unprivileged Nginx | Production static frontend and sanitized API forwarding |
| Optional Cloudflare Tunnel | Authenticated inbound connector, separate from outbound routing |

The API persists work; workers claim leases, operate browsers, and persist events/results; the dashboard
retrieves those records and streams job progress. SQLite is supported for local development. AI is optional.

## 1. Local installation

Install Python 3.12+, Node.js 22.12+ or a compatible newer release, npm and Git. Install Playwright browser
binaries and required OS libraries. Docker is optional locally; Docker Desktop must use Linux containers.

### Windows Command Prompt

```bat
git clone https://github.com/SteveParadox/AdBot.git
cd AdBot
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python.exe -m playwright install chromium firefox webkit
.venv\Scripts\python.exe scripts\init_env.py
cd frontend
npm ci
cd ..\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-server-header --no-access-log
```

Keep the API terminal open. In three separate terminals, initially at the repository root:

```bat
cd backend
..\.venv\Scripts\python.exe -m app.worker
```

```bat
cd backend
..\.venv\Scripts\python.exe -m app.scheduler
```

```bat
cd frontend
npm run dev
```

PowerShell can use explicit Python executable paths without activating the virtual environment. Use
`npm.cmd` if your shell blocks `npm.ps1`; no execution-policy change is necessary.

### Linux/macOS

```sh
git clone https://github.com/SteveParadox/AdBot.git
cd AdBot
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m playwright install --with-deps chromium firefox webkit
.venv/bin/python scripts/init_env.py
(cd frontend && npm ci)
cd backend
../.venv/bin/python -m alembic upgrade head
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-server-header --no-access-log
```

On macOS omit `--with-deps` if unavailable. Linux browser library installation can require package-manager
permissions. Start worker/scheduler separately from backend using the virtualenv Python, and run
`npm run dev` from frontend. Backend commands must run from **backend/** because settings read `../.env`.

### Private configuration and login

`init_env.py` generates a private root `.env` with API/database/session keys and refuses to overwrite an
existing file. Existing installations must merge new settings from `.env.example` while preserving secrets.
Never commit real environment files, proxy credentials, private keys, tunnel tokens or backups.

Local development defaults:

```dotenv
ADBOT_ENVIRONMENT=development
ADBOT_DATABASE_URL=sqlite:///./adbot.db
ADBOT_REDIS_URL=
ADBOT_AI_PROVIDER=disabled
ADBOT_FIXTURE_MODE=false
ADBOT_ALLOWED_HOSTS=localhost,127.0.0.1
ADBOT_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

Open **http://127.0.0.1:5173**. Enter the generated `ADBOT_API_KEYS` value, not its variable name. Multiple
keys are comma-separated, each at least 32 characters. Keys identify separate workspace owners. The browser
keeps its key in sessionStorage and sends bearer authentication; there is no cookie/password login flow.

For administration, add an authorized API key to `ADBOT_CONTENT_ADMIN_KEYS` and restart the API. Locally
the same key can have both roles; production should provision separate ordinary/admin credentials.
Global administration does not grant access to other keys' private jobs. This is not organization RBAC.
SQLite data is `backend/adbot.db`; artifacts are under `backend/data/screenshots/` by default.

Vite proxies `/api` to port 8000. If the API uses another port, set `ADBOT_API_PROXY_TARGET` in Vite's
process environment before startup. Environment secrets are server-side, not public frontend settings.

## 2. First end-to-end job

1. Connect with a workspace key. Open **Websites** and add a target you are authorized to automate.
2. Set starting URL, explicit allowed hosts, limits and delays. Include approved CDN/resource hosts.
   `example.com` permits the exact host; `*.example.com` explicitly permits its subdomains.
3. Confirm authorization, keep robots compliance enabled and enable captures/scrolling if needed.
4. Open **Jobs**, select the website and launch a crawl. A running worker must claim the persisted job.
5. Inspect status/events, page visits, HTTP results and screenshots. Queued work does not imply execution.
6. Build a permitted **Workflow** or create a **Schedule** with the correct timezone. Run the scheduler
   separately. Pause/resume occurs at safe boundaries; elapsed session deadlines continue while paused.
7. Inspect partial results before retrying operations with side effects.

Production additionally requires `ADBOT_AUTHORIZED_DOMAINS`, an operator-controlled target boundary.
Unapproved domains, private/mixed DNS results, protocols and ports are rejected. Ordinary crawls are
read-only; AI permissions/reviews are separate and do not grant unrestricted forms/downloads/sockets.

For a controlled fixture set `ADBOT_FIXTURE_MODE=true`, restart API/worker, then start
`python -m uvicorn app.fixture:app --host 127.0.0.1 --port 8765` using the virtualenv from backend.
Register `http://127.0.0.1:8765/` with allowed domain `127.0.0.1`. Only that configured fixture exemption
is allowed; arbitrary private networks remain blocked. Fixture mode is forbidden in production.

## 3. Optional AI setup

Crawls work with AI disabled. For goal-driven browsing configure an approved provider/model on the server:

- `groq`: uses `ADBOT_GROQ_BASE_URL`, `ADBOT_GROQ_API_KEY`, `ADBOT_AI_MODEL`.
- `openai_compatible` or `local`: uses `ADBOT_AI_BASE_URL`, `ADBOT_AI_API_KEY`, `ADBOT_AI_MODEL`.
- Remote providers require HTTPS. Obtain valid model identifiers and scoped credentials from your provider.
- Groq can explicitly fall back to a local model using the `ADBOT_AI_FALLBACK_*` settings. With outbound
  protection enabled, approve its `ai_local` direct policy; remote proxies cannot treat loopback as local.
- Configure step/token/time/concurrency budgets. Provider requests may incur charges. Visual reasoning and
  encrypted browser-session persistence require separate opt-ins; preserve the session encryption key.

Restart API and worker for environment/provider changes. Use **AI Agent** to submit an objective, review
permissions/actions, observe captures and inspect verified/cited results. See [agent guide](docs/AGENT_GUIDE.md),
[interaction engine](docs/INTERACTION_ENGINE.md) and [agent limitations](docs/AGENT_VERIFICATION.md).

## 4. Content administration

Connect as an administrator and open **Content**. Select a section or choose **New section**, edit text
and safe image/link URLs, inspect the preview and save:

- **draft:** preserves the previous public publication while saving edits.
- **published:** replaces the public snapshot atomically.
- **archived:** hides the section. Delete removes it; order controls custom section placement.

Reserved keys control login, page headings/descriptions and `seo`; custom promotional sections appear on
the login page. `navigation_label` is independent of the page headline. Images use local/HTTPS URLs;
there is no upload library. Text is escaped; unsafe preview/public URLs are rejected.

Public content refreshes every 30 seconds, with immediate editor-browser invalidation after writes.
Errors retain cached content or original copy and offer retry. Title/description/canonical/Open Graph
metadata is client-rendered, not SSR. Content saves and deletes require the loaded revision; stale edits are rejected and the editor preserves your draft for comparison/merge.
See [dynamic content](docs/DYNAMIC_CONTENT.md).

## 5. User-Agent administration

Under **Content > User-Agent management**, edit the global string, create/edit/duplicate profiles, assign
service overrides, enable/disable saved overrides, preview and save. Referenced profiles cannot be deleted
until unassigned; the application-default profile is protected. A stale configuration returns 409: reload,
merge changes and save. Configuration and revision-only audit records commit together.

Custom strings are not limited to a browser whitelist. Values must be nonempty printable ASCII, without
leading/trailing whitespace or controls, within the operator's maximum length; no silent rewriting occurs.
Operator-required service identity takes precedence. Otherwise: authorized internal request override,
service custom value, enabled profile, global value, application default. Disabled settings fall back safely.

```dotenv
ADBOT_USER_AGENT_DEFAULT=Adbot/1.0.0
ADBOT_USER_AGENT_MAX_LENGTH=512
ADBOT_USER_AGENT_ALLOW_REQUEST_OVERRIDES=false
ADBOT_USER_AGENT_ROTATABLE_SERVICES=
ADBOT_USER_AGENT_FIXED_IDENTITIES={}
```

API and worker revision watchers normally apply committed changes within one second, with a five-second
read-cache fallback and bounded backoff during outages. Active browser contexts retain one
identity for browsing, robots rules and downloads; model retries/failover preserve their selected header.
Automatic browser-only round-robin/random/weighted/sticky/compatibility/scheduled/endpoint-coordinated pools require explicit operator
permission and compatible proxy policy. Coordination happens only when a NEW context chooses its route,
not during retries or a stable authenticated session. A UA string does not change the browser engine or
TLS fingerprint; automation markers remain present. Do not put credentials in these outbound headers.

Details: [management/file inventory](docs/network/USER_AGENT_MANAGEMENT.md), [profiles](docs/network/USER_AGENT_PROFILES.md),
[proxy coordination](docs/network/USER_AGENT_PROXY_INTEGRATION.md), [validation](docs/security/USER_AGENT_VALIDATION.md).

## 6. Outbound proxy routing

Protection and rotation are off by default. Enabling them requires approved operator-owned configuration.
Required proxy services **never silently fall back direct**. Stable services use one endpoint without
cross-IP failover; the provider must also guarantee a fixed exit allocation, not hidden upstream rotation.

1. Copy `docker/security/outbound-proxies.example.json` outside this repository.
2. Replace placeholders with approved HTTP(S) endpoints, credentials and an HTTPS health URL you own or
   may probe. Restrict file ACLs while allowing the actual API/worker container user to read it.
3. Assign existing browser/ai/ai_local service policies, including explicit local-model direct approval.
4. For native processes set the private path and validate without network calls:

```dotenv
ADBOT_OUTBOUND_PROXY_ENABLED=true
ADBOT_OUTBOUND_PROXY_CONFIG_PATH=/absolute/private/outbound-proxies.json
```

```sh
# From backend using the virtualenv Python:
../.venv/bin/python -m app.outbound --check
```

5. Restart API/workers and inspect **Content > Network routing**. Verify actual exit addresses with
   controlled target/provider records. Redis aggregates expiring per-process heartbeats; without Redis
   the dashboard explicitly reports only the API process.

HTTP/HTTPS CONNECT is supported, with verified TLS and separate proxy authentication. HTTPS is preferred
for authenticated proxy transport. SOCKS/remote DNS are not implemented: local DNS validates and pins
public destination IPs. Selection supports round-robin/random/weighted/sticky/fixed/health/latency/scheduled strategies under
explicit service permissions. Circuits, backoff and bounded connect failover do not replay target
mutations or rotate because of a target denial/429. Host firewalls are still needed to constrain arbitrary
sockets under process compromise; application routing is not a network-layer anonymity guarantee.

For Docker set private host `ADBOT_OUTBOUND_PROXY_CONFIG_FILE` and use the overlay on all operations:

```sh
docker compose -f docker-compose.yml -f docker/security/compose.outbound.yml config --quiet
docker compose -f docker-compose.yml -f docker/security/compose.outbound.yml up -d --build
```

Read [proxy architecture](docs/security/OUTBOUND_PROXY_ARCHITECTURE.md), [rotation](docs/security/IP_ROTATION_CONFIGURATION.md)
and [external network requirements](docs/security/EXTERNAL_NETWORK_REQUIREMENTS.md).

## 7. Docker deployment

Generate `.env` only if absent; merge example additions otherwise. Set nonempty
`ADBOT_AUTHORIZED_DOMAINS` to actual approved target hosts before starting. Compose always selects
**production mode**, PostgreSQL/Redis and fixture mode off, regardless of local development settings.
Set actual public allowed hostnames/CORS origins for the eventual ingress; retain localhost as needed
for local evaluation. Docker Desktop must run Linux containers.

```sh
python scripts/init_env.py
# Edit private .env before proceeding; skip generation when it already exists.
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail 100 api worker scheduler
```

Open **http://127.0.0.1:5173**: host 5173 maps to Nginx's internal 8080. Only the frontend is host-published,
bound to loopback. API/database/Redis remain internal; migrations run before application startup. SQL,
Redis and artifacts use persistent named volumes. Browser images are large; load-test worker memory,
shared memory and concurrency against your pages before raising limits.

The base stack is an HTTP loopback origin, not a complete public TLS deployment. Add a verified TLS edge
or Tunnel before public use. Production docs/OpenAPI are disabled; Nginx serves built assets, blocks
sensitive/map paths and caches only successful versioned assets. Do not host public Vite dev servers.

## 8. Cloudflare Tunnel and origin protection

Follow [Tunnel deployment/recovery](docs/security/CLOUDFLARE_TUNNEL.md) and
[Cloudflare setup](docs/security/CLOUDFLARE_SETUP.md) before enabling the optional overlay.
Required private operator values:

- `ADBOT_CLOUDFLARED_IMAGE`: reviewed image pinned by digest.
- `ADBOT_TUNNEL_CONFIG_PATH`: absolute host path to the populated private YAML.
- `ADBOT_TUNNEL_CREDENTIALS_PATH`: absolute host path to named-tunnel credential JSON.

Route the actual hostname to `http://frontend:8081` with a final 404 catch-all. Verify example subnet
availability first; changing addresses requires updating every coupled trust/geo/static peer setting.
The dedicated listener checks its connector socket peer and Cloudflare visitor HTTPS metadata. A separate
internal network carries sanitized client identity to the exact trusted frontend/API hop.

```sh
docker compose -f docker-compose.yml -f docker/security/compose.tunnel.yml config --quiet
docker compose -f docker-compose.yml -f docker/security/compose.tunnel.yml up -d --build
```

Include both Tunnel and outbound overlay files when combining them, and keep the same flags for later
operations. Tunnel enables API HTTPS enforcement: verify edge HTTPS and a recovery console before
rollout. HSTS remains opt-in. Connector metrics port 2000 `/ready` is internal; do not publish it publicly.
No public inbound origin web listener is needed, but closing actual firewall ports is an operator task.

For direct Cloudflare origins use reviewed IPv4/IPv6 allowlists and authenticated TLS origin pulls.
DNS, certificates, account credentials, firewall policy and provider exit IPs were not changed by source
code. See [origin protection](docs/security/IP_ADDRESS_PROTECTION.md) and
[external security checklist](docs/security/EXTERNAL_SECURITY_CHECKLIST.md).

## 9. Security configuration

| Setting/control | Purpose |
|---|---|
| `ADBOT_API_KEYS` | Private workspace bearer credentials |
| `ADBOT_CONTENT_ADMIN_KEYS` | Valid keys authorized for global administration |
| `ADBOT_AUTHORIZED_DOMAINS` | Production destination authorization, not incoming host validation |
| `ADBOT_ALLOWED_HOSTS` | Allowed incoming Host values; configure the actual hostname |
| `ADBOT_CORS_ORIGINS` | Exact permitted browser origins; not an authentication substitute |
| `ADBOT_TRUSTED_PROXY_CIDRS` | Exact sanitizing proxy peers; empty trusts none; never all-address ranges |
| `ADBOT_ENFORCE_HTTPS` | Reject ordinary insecure API traffic after trusted scheme normalization |
| `ADBOT_HSTS_ENABLED` | Enable only after verified HTTPS; browsers retain it across rollback |
| `ADBOT_PUBLIC_RATE_PER_MINUTE` | Early per-client rate limit, including invalid credentials |
| `ADBOT_RATE_PER_MINUTE` | Additional authenticated-key limit |
| `ADBOT_BUILD_SOURCEMAPS` | Default off; optional hidden maps stay denied by production Nginx |

Retain `--no-proxy-headers` on custom Uvicorn launches: the app owns trust normalization. Without an
accurate proxy-peer configuration, users behind it share an ingress quota. Never trust arbitrary XFF/CF
headers, disable TLS verification or remove limits to hide a topology error. Logs mask known credentials
and avoid raw paths/query/body logging, but operators must not log arbitrary sensitive payloads.
Read the [audit](docs/security/SECURITY_AUDIT.md), [implementation review](docs/security/COMPREHENSIVE_REVIEW.md)
and [domain/identity privacy guidance](docs/security/DOMAIN_AND_IDENTITY_PRIVACY.md).

## 10. Testing and recorded verification

From **backend/** using your platform's virtualenv Python:

```sh
../.venv/bin/python -m pytest -q -m 'not browser'
../.venv/bin/python -m pytest tests/test_user_agents.py tests/test_outbound.py -q
../.venv/bin/python -m pytest -q -m browser
../.venv/bin/python -m ruff check app tests
```

Windows substitutes `..\.venv\Scripts\python.exe`. Browser-marked tests require installed Chromium.
Tests use temporary databases; never point test database overrides at production. From **frontend/**:

```sh
npm test
npm run build
npm run test:e2e
```

The E2E runner starts isolated fixture/model/API/worker/scheduler/Vite services, uses a temporary database
and cleans up its processes. Default ports 8000, 5173, 8765 and 8766 must be free. It refuses occupied
ports rather than silently testing another application. PowerShell overrides for a running local stack:

```powershell
$env:ADBOT_E2E_API_PORT = '8100'
$env:ADBOT_E2E_FRONTEND_PORT = '5180'
$env:ADBOT_E2E_STARTUP_MS = '60000'
npm.cmd run test:e2e
```

Fixture ports 8765/8766 remain fixed. Local simulated model fixtures are not live-provider certification.
Recorded implementation checks include **86 non-browser backend tests**, **27 focused UA/proxy tests**,
**5 browser journeys**, **5 frontend unit tests**, migration upgrade/downgrade/reapply, build and lint
passing. Later small additions have focused results rather than a claim of another full-suite run.
Exact commands, timing and limits: [UA evidence](docs/testing/USER_AGENT_TEST_RESULTS.md),
[network evidence](docs/security/NETWORK_SECURITY_TESTS.md), [review evidence](docs/security/COMPREHENSIVE_REVIEW.md).
Local results do not establish production readiness or absence of every vulnerability.

## 11. Operations, backups and recovery

Before migrations back up SQL data, artifacts and required private configuration/encryption keys. Use
PostgreSQL-consistent tooling in production. For SQLite stop writers or use its backup API; do not copy
a live main file while ignoring its WAL state. Restore into an isolated environment and verify both job
history and encrypted-session access. Protect backups with appropriate access, encryption and retention.

Deploy reviewed images and matching migrations, then roll API/workers/scheduler forward together.
`alembic current` and `alembic history` inspect state. Readiness checks the UA table as well as existing
schema/dependencies. Export feature configuration and review destructive downgrade operations before
rollback; prefer a known compatible release/configuration when possible.

Compose shutdown preserves volumes by default; using its volume-removal option deletes stored data.
Use the same overlay flags as startup. Pin/review production image digests and dependency updates.
Keep console/VPN access during TLS, DNS, firewall and subnet changes; verify rollback before enforcing
restrictions. No blanket firewall script is deployed by this repository.

| Symptom | What to check |
|---|---|
| `.env already exists` | Expected protection: merge missing example settings, do not overwrite real secrets |
| 401 | Correct generated key, current process environment, minimum length and bearer authentication |
| Administrator 403 | Key must be valid in API_KEYS and listed in CONTENT_ADMIN_KEYS; restart API |
| Invalid Host / 400 | Real incoming hostname must be allowed; do not replace trust with a global wildcard |
| HTTPS required / 426 | Actual TLS/edge scheme, connector metadata and exact trusted peer; base HTTP is not Tunnel |
| Readiness 503 | Database/Redis availability and completed migrations, including UA tables |
| Jobs stay queued | Running worker, matching database, capacity and leases; scheduler alone cannot run jobs |
| Schedule does not fire | Scheduler process, enabled state, timezone and next-run time |
| Target rejected | Website/operator allowlists, public DNS policy, subresource hosts and supported ports |
| AI unavailable | Provider/model/key, step/token/time budget and explicit proxy/local-fallback policy |
| Proxy unavailable | CA/TLS, credentials, CONNECT IP/port support, approved health URL, cooldown and fixed-route policy |
| UA save 409 | Reload revision, reconcile edits and save; do not blindly overwrite another admin |
| UA save 422 | ASCII/control/length rules, profile references, permission and stable-route restrictions |
| UA update not visible | New context required; revision watcher/five-second fallback; mandatory identity takes precedence |
| Uvicorn access log unpack error | Restart API with the redaction fix; its formatter must retain all five structured fields |
| Frontend API failure | Vite proxy target/port, API process, Host/CORS configuration or production Nginx routing |
| Browser tests fail early | Port conflicts, browser binaries, resource limits and actual runner diagnostics |
| Docker build/pull fails | Registry/DNS/proxy access, image availability and disk; no runtime-success claim until fixed |

## 12. Automation Control Center

The **Automation** tab combines live queue outcomes, worker/scheduler heartbeats, browser session leases,
network health, User-Agent management, alerts, recent owned jobs and approved policy history. It requires
the existing administrator key role. Global controls affect all workspaces; individual job actions stay
within the caller's workspace.

Existing queue/worker/scheduler services now coordinate priority, one-parent dependencies, bounded queue
admission, runtime concurrency/recovery limits, manual release, pause/resume and emergency cancellation.
User-Agent and proxy round robin use atomic SQL counters; proxy cooldowns and browser identity assignments
survive process restarts. Authenticated/persisted sessions fail closed on route loss. Fixed identities,
stable egress, authorization, SSRF checks, TLS and action-review requirements remain enforced.

Run `python -m alembic upgrade head` before deploying matching API/workers/scheduler. New migration
`a20d00000001` follows `f19c00000001`; take a consistent backup first. Ordinary runtime policy changes use
revision CAS and require no restart. Operator security environment changes still require deployment.

- [Architecture and file report](docs/automation/AUTOMATION_ARCHITECTURE.md)
- [Automation coverage matrix](docs/automation/AUTOMATION_COVERAGE_MATRIX.md)
- [Administrator controls](docs/automation/ADMIN_CONTROLS.md)
- [Workflow scheduling and dependencies](docs/automation/WORKFLOW_ORCHESTRATION.md)
- [User-Agent automation](docs/automation/USER_AGENT_AUTOMATION.md), [proxy automation](docs/automation/PROXY_ROTATION_AUTOMATION.md)
- [Network identity coordination](docs/automation/NETWORK_IDENTITY_COORDINATION.md)
- [Recovery and retention](docs/automation/SELF_RECOVERY.md), [deployment and restore](docs/automation/DEPLOYMENT.md)
- [Current verification results](docs/automation/TEST_RESULTS.md), [implementation report](docs/automation/IMPLEMENTATION_REPORT.md)

## Documentation and deployment limits

- [API reference](docs/API.md), [durable architecture](docs/ARCHITECTURE.md)
- [Agent setup](docs/AGENT_GUIDE.md), [interaction engine](docs/INTERACTION_ENGINE.md)
- [Dynamic content](docs/DYNAMIC_CONTENT.md)
- [UA architecture/file inventory](docs/network/USER_AGENT_MANAGEMENT.md), [profiles](docs/network/USER_AGENT_PROFILES.md)
- [UA/proxy integration](docs/network/USER_AGENT_PROXY_INTEGRATION.md), [validation](docs/security/USER_AGENT_VALIDATION.md)
- [Proxy architecture](docs/security/OUTBOUND_PROXY_ARCHITECTURE.md), [rotation](docs/security/IP_ROTATION_CONFIGURATION.md)
- [Tunnel](docs/security/CLOUDFLARE_TUNNEL.md), [Cloudflare](docs/security/CLOUDFLARE_SETUP.md)
- [External network requirements](docs/security/EXTERNAL_NETWORK_REQUIREMENTS.md)
- [Full review](docs/security/COMPREHENSIVE_REVIEW.md), [security audit](docs/security/SECURITY_AUDIT.md)

Still requiring deployment verification: real PostgreSQL/Redis multi-process behavior, Nginx runtime and
CSP/TLS, Cloudflare/DNS/direct-origin rejection, proxy exit allocation, host egress ACLs, load/capacity,
selected browser engines and backup restoration. SOCKS/remote DNS are unsupported and metadata is client-rendered. Shared SQL counters and cooldowns require database availability and synchronized host clocks. Arbitrary OS sockets
under compromise are not intercepted. No anonymity guarantee is made. Truthful lawful business
information, legitimate ownership records and dependency attribution must remain intact.
