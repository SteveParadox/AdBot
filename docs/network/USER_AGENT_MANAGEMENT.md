# User-Agent management

## Architecture and audit
Existing browser contexts selected random identities through polymorph, while a separate import-time
USER_AGENT constant was used for robots and downloads. HTTPX model clients used their library default;
proxy health checks hardcoded AdBotMonitor. These live identity decisions now use app/user_agents.py.
The old browser constant remains solely for import compatibility and is not used by live requests.
Inbound requests, Cloudflare connector traffic and internal database/Redis protocols are unaffected.
Browser automation markers X-AdBot-Automation and X-AdBot-Session remain present regardless of custom UA.

SQLAlchemy persists a singleton versioned policy document and revision-only administrator audit events.
Alembic e18a00000001 creates the two tables after the existing content migration, without rewriting
content/jobs. Constraints enforce singleton ID and nonnegative revision; schemas enforce the document,
profile IDs/values and references. Dispatch validates the selected value again. Never edit these tables
by hand. Invalid persisted configuration fails closed rather than sending an unknown malformed identity.
Missing rows use the application default. Configuration reads cache for at most five seconds per process;
a successful local save invalidates immediately. Existing contexts retain their identity until closed.

## Resolution
For a registered service, an operator-fixed identity is mandatory. Otherwise precedence is authorized
per-request override, explicit service value, enabled assigned profile, global manual value, application
default. A disabled assigned profile falls back to global/default. Rotation is an explicit service policy
using only enabled pool profiles and applies before global fallback. An empty enabled rotation pool falls
back to global/default. App-default profile is always available and protected; restore global with null.

Registered integrations: browser (including its robots checks/downloads), ai, ai_local and proxy_health.
Unknown services are rejected. No fictional payment/auth integrations were added. ai/ai_local/health
support manual or profile identity but cannot automatically rotate. Required provider identities belong
in the operator-fixed environment map and override dashboard settings and request overrides.

## Configuration
Runtime: administrators manage global value, profiles and service policies through Content > User-Agent
management or GET/POST /api/admin/user-agents. POST accepts revision, global_value, profiles, services;
GET adds diagnostics/default/operator capabilities. Saves use compare-and-swap revision checks: stale
writes return 409; reload and merge before retrying. Configuration and audit revision commit together.
GET/POST require the existing content administrator key allowlist and workspace authentication. No
public configuration or ordinary-user write endpoint exists. No auth cookies: bearer/CORS controls apply.

Environment (server only): ADBOT_USER_AGENT_DEFAULT=Adbot/1.0.0 (application version),
ADBOT_USER_AGENT_MAX_LENGTH=512 (32..2048), ADBOT_USER_AGENT_ALLOW_REQUEST_OVERRIDES=false,
ADBOT_USER_AGENT_ROTATABLE_SERVICES empty, ADBOT_USER_AGENT_FIXED_IDENTITIES={} JSON map.
Environment defines capabilities/mandatory identities; DB defines runtime choices. Restart for capability
changes, not for ordinary saved content changes. An operator default update also refreshes the protected
built-in profile at read time. Do not put credentials in UA values or frontend environment variables.

## Files and deployment
Created backend/app/user_agents.py, frontend/src/UserAgentAdmin.tsx, tests/test_user_agents.py,
frontend/e2e/user_agents.spec.ts and backend/alembic/versions/e18a00000001_user_agents.py plus five docs.
Modified db/config/main/browser, agent/controller, outbound, frontend Content, test cache fixture and
.env.example. No runtime dependency added. Run Alembic upgrade head before deploying API/workers.
Back up/export identity config before downgrade; downgrade drops only identity/audit tables. An old app
can ignore the new tables. Rolling back removes this feature, restoring its old code's identity behavior.

Limitations: no revision history restoration UI (duplicate/save profiles for reusable alternatives), audit
retention requires operator policy, rotation counters are process-local, provider requirements must be
correctly registered by the operator, and five-second cross-worker update latency is intentional.

Compatibility profiles change only the HTTP identity string, not browser engine, OS, client hints or
TLS fingerprint. Automation markers remain explicit. The private model_clients helper accepts
user_agent_override/authorized_override and forwards these to the common resolver; they are never
accepted from inbound request headers. The readiness probe also checks the new config table, preventing
a deployment without the migration from being reported ready.

Exact new files: backend/app/user_agents.py; backend/tests/test_user_agents.py;
backend/alembic/versions/e18a00000001_user_agents.py; frontend/src/UserAgentAdmin.tsx;
frontend/e2e/user_agents.spec.ts; docs/network/USER_AGENT_MANAGEMENT.md;
docs/network/USER_AGENT_PROFILES.md; docs/network/USER_AGENT_PROXY_INTEGRATION.md;
docs/security/USER_AGENT_VALIDATION.md; docs/testing/USER_AGENT_TEST_RESULTS.md.
Exact touched integration files: backend/app/config.py; backend/app/db.py; backend/app/main.py;
backend/app/browser.py; backend/app/agent/controller.py; backend/app/outbound.py;
backend/tests/conftest.py; backend/tests/test_outbound.py; frontend/src/Content.tsx; .env.example.
