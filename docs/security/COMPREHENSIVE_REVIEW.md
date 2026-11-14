# Comprehensive implementation review — 2026-11-14

Scope: content models/migration/API and React renderer/editor; auth/authorization and rate limits;
proxy trust, safe errors/logs and headers; forward-proxy framing, DNS/SSRF pinning and upstream routing;
health/circuit monitoring, diagnostics and lifecycle; Docker/Nginx/Tunnel topology and configuration.
This supplements SECURITY_AUDIT.md and REVIEW_FINDINGS.md, rather than replacing earlier evidence.
No production infrastructure, provider account, Git history or live business identity was modified.

## Confirmed issues fixed

| Severity / condition | Finding | Remediation and evidence |
|---|---|---|
| High, when Python optimization is enabled | Endpoint security checks used assert, removed by python -O | Explicit validation; subprocess regression runs optimized Python and verifies unsafe proxy config is rejected |
| Medium | GET/HEAD bodies and malformed headers could produce ambiguous forwarded HTTP framing; connection-nominated headers were forwarded | Reject body-bearing read-only requests, invalid header names/control characters, non-CONNECT HTTPS and malformed authorities/versions; remove hop-by-hop/nominated headers; real local TCP tests verify no prohibited request reaches target |
| Medium | Closing/cancelling established CONNECT streams could inject a second HTTP error into the TLS byte stream | Track response establishment; cancellation closes cleanly; pre-establishment policy rejection is 403, network failure 502; controlled tunnel shutdown test verifies clean EOF |
| Medium | An older in-flight connection/probe success could erase a newer circuit failure | Track failure timestamp and clear circuit only for a sufficiently recent successful attempt; deterministic race regression |
| Medium reliability | Serial slow probes delayed heartbeat publication beyond diagnostic TTL | Independent heartbeat task, bounded parallel probes and joined cancellation; blocked-probe/Redis adapter test verifies publication and cleanup |
| Medium, edge HTTPS misconfiguration | Tunnel ingress unconditionally stamped HTTPS after connector authentication | Also require trusted connector CF-Visitor scheme=https; other edge schemes receive 426. Static configuration review only; Nginx/live Cloudflare test remains pending |
| Low / accidental content disclosure | New section flow retained previous draft data | Dedicated reset action clears draft/key/status/order; browser regression tests reset and reload saved draft |
| Low UX | Page heading was used as navigation label, making Overview display a full headline | Independent navigation_label content field with original route-name fallback; navigation browser regression |
| Low / unsafe draft input | Draft preview rendered URLs before API validation | Preview rejects unsupported schemes, credentials, protocol-relative URLs and whitespace/backslashes; frontend unit test |

Textarea labels are now explicitly named so populated editor fields retain predictable automation and
accessible lookup behavior. A browser retry exposed this issue after the new reset/reload assertions.
Proxy credential masking, source IP/DNS validation, public published-snapshot isolation, admin boundaries,
rate limiting, production doc suppression and earlier security controls remain in force.

## Tests and actual limitations
- Initial combined content/privacy/outbound/review selection: **36 passed**.
- Full non-browser suite: **71 passed, 28 deselected**, one existing Starlette/httpx deprecation warning.
- New forward-proxy/circuit/optimized-validation/shutdown focused checks: **4 passed**.
- Frontend TypeScript/Vite build: **passed**; frontend unit tests: **5 passed**.
- First browser run: **2 passed, 2 failed** (agent click timeout on the slow host; editor populated-textarea
  exact-label lookup). The editor now has explicit aria-label values; final retry results recorded below.
- Ruff and whitespace checks passed. Final heartbeat/circuit focused run is recorded below.
- Nginx image pull exceeded a bounded 45-second deadline. No Nginx parser/runtime, live HTTPS/origin,
  Cloudflare identity/header behavior or host firewall success is claimed by these source changes.

Residual limitations requiring operational/product decisions: CMS writes remain last-write-wins between
authorized simultaneous editors (no revision history/conflict UI); metadata is client-rendered; application
routing cannot prevent arbitrary sockets from a compromised process; proxy providers must guarantee fixed
exit allocations; SOCKS/remote DNS are unsupported; real Redis multi-process behavior and deployed TLS,
CSP, origin rejection and Tunnel subnet/trust setup require staging verification. Mutable image tags in
base Dockerfiles should be pinned to reviewed digests by the release process. A code review and passing
local tests do not establish absence of every vulnerability or production readiness.

## Final retry results
- Browser retry after explicit editor labels and the content reset/navigation fixes: **4 passed (32.1s)**.
- Focused complete-review + outbound suite after independent heartbeat changes: **17 passed**.
- The 71-test broad run preceded the final heartbeat change and latest shutdown test; the focused run
  above verifies those final backend changes. It is not represented as another full-suite run.
- All changes remain local/uncommitted. No external infrastructure or accounts were modified.
- Final frontend rerun after all editor/preview changes: TypeScript/Vite build **passed**; frontend unit
  tests **5 passed**. Existing deprecation warnings do not constitute failed tests.
