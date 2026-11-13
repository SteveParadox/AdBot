# Cloudflare setup — pending manual action

No Cloudflare deployment is assumed. These are operator steps; do not place credentials in the repo.
Keep a tested recovery console and a second operator session before changing DNS, TLS or firewalls.

1. Create an organization-controlled Cloudflare account, enable MFA and recovery codes, invite operators
   with least privilege. Use a business address. Domain/DNS administrators must approve the migration.
2. Add your actual domain as a zone and select the appropriate plan. Export current DNS before changes.
3. Compare imported A/AAAA/CNAME/MX/TXT/SRV records to the authoritative zone, including SPF/DKIM/DMARC
   and verification TXT. Mail records must remain DNS-only. Do not proxy unsupported protocols.
4. At the registrar replace nameservers with the exact pair assigned to this zone; verify authoritative
   NS answers and Cloudflare zone activation. Coordinate DNSSEC DS changes using provider instructions
   to avoid validation outages. Roll back to the recorded delegation if activation fails.
5. Proxy eligible web records (orange cloud). Check both apex and www and all AAAA records; old DNS-only
   staging/mail records may expose the same origin. Move unrelated services off that origin where needed.
6. For a direct HTTPS origin choose Full (strict), not Flexible. Provision a valid origin certificate and
   key on the TLS terminator, matching the hostname. Cloudflare Origin CA certificates are for the
   Cloudflare-to-origin leg; normal browsers will not trust them directly. Keep keys outside source control.
   Verify renewal, chain and expiry before switching. [TLS modes](https://developers.cloudflare.com/ssl/origin-configuration/ssl-modes/).
7. Turn on edge HTTPS enforcement after checking HTTPS works. Keep the origin HTTPS-only for app traffic.
   Set ADBOT_ALLOWED_HOSTS and exact CORS origins to real verified hostnames. Set ADBOT_ENFORCE_HTTPS=true
   only once the final trusted proxy supplies correct https. API rejects HTTP with 426, so edge HTTPS
   redirects must happen before API forwarding. Enable HSTS last after recovery testing; no preload or
   includeSubDomains is automatically applied. HSTS cannot be instantly rolled back in client browsers.
8. Enable the rules available for your plan and inspect Security Events for false positives. Start with
   the Free Managed Ruleset where available. Avoid bypass rules covering the whole API.
9. Add an IP rate rule for /api/ (start from measured usage); if plan allows more rules add tighter limits
   for POST /api/jobs, /api/agent/tasks and /api/admin/content. Use 429/block for API abuse rather than
   interactive challenges that break programmatic callers. Retain application limits and ownership checks.
10. Review available DDoS and bot controls. Test authorized API clients before enabling challenges.
    Advanced WAF/bot/rate characteristics and additional capacity depend on plan. Free currently includes
    the Free Managed Ruleset and one rate rule; check live availability before purchase or rollout.
    [WAF availability](https://developers.cloudflare.com/waf/) and [rate limits](https://developers.cloudflare.com/waf/rate-limiting-rules/).
11. Optionally protect the admin API hostname/path with Cloudflare Access and the organization's IdP.
    Test browser preflight, bearer APIs and machine service tokens. Access is an additional boundary;
    it does not replace content-admin authorization. A separate protected admin hostname can simplify
    policies. Access/Zero Trust is a separate service with user/plan limits; verify current pricing.
12. Choose one origin boundary: outbound-only Tunnel (preferred where suitable), or a TLS origin with
    network allowlisting and Authenticated Origin Pulls. For allowlisting obtain CURRENT IPv4 and IPv6
    ranges from https://www.cloudflare.com/ips/; permit only these to web ports, retaining separate
    operator VPN/SSH and recovery access. Do not run a blanket firewall script from this repository.
13. For AOP stage certificate verification, enable Cloudflare origin pulls, test, then require client
    certificates at the origin. See docker/security/origin-tls.example.conf. A shared Cloudflare client
    certificate identifies its network, not exclusively your account; constrain hostname and prefer
    dedicated authentication where available. [AOP](https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/).
14. For Tunnel create a named tunnel, save credentials/config outside this checkout, copy and fill
    docker/security/tunnel.example.yml, and mount using compose.tunnel.yml. Create the tunnel DNS route
    in the dashboard. Pin an approved cloudflared image digest before deployment. A healthy connector
    plus a 404 catch-all is required. No inbound origin web ports are needed. Keep the loopback frontend
    port for recovery or remove it in an operator-specific overlay. AOP adds nothing to Tunnel's already
    authenticated connector transport. [Tunnel TLS](https://developers.cloudflare.com/tunnel/troubleshooting/https-origins/).
15. Client IP: never trust arbitrary CF-Connecting-IP or XFF. For direct Cloudflare ingress use Nginx
    real_ip only with current set_real_ip_from ranges AND origin access restrictions. For Tunnel use a
    dedicated listener reachable only by the connector and validate that peer before accepting CF data.
    The final Nginx must send a single X-Real-IP and scheme and strip incoming forwarding headers.
    Set ADBOT_TRUSTED_PROXY_CIDRS to that final Nginx peer, not the whole Internet. Disable Uvicorn proxy
    rewriting in every custom launch too. Base nginx.conf uses its socket peer and http scheme; it does
    not automatically trust Cloudflare. An authenticated HTTPS-only tunnel listener may stamp a fixed
    https scheme after edge enforcement is verified. [Header semantics](https://developers.cloudflare.com/fundamentals/reference/http-headers/).
16. Bypass edge caching for /api/*, authenticated requests, errors and admin routes. Honor no-store.
    Cache only public versioned static assets. Do not apply Cache Everything to the dashboard/API.
17. Review Security Events and connector/origin health after rollout; restrict log access and retention.
    Do not record bearer keys, request bodies or full query strings in edge log exports.
18. Verify from an authorized external network: HTTPS/certificates, HSTS only if enabled, admin 401/403,
    spoofed forwarding headers, API no-store, SSE streams, CORS, screenshots and content publication.
    Try your OWN origin IP with the real Host header: it must fail without the permitted network/client
    certificate; Tunnel origins must have no inbound web listener. Check IPv6 too. Do not scan third parties.

Repository tests validate configuration behavior, not actual edge/origin isolation. All account, DNS,
certificate and firewall steps remain Pending Manual Action until a named operator records evidence.
