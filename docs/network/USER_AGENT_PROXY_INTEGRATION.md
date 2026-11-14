# User-Agent and proxy coordination

An identity belongs to a logical HTTP operation or browser context, not to a connection attempt.
Browser startup binds an approved route, resolves identity once, creates the browser with that identity,
and uses the same string for robots fetches, can_fetch/crawl_delay and controlled downloads. Browser
headers are configured once by the browser engine; no duplicate extra User-Agent is added. Robots and
download HTTPX clients explicitly replace their single UA header. Model clients resolve per provider
once, with header pooling and retries preserving the selected value and Authorization independently.
Health probes resolve the health service identity before each new probe. Existing redirect/SSRF checks,
TLS verification, proxy authentication, fail-closed requirements and automation markers are retained.

Automatic coordination is opt-in proxy_endpoint strategy: at the start of a NEW browser context, the
initial approved endpoint ID deterministically maps to one enabled profile. Browser connections then
share a bound route. Authorized connect failover may change that route but never changes the active
context UA. New contexts can select new endpoints/profile mappings. This deliberately avoids coordinated
mid-session identity changes. Raw integration clients not bound to browser contexts retain existing
proxy selection semantics. Request/body retries are not introduced by header selection.

Round-robin/random/scheduled UA strategies are independent of IP selection; no failover callback changes
headers. If proxy routing is enabled, stable or nonrotatable service policies reject automatic UA
rotation. Local/fixed model integrations never rotate UA automatically. Operator permissions and proxy
policy both matter. Do not enable rotation for authenticated, financial, provider-allowlisted or other
stable-identity operations. Settings do not authorize bypassing a destination's quota, ban, challenge,
policy or ad-traffic controls. No response status triggers UA changes.

Per-request internal override requires both operator opt-in and authorized=True at the shared resolver;
it is not accepted from visitor request headers or job payloads. Mandatory operator service identities
win even over authorized overrides. Validate the returned value and reuse it for retries. Future clients
should adopt resolve(service) at their operation boundary rather than invoking it for each retry/socket.
