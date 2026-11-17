# User-Agent rotation: real browser simulation

Verified 2026-11-17 using a temporary database and a loopback-only destination on port 8765.
The test configures profiles through the authenticated admin API, queues jobs through the job API,
claims them through the existing queue and executes the real Playwright worker path. The destination
records the headers it actually receives. Live workspace profiles/environment are not changed.

| Browser session | Observed identity on both pages | Result |
|---|---|---|
| 1 | Adbot-Rotation-A/1 | Completed |
| 2 | Adbot-Rotation-B/1 | Completed |
| 3 | Adbot-Rotation-A/1 | Completed |
| 4 | Adbot-Rotation-B/1 | Completed; identity remained pinned during an admin configuration update |
| 5 | Adbot-Rotation-A/2 | Completed; new session applied the saved revision and skipped disabled B |

During session 4, after the first page was recorded, the test edits A to version 2 and disables B.
The second page still receives B/1. Session 5 receives A/2. A third disabled candidate is never selected.
Every session visits two pages, and its robots request uses the same selected User-Agent. Browser page
requests retain X-AdBot-Automation:true and the matching X-AdBot-Session job identifier. Persisted network
assignments match the captured identities and are inactive after completion.

Result: **1 end-to-end test passed, five completed browser jobs, ten page visits, 25.91 seconds**.
Ruff check passed. The only pytest warning was the existing Starlette TestClient deprecation.

Reproduce from backend with fixture port 8765 free:

```powershell
..\.venv\Scripts\python.exe -m pytest tests/test_user_agent_rotation_e2e.py -q -s
```

This verifies round-robin rotation and revision/session continuity over actual local browser requests.
It does not claim that every rotation strategy or an external proxy/provider was exercised in this run.
