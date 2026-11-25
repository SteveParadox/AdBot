# Architecture audit

Baseline [142a518](https://github.com/SteveParadox/AdBot/commit/142a51843185c1263e268bbe870c07d96632534a), November 25, 2026. The checkout was clean. The remote contained main, the autonomous-clicks, clickable-docs, Chromium-size and exclusive-ownership branches. The linked GitHub open-PR search returned no open results. The docs, viewport and browser ownership work is present on the baseline.

| Capability | Baseline finding | Research integration |
| --- | --- | --- |
| Natural-language routing and discovery | Missing. `agent/contracts.py` requires `website_id`. `agent/api.py` loads the owned Website and `jobs.make_job` seeds its base URL into the frontier. | Separate query API and search adapters. |
| Cross-domain access | Unsuitable. `security.Policy` requires declared domains and applies operator authorization. `egress.py` pins DNS for browser and HTTP routes. | Dedicated public policy and egress service. |
| Browser lifecycle | Reusable primitives. `browser.py` uses isolated context, route filtering, blocked service workers and browser ownership. Agent controller supports general actions and persisted sessions. | Use isolated Chromium with dedicated read-only routes. |
| Extraction | Partially implemented. `extraction/engine.py` captures browser data using registered extraction schemas and datasets. | Extract generic main text and structured product metadata from public responses. |
| Plan, evidence and verification | Partially implemented in `agent/planning.py`, `agent/runner.py` and `agent/contracts.py`. Plans use site state; quotes bind to observed pages; checks use strict model JSON. | Use independent research queries, source IDs and semantic support checks. |
| Models | Reusable with a prompt entry point. `agent/model.py`, `provider_quota.py` and `outbound.py` provide strict JSON, deadlines, Groq, compatible endpoints, native Ollama, quota accounting, retries and configured failover. | Share the transport. |
| Queue and recovery | Implemented in `jobs.py`, `worker.py` and `scheduler.py`. SQL is authoritative, Redis can wake workers, and leases fence final writes. Baseline jobs all reference sites. | Extend job types and allow website-free research rows. |
| Memory and tenancy | `agent/memory.py` scopes summaries to the owner and registered website. Auth and retention are reusable. | Add owner-scoped conversations and research result retention. |
| API and events | Auth, task history, job control and replayable SSE already exist. | Add versioned research routes and reuse job event streaming. |
| Frontend | `AgentPanel.tsx` expects registered sites, agent plans and browser outcomes. `main.tsx` dispatches the docs shell. | Add a dedicated research route and use the existing client and event stream. |
| Verification | Existing suites cover egress, browser ownership, recovery, quotas, fallback and extraction. | Add fixture-based service, API, browser and UI coverage. |
