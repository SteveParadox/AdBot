# Network security test results

Executed local tests only; no proxy-provider, live Cloudflare/DNS/firewall or public IP change is claimed.

- Initial combined outbound + non-browser agent run: 14 passed, 8 failed, 13 deselected. Investigation
  found proxy-mounted HTTPX clients overrode unit-test MockTransport even when protection was disabled.
  Restored the native legacy model HTTPX path when disabled; enabled routing still uses the shared guard.
  Existing test security assertions and model mocks were not removed or weakened.
- Rerun `pytest tests/test_outbound.py tests/test_agent.py -q -m 'not browser'`: **22 passed**, 13 deselected,
  one existing Starlette/httpx deprecation warning.
- Additional real local proxy + private-CA TLS model integration: **1 passed**. A controlled TCP proxy
  observed the pinned CONNECT IP/port; destination TLS validated a generated test certificate with the
  proper hostname; the HTTPS provider returned JSON; proxy authentication was absent at the target.
- Frontend `npm.cmd run build`: TypeScript and Vite production build **passed**.
- Frontend `npm.cmd test`: **4 passed**.
- `ruff check backend/app backend/tests/test_outbound.py`: **passed**.

Coverage: round-robin, random, sticky, health-preferred, scheduled selection; stable/fixed-route
validation; disabled default; unsafe proxy schemes/userinfo/credential rejection; connect timeout,
explicit failover and circuit cooldown; no automatic direct fallback; local proxy Basic authentication;
credential-free snapshots/redacted logs; provider origin/DNS restrictions; TLS verification settings;
health recovery; admin 401/403 boundaries; Tunnel trust/template checks. Public target DNS, provider
routing and credentials remain under operator control, never visitor input.

Some tests inject resolver/transport behavior or an instrumented TLS writer. The dedicated local TLS
integration separately exercises a real CONNECT chain with verified target TLS; the strengthened rerun also validated TLS to a real local HTTPS proxy using the private CA. It does not verify a
third-party provider's listener, actual public exit IP, remote DNS or external firewall restrictions.
SOCKS is rejected rather than pretending remote DNS is supported. Shared monitoring via real Redis and
live Nginx/Tunnel/origin behavior require staging verification; repository checks alone cannot prove them.

Final full-suite, browser and deployment validation results are appended below after completion.

## Continuation verification
The previous background test/container sessions were unavailable after resuming; their unfinished
results were not counted. A full non-browser run and focused outbound tests were restarted.
- `python -m app.outbound --check` against the placeholder example: **valid**, 2 endpoints/3 services;
  no network calls or credential values printed.
- Encoded Basic proxy credentials are now included in registered log redaction; integration coverage
  checks both raw password and Base64 credential masking.
- `docker run --pull never ... nginx -t`: **not executed successfully**, required image absent locally.
  Earlier image pull did not leave a usable image; no runtime Nginx success is claimed.

## Final verified results (2026-11-14)
- Full backend run: `pytest -q -m 'not browser'`: **67 passed, 28 deselected** in 318.39s.
- Final focused routing run: `pytest tests/test_outbound.py -q`: **12 passed**. This includes the new
  sanitized private-configuration failure guard added after the broad run began.
- Strengthened HTTPS integration rerun: **1 passed**; verified TLS both to the local HTTPS proxy and
  controlled destination, then confirmed the proxy's self-signed certificate is rejected without its
  explicit test CA. No verify=False path was introduced.
- Four Playwright browser journeys: **4 passed** (54.6s); frontend unit tests: **4 passed**;
  TypeScript/Vite production build: **passed**.
- Application/outbound-test Ruff and `git diff --check`: **passed** (only normal CRLF Git warnings).
- Combined base + Tunnel + outbound Compose `config --quiet`: **passed** with validation-only paths
  and placeholder image/credentials; no services deployed or credentials exposed.
- Nginx runtime remains **unverified**: required image absent after resuming; no successful image-pull
  completion or nginx -t result was available. Live Cloudflare/Tunnel, actual provider exit IPs, Redis
  cross-process monitoring and host-level leak prevention remain pending external staging checks.

The broad run predates the final test-only certificate-rejection assertion and private-config guard;
those were covered by the focused results above. Small final changes added redacted failover-attempt
logging and moved worker config validation before Redis resource creation. No production readiness or
anonymity claim is made, and no push/deployment was performed for this task.
