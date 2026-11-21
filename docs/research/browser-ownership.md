# Concurrent browser ownership

Research source: [Browser Use Agent.run](https://github.com/browser-use/browser-use/blob/e682e0dc02d77a307a5b2aedf17142c2cd69af5b/browser_use/agent/service.py#L450), inspected 2026-11-21.

Browser Use rejects an already-running Agent and a Browser whose `_user` is set.
It claims both before awaiting work and releases both in `finally`. Its error
message recommends a separate Browser for each concurrent Agent, allowing
sequential reuse with keep_alive. Sharing a browser can drive the same tab or
let one agent stop another's browser.

Adbot already creates a Runner per worker execution and launches a separate
Playwright browser and nonpersistent context per run. AgentRunner inherits this
lifecycle. Its restored storage state comes from that job's AgentTask, rather
than a common browser profile. Keep this architecture: no global browser,
context, page, or persistent profile is introduced.

The additional guard rejects concurrent reuse of a Runner before any mutable
state is changed. After launch it claims the browser before context creation;
a rejected claimant never closes the existing owner's browser. The successful
owner closes its browser before releasing ownership, including on failures and
cancellation. The registry retains object identities while owned and protects
claim/release with a thread lock. This is an independent adaptation of the
ownership pattern; no Browser Use code or dependency is copied.

Ownership is process-local. Existing SQL job leases remain responsible for
cross-process scheduling and durable-write fencing. Browsers are launched
locally, not attached through shared CDP endpoints. This guard does not claim to
coordinate external browser services or make a stale remote worker disappear.

Regression coverage includes overlapping runner calls, rejection without
releasing an existing claim, release on completion/error/cancellation, and two
real worker jobs writing different cookies and localStorage on the same origin.
Production domain leases serialize jobs targeting the same domain; the test
seeds a second execution lease to exercise same-origin isolation without changing
that scheduling policy. The browser test also navigates one job independently and cancels it while the
other continues, then verifies both owned browser processes disconnect.
