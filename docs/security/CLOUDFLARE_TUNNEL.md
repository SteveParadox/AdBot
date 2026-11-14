# Cloudflare Tunnel deployment and recovery

Status: repository templates only; no tunnel, DNS record, certificate or firewall was created.
Use a named, organization-owned tunnel and MFA-protected least-privilege Cloudflare administration.

## Prepare
1. Confirm public hostname, business ownership and the existing TLS/DNS plan. Follow CLOUDFLARE_SETUP.md.
2. On an authorized operator workstation install the supported cloudflared CLI, authenticate through
   the provider's browser flow, create a named tunnel and route the intended DNS hostname to it. Keep
   account login material and connector JSON outside this checkout. Use a read-only deployment credential
   for the named tunnel, not a global API key. Do not paste any credential into chat or source control.
3. Copy docker/security/tunnel.example.yml outside the repo. Fill your actual tunnel UUID, credentials
   path and hostname. Service is http://frontend:8081 and the final route is http_status:404.
4. Set ADBOT_TUNNEL_CONFIG_PATH, ADBOT_TUNNEL_CREDENTIALS_PATH and ADBOT_CLOUDFLARED_IMAGE in private
   deployment environment. Pin a reviewed cloudflared image by digest; the template refuses an unset value.
5. Confirm that 172.30.50.0/29 and 172.30.51.0/29 do not overlap existing host/Docker/VPN ranges. If they
   do, change BOTH overlay IPAM/static addresses AND tunnel-ingress.conf geo/trust values. The connector
   is .50.2, frontend connector listener .50.3, frontend backend hop .51.3, API backend hop .51.4.
6. Validate Compose quietly to avoid dumping interpolated credentials:
   `docker compose -f docker-compose.yml -f docker/security/compose.tunnel.yml config --quiet`.
7. Verify edge HTTPS enforcement and a working recovery console BEFORE starting this overlay; it enables
   API HTTPS enforcement. HSTS remains off until verified. The base 8080 listener does not stamp HTTPS.

## Start and verify
Run `docker compose -f docker-compose.yml -f docker/security/compose.tunnel.yml up -d --build` only as
an approved deployment. The overlay mounts a separate Nginx listener with an original-socket-peer geo
check. Only the designated connector can submit CF-Connecting-IP; Nginx translates the validated
header into X-Real-IP and stamps HTTPS on that authenticated HTTPS-only ingress. The API trusts only
172.30.51.3/32 on the dedicated internal network. Requests from other peers to port 8081 receive 403.
The base listener remains loopback-published for local recovery; no inbound public HTTP/HTTPS is needed.

cloudflared's metrics listener is internal on port 2000; monitor its /ready endpoint from an authorized
container on the tunnel_ingress network, not the public Internet. A 200 indicates connector readiness;
then verify the public app, API auth, content publishing, SSE jobs and screenshots. Check the dashboard's
tunnel health and use redacted container logs. Do not publish metrics ports or use an invented curl
healthcheck in a minimal cloudflared image. [Metrics](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/monitor-tunnels/metrics/)
and [readiness example](https://developers.cloudflare.com/tunnel/guides/kubernetes/).

Verify public HTTPS works and edge HTTP redirects. Test that forged forwarding headers cannot change
client identity, other containers cannot use the privileged listener, and the API rejects insecure
ordinary requests. Validate IPv6, DNS alternatives and direct origin access from YOUR external test
host. In a Tunnel deployment inbound public web ports should be closed by host/cloud firewall. Do not
assume DNS proxying alone enforces this. Cloudflare client-header behavior is documented in
[HTTP headers](https://developers.cloudflare.com/fundamentals/reference/http-headers/).

## Recovery and rollback
Restart a failed connector with the same read-only credential; inspect outbound DNS and required Tunnel
transport reachability before changing authentication. Rotate/revoke a compromised connector credential
at Cloudflare, replace the private file and restart the service. Retain the previous approved image digest
and configuration. For rollback restore the prior verified ingress/DNS and base Compose deployment;
remove the overlay service only after another ingress works. Keep SSH/VPN/console management available.
HSTS, if enabled separately, persists in client browsers after rollback. Never switch to Flexible TLS or
trust arbitrary forwarded headers to make a broken deployment appear healthy. For direct HTTPS origins
use Full (strict) plus allowlisting/AOP as described in CLOUDFLARE_SETUP.md.
