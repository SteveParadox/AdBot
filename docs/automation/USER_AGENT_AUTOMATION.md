# User-Agent automation

The existing `/api/admin/user-agents` API, protected default profile, revision CAS and audit table remain.
The Automation tab embeds the existing editor. Profiles now have `clients`, an explicit list of eligible
`chromium`, `firefox`, `webkit` and/or `httpx` environments. Existing profiles default to all clients for
compatibility; administrators must label their identities accurately. This is metadata filtering, not
browser fingerprint emulation or automatic validation of arbitrary identity claims.

Precedence: operator-fixed service identity; explicitly authorized request override; enabled service
literal value; eligible explicit profile; eligible rotation pool; configured global identity; application
default. An explicit `fallback: "fail"` rejects an assigned profile/pool with no enabled compatible entry.
Disabled service policy uses the global/application fallback. Explicit custom strings remain supported.

| Strategy | Selection at session creation |
|---|---|
| `none` / `manual` | Explicit service identity/profile, then global/default |
| `round_robin` | Atomic SQL counter for the browser service |
| `random` | Random eligible profile |
| `weighted` | Eligible profiles with configured positive finite weights, default 1 |
| `sticky` | Stable hash of logical session ID over the eligible pool |
| `scheduled` | Wall-clock interval selects pool index; existing context remains unchanged |
| `compatibility` | Client eligibility filter plus stable session hash |
| `proxy_endpoint` | Legacy opt-in endpoint hash, retained for compatibility |

Automatic rotation remains browser-only and requires `ADBOT_USER_AGENT_ROTATABLE_SERVICES=browser`.
Provider HTTP clients and proxy-health clients have configurable fixed/manual policies; their identities
cannot rotate. Mandatory identities and stable/nonrotatable egress still prohibit rotation.

Example policy portion, after creating both referenced profiles:

```json
{"services":{"browser":{"rotation":"weighted","profiles":["chromium-a","chromium-b"],
  "weights":{"chromium-a":3,"chromium-b":1},"fallback":"fail"}}}
```

Profile example: `{"id":"chromium-a","name":"Approved Chromium","value":"ApprovedClient/1",
"clients":["chromium"],"enabled":true}`. Use a truthful identity suitable for your integration.

Selection occurs once before browser creation. The exact string is saved in `network_assignments`
and reused on recovery even if the profile is later edited or disabled. A new incompatible mandatory
operator identity fails the resumed session; review and launch a new job. Existing contexts do not
change identity after configuration saves. New eligible sessions see committed revisions through the
one-second watcher or five-second read fallback. HTTP model clients resolve once before provider retries.

Tests: `test_user_agents.py`, strategy/weight/revision cases in `test_automation.py`, browser and E2E
journeys. Operator environment changes and browser-engine installation still require deployment work.
