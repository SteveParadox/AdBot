# Origin and outbound IP protection

Origin privacy and outbound privacy are separate. Cloudflare/Tunnel handles inbound application access;
approved outbound proxies handle browser/model destination connections. Neither has been activated
against live infrastructure by this repository change. The host IP remains known to hosting/DNS/proxy
providers and may be present in historical records. See DOMAIN_AND_IDENTITY_PRIVACY.md for limitations.

The base Compose deployment binds only frontend 5173 to loopback, publishes no API/DB/Redis ports,
and preserves the SSRF egress guard. The optional Tunnel overlay uses an unexposed connector-only Nginx
listener on 8081. Only its static connector peer may present Cloudflare client headers; all other peers
receive 403. A separate internal backend network carries sanitized client IP and fixed HTTPS scheme to
an exact trusted frontend address. The API's Uvicorn proxy parser remains disabled. Enable the overlay
only after verifying edge HTTPS; do not enable HSTS until the entire path passes tests.

For direct Cloudflare origins use current IPv4 AND IPv6 allowlists and authenticated TLS pulls, as in
CLOUDFLARE_SETUP.md/origin-tls.example.conf. Before enforcing ingress restrictions, retain console/VPN
recovery and a second operator session. Never block management access blindly. There is no provider-
specific firewall command because the hosting OS/cloud firewall is unknown. Prepare a change ticket
that permits web ingress only from current Cloudflare ranges (or no inbound web ports for Tunnel),
management only from your VPN/bastion, stateful replies and required health/monitoring. Apply to IPv6 too.
For outbound enforcement allow proxy destinations/ports, explicit local integrations, DNS and internal
services, and reject other Internet web egress at the worker/API container or host boundary. Apply only
after staging with recovery access. No firewall was changed automatically.

Verify externally against YOUR infrastructure: public hostname HTTPS works; direct origin IP with the
real Host header is rejected; alternative DNS/AAAA/staging names do not bypass the edge; DB/Redis/API
ports are closed; forged XFF/CF/Forwarded headers do not change identity. Audit mail/SPF/MX/history for
origin leaks. For egress use controlled target/proxy logs to confirm only approved exits reach targets,
then stop all approved proxies and confirm requests fail rather than appearing directly. Verify redirects,
WebRTC, IPv6 and browser DNS behavior in the actual container. Application DNS resolution still contacts
the configured resolver; remote DNS/SOCKS privacy is not claimed. Provider-side exit IP verification and
network firewall enforcement are required before claiming leak prevention at the infrastructure level.
