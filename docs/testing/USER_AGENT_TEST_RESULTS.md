# User-Agent test results

Initial focused run: 31 passed, 13 browser-marked tests deselected (UA, content/migration and non-browser
agent regression). Frontend TypeScript/Vite build passed. An initial test file encoding error was fixed
before running the focused suite; no failed test was counted as passed.

Coverage: resolution precedence, default/global restoration, protected profile, assignment/deletion,
disabled/unknown policy restrictions, CR/LF/NUL/TAB/non-ASCII/length/whitespace rejection, admin 401/403,
revision conflict 409, service independence, mandatory identity, per-request authorization, single header,
authentication preservation and retry identity. A real local forward-proxy HTTP test additionally checks
actual target headers and bound browser route continuity. Existing HTTPS/proxy-chain regression tests
exercise model clients with TLS verification retained. No third-party networks are used by fixtures.

Full regression, browser administration and final migration/build results are appended once completed.
No new deployment or provider contract verification is claimed. Proxy/Tunnel/firewall release gates from
NETWORK_SECURITY_TESTS.md still apply. Rotation defaults off, and operator-approved browser-only
rotation is not permission to conceal automation or bypass destination controls.

## Final executed results
- `pytest -q -m 'not browser'`: **86 passed, 28 deselected**, one existing Starlette/httpx deprecation
  warning (722.97 seconds). This run preceded the last service-enabled/timestamp and internal helper
  override additions, which are separately covered by focused checks below.
- `pytest tests/test_user_agents.py tests/test_outbound.py -q`: **27 passed**; includes migration
  upgrade replay/downgrade/reapply and DB singleton constraint, alternate rotation, TLS/proxy identity.
- `pytest tests/test_user_agents.py -q`: **15 passed** at that revision.
- `pytest tests/test_user_agents.py::test_internal_request_override_transport_guard tests/test_privacy.py::test_readiness_hides_dependency_details -q`: **2 passed**.
- Browser runner on isolated ports 8100/5180: **5 passed (51.2s)**. Includes real admin global save,
  duplicate profile, restore default plus existing content, agent, screenshot/crawl/schedule journeys.
- Frontend `npm.cmd test`: **5 passed**. Final `npm.cmd run build`: **passed**, after all UI changes.
- App/UA tests/migration Ruff and whitespace checks: **passed** (normal Git CRLF warnings only).

No security checks were disabled to obtain these results. The initial temporary test encoding error was
corrected; real local HTTP and existing verified HTTPS proxy tests remain active. Cross-worker five-second
refresh behavior is implemented but needs production Redis/database/process staging observation; actual
provider-required identities and proxy-provider exit contracts require operator verification. Existing
Cloudflare/Tunnel/Nginx/firewall release gates remain unchanged. No deployment or push was performed.

Final focused checks after the last additions:
`pytest tests/test_user_agents.py::test_disabled_service_and_profile_fallback tests/test_user_agents.py::test_internal_request_override_transport_guard -q`: **2 passed**. Service enable/disable fallback,
server-owned timestamps and explicit internal request authorization therefore have executed evidence.
