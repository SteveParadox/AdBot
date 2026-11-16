# IP rotation configuration

Current shared counters/cooldowns, weighted/latency/fixed selection and session protection are documented
in [proxy automation](../automation/PROXY_ROTATION_AUTOMATION.md). Runtime strategies can only refine
existing operator permissions; the private endpoint file remains authoritative.

Only use proxies approved for these destinations. No rotation for access denials, quotas, advertising
engagement, financial transactions or authenticated/fixed-IP workflows. Default protection is disabled;
turning on environment variables alone neither creates proxies nor changes the public server IP.

1. Copy docker/security/outbound-proxies.example.json OUTSIDE the repository. Replace .invalid hosts
   and example credentials with approved endpoints and an HTTPS health endpoint you own or are permitted
   to probe. Restrict file ownership/ACLs to the deployment service. Never use frontend VITE variables.
2. Keep browser and ai stable with one statically allocated endpoint unless the destination explicitly
   permits rotation and no authentication/session/fixed-IP dependency exists. ai_local direct mode is
   explicit approval for the server-configured local model integration; omit it to fail closed.
3. Set ADBOT_OUTBOUND_PROXY_ENABLED=true and ADBOT_OUTBOUND_PROXY_CONFIG_PATH to the private mounted
   file. With Compose use compose.outbound.yml and ADBOT_OUTBOUND_PROXY_CONFIG_FILE as the host path.
4. Configure connect timeout (default 5s), CONNECT reply/health timeout (15s), bounded connect retries
   (2), and health interval (60s). Browser/job and HTTPX provider request deadlines still bound actual
   requests; the local stream guard retains its 180-second transport ceiling and existing job budgets.
5. To enable round-robin: service strategy=round_robin, stable=false, allow_rotation=true, list two or
   more approved endpoint IDs. Random uses strategy=random; health prefers measured lower latency;
   scheduled changes eligible route selection by rotation_seconds (minimum 30); sticky retains each
   context's assigned route. Enable allow_failover separately only if cross-IP continuity is permitted.
6. Restart API and workers, inspect admin diagnostics and operator logs, then test through controlled
   destinations. Verify provider exit addresses out-of-band without using unauthorized public echo sites.
7. Disable rotation by restoring sticky/stable/single-endpoint configuration. Disable protection only
   with explicit approval for direct routing; this re-enables original direct destination sockets. To
   fail closed during maintenance, leave required mode enabled with unavailable proxies rather than
   switching the global protection flag off.

Troubleshooting: 503 monitor errors indicate Redis/diagnostic failure; target connection failures with
required routing never fall back direct. Open circuits require cooldown and a successful probe/connection.
Unknown endpoint IDs, unapproved service names, SOCKS URLs, URL userinfo, unsafe credentials and rotating
stable policies fail config validation. Proxy refusal may mean CONNECT IP/port policy is unsupported;
work with the approved provider rather than changing target restrictions. Fix system CA trust for TLS
problems; never disable certificate verification. Rotation ordering/counters are not coordinated across
multiple processes. A stable endpoint's provider must also guarantee a fixed public exit address.
