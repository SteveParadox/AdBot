# Network services audit and architecture

The existing browser egress proxy already enforced target/domain/DNS rules, pinned IP sockets and
blocked unauthorized mutations. Browser robots and downloads reuse that local proxy. Model HTTP
requests previously used a separate direct HTTPX client. API/worker also connect internally to the
configured database and Redis; these are infrastructure connections, not rotated Internet traffic.
Existing ingress security is retained: no public DB/Redis/API ports, loopback frontend host binding,
explicit proxy trust, header sanitization, admin authorization, private errors and no-store APIs.

`app/outbound.py` is the shared routing manager. Browser/robots/download connections reach it through
`egress_proxy`; model providers use per-provider pooled HTTPX clients through the same local guard when protection is enabled. Disabled protection preserves their original native HTTPX route.
No environment HTTP_PROXY/NO_PROXY bypass is used. Server-only JSON defines approved endpoint IDs
and service policies: browser, ai, ai_local. There is no API for visitors or workspace users to supply
proxy endpoints or modify configuration. Content administrators can view redacted diagnostics only.

## Connection flow
1. Validate target against the website policy or the exact server-configured provider origin.
2. Resolve DNS locally and reject any non-global address for public destinations; approved local model
   services are an explicit exception and must use an explicitly direct ai_local policy when enabled.
3. Connect directly only if protection is disabled or the service explicitly selects direct mode.
4. Otherwise CONNECT a validated destination **IP** through the selected approved HTTP/HTTPS proxy.
   Proxy credentials are carried only on this outer connection. HTTPS proxy TLS uses the system trust
   store and hostname validation. Destination TLS/SNI/certificate verification remains in HTTPX/browser.
5. Stream the original request through the tunnel. Plain HTTP uses CONNECT to port 80 too: providers
   must permit this. Redirects in browser/robots/download flows are rechecked; model redirects are off.

HTTP/HTTPS proxies support Basic authentication. Credentials over plain HTTP are rejected unless an
operator explicitly accepts `allow_plaintext_auth=true` for an approved private path. HTTPS is preferred.
SOCKS is deliberately rejected: existing dependencies do not supply a verified remote-DNS SOCKS chain.
No new runtime dependencies were added. DNS goes to the host's resolver; this implementation does not
claim remote DNS privacy. Pinning prevents an upstream re-resolution from turning a public hostname
into metadata/private-IP access. Approved upstream providers must honor CONNECT IPs as requested.

## Policies and selection
Protection/rotation are off by default. When enabled, an absent service policy fails closed. Required
services never fall back to direct connections. Stable services require exactly one endpoint, no
rotation and no cross-IP failover, preserving allowlisted/provider/authenticated continuity across
workers and restarts. Sticky sessions remain attached to a route until released. Other strategies require
`stable=false, allow_rotation=true`. Optional connect failover also requires `allow_failover=true`.
No HTTP 429, denial, account restriction or destination response triggers IP changes/retries. Connection
retries happen before the target request is sent; mutations are not replayed by the routing manager.
Counters, circuits and scheduling are process-local; production diagnostic heartbeats use Redis but
selection is not globally coordinated. Scheduled strategies are per-process monotonic intervals.

## Health and failover
Connections record success/failure counts, consecutive failures, timeout counts, latency and last success.
Failures open a circuit with bounded exponential backoff/jitter. A periodic HEAD check to each operator-
approved HTTPS health URL validates the proxy tunnel and destination TLS before resetting the circuit.
Unhealthy endpoints are ineligible until cooldown; monitor probes recover them. Stable routes block
rather than silently change. Session state is bounded and released with local proxy contexts.

The API and worker start monitors and publish expiring, redacted process snapshots to Redis when
configured. GET /api/admin/network and the Content administrator dashboard show endpoint IDs, policies,
counts, latency, last success, cooldown state and failover counters; hosts, URLs, credentials and keys are
omitted. Without Redis diagnostics explicitly cover the API process only. Heartbeat records may lag by
one interval and expire after three intervals. Endpoint IDs should be descriptive but non-sensitive.
Configuration is startup-validated with sanitized errors, not hot-reloaded. Restart processes after changes.

## Limitations and release gates
An external firewall is required to prevent a compromised process, browser bug, native extension or new
uncentralized client from opening a raw socket. Restrict outbound web sockets to approved proxy hosts;
permit only required DNS, database, Redis, Tunnel transport and explicitly direct local integrations.
A trusted proxy can observe HTTP and destination IPs; HTTPS hides application payloads but requires
trust in that operator's routing behavior. Health probes cannot prove the provider's public exit IP.
Stable services should use provider-side static exit allocations; one proxy endpoint can itself rotate
IPs upstream. Verify and contractually disable that behavior for sessions and fixed-IP services.


## Task file inventory
Created: backend/app/outbound.py; backend/app/network_api.py; backend/tests/test_outbound.py;
frontend/src/NetworkStatus.tsx; docker/security/compose.outbound.yml;
docker/security/outbound-proxies.example.json; docker/security/tunnel-ingress.conf; and the six network
security documents (IP_ADDRESS_PROTECTION.md, CLOUDFLARE_TUNNEL.md, OUTBOUND_PROXY_ARCHITECTURE.md,
IP_ROTATION_CONFIGURATION.md, EXTERNAL_NETWORK_REQUIREMENTS.md, NETWORK_SECURITY_TESTS.md).
Modified: .env.example; backend/app/config.py; backend/app/egress.py; backend/app/browser.py;
backend/app/agent/model.py; backend/app/main.py; backend/app/worker.py; backend/app/privacy.py;
frontend/src/Content.tsx; docker/security/compose.tunnel.yml; docker/security/tunnel.example.yml.
No schema migration, new runtime dependency, public write API, provider account modification or
production deployment is required/performed by these source changes. Failover metrics count authorized
connect failover attempts, with separate redacted log events; they do not count successful IP changes.
