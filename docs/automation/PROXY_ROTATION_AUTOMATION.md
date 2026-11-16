# Proxy automation

Private operator JSON remains the source of endpoint addresses and credentials. No endpoint credentials
are added to runtime policy or dashboard payloads. TLS verification, pinned destination IPs, authorized
domains and the local method/framing guard remain mandatory. Only HTTP(S) CONNECT proxies are supported.

Each endpoint may specify `weight` (positive finite value up to 1000, default 1). Required services can
select `round_robin`, `random`, `weighted`, `latency`, `health`, `sticky`, `fixed` or `scheduled`.
`fixed` requires exactly one endpoint. Stable services require exactly one endpoint and reject rotation
and failover. Rotation/failover must be explicitly allowed in the private operator configuration.

Example browser service for an authorized integration which permits changes between sessions:

```json
{"mode":"required","endpoints":["approved-a","approved-b"],"strategy":"weighted",
 "stable":false,"allow_rotation":true,"allow_failover":true}
```

Do not apply this example to an integration requiring a fixed source IP. Runtime `proxy_strategies`
can change only the strategy of already authorized required services; it cannot add endpoints, enable
direct fallback, relax fixed routing or authorize rotation.

Round robin uses a shared SQL counter. Scheduled selection uses wall-clock intervals. Weighted uses
endpoint weights. Health/latency choose the smallest observed latency in the current process; shared
cooldowns exclude endpoints known to have failed elsewhere. Redis aggregates per-process diagnostics.
Latency measurements are not a globally merged ranking. Keep worker host clocks synchronized.

Monitoring uses each configured operator-owned HTTPS health URL. Latency, successes/failures, consecutive
failures, timeouts, authentication failures, TLS errors, recovery attempts and last success are recorded.
Failure opens a jittered circuit with bounded backoff. A later valid health request or eligible connection
recovers it. Shared failure timestamps prevent an older in-flight success from clearing a newer failure.
The runtime health interval is 10–3600 seconds; a sleeping monitor sees changes on its next cycle.

Bound sessions retain their route. Explicitly permitted failover may select a healthy approved replacement,
record the new assignment and keep the same User-Agent. Persisted/authentication-capable agent sessions
are protected against route changes even when a general browser service permits failover. Required egress
always fails closed when no suitable route exists. HTTP 407 produces authentication-failure diagnostics.

Shared selection happens at session boundaries. Bound-session shared-health reads and healthy-state
publication are limited to roughly once per second per process/service or endpoint; failures publish
immediately. SQL outages do not silently turn required egress into direct traffic. The private file and
provider exit-IP allocation still require operator provisioning and deployment verification.
