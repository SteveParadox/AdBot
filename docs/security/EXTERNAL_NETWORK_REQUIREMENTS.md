# External network requirements

All live actions below are Pending Manual Action. Repository configuration is not proof of activated
protection. No external account, network firewall, tunnel or proxy was changed. Operators must retain
recovery access and use a maintenance/staging rollout appropriate to their hosting platform.

| Provider | Action / access | Verification | Rollback / limitations |
|---|---|---|---|
| Proxy provider | Procure approved HTTP(S) CONNECT service, required port/IP destinations, TLS and static exit allocations for fixed services; approve health probe endpoint/frequency; obtain scoped credentials | Controlled target logs show contracted exit IP; provider confirms no hidden per-connection rotation; all proxies down produces failure, not origin IP | Revoke compromised credentials; restore last approved endpoint file; provider fees/availability apply |
| Host secrets | Mount private JSON/connector credentials read-only outside source and frontend environment; owner-only ACLs; update API and worker together | `python -m app.outbound --check` validates without network; diagnostics omit secrets; file access test as service user | Restore encrypted config backup and restart; never enable direct mode as accidental outage fallback |
| Cloudflare/DNS | Create named tunnel, route real hostname, pin connector image, enable edge HTTPS, review Access/WAF/caching and old A/AAAA/MX leaks | Connector /ready and public hostname work; alternative/origin hosts cannot bypass; no cached private APIs | Restore approved previous DNS/ingress; DNS TTL and certificate readiness matter; plan capabilities/costs vary |
| Hosting ingress | Restrict web ingress to Cloudflare with authenticated TLS pulls, or close public inbound web ports for Tunnel; retain VPN/console management | Own external Host-header/IP and IPv6 tests fail direct; DB/Redis/API closed | Restore saved firewall rules via console; do not apply blanket firewall scripts |
| Docker topology | Verify optional overlay subnet availability, update all coupled static trust/geo/alias values when changing them; restrict privileged ingress listener to connector | Compose validation then real Nginx runtime test; other peers receive 403; trusted client IP/HTTPS scheme correct | Restore base overlay-free network configuration and prior verified ingress |
| Host/container egress | Restrict API/worker destination sockets to approved proxy IPs/ports, DNS, DB/Redis, explicit local integrations, monitoring and Tunnel needs; enforce IPv4 and IPv6 | Controlled packet capture/flow logs; direct web socket fails; browser WebRTC/background and DNS tested | Console restore prior reviewed ACL; exact rules depend on unknown production OS/cloud firewall |
| DNS resolver | Use an approved controlled resolver with suitable encryption/ACL/retention; app deliberately resolves locally to validate/pin target IPs | Resolver/flow logs and mixed-private DNS tests; upstream sees pinned IP, not a re-resolved name | Restore previous approved resolver; remote DNS/SOCKS not supported or claimed |
| Monitoring | Permit internal Redis heartbeat keys and required Redis commands; protect metrics network and admin API; set retention and alerts for open circuits/failovers | Cross-worker snapshots expire after 3 intervals; failures/redaction observable; no publicly published metrics | Restore known monitor config; Redis failure must not silently approve direct traffic |
| Destination owner | Confirm automation/proxy/rotation permission; fixed-IP, financial, logged-in and allowlisted services stay stable | Document permitted policy and controlled test; respect denials and rate limits | Disable eligible rotation, retain fixed endpoint; never rotate around denial |

Network-layer validation is mandatory before asserting leak prevention under process compromise. Application
routing does not intercept database/Redis/Tunnel control traffic, host DNS, arbitrary OS tools or future
clients that bypass the shared interface. Proxy providers and hosting/DNS operators still know routing
and ownership information. No anonymity guarantee is made. Use EXTERNAL_SECURITY_CHECKLIST.md for
registrar, business and broader compliance requirements; nothing here authorizes misleading records.
