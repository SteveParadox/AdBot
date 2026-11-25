# Verification results

Verified on November 25, 2026 from the feature branch. The research feature suite passes through the normal FastAPI routes, worker, model transport contracts and SQL persistence with deterministic provider responses.

| Check | Result |
| --- | --- |
| Backend research suites | 41 passed, including a real Chromium renderer and fixture-based search, model, shopping, authorization, cancellation and replay. |
| Focused backend regression | 44 passed when the research suite ran with three migration compatibility tests. |
| PostgreSQL 16 | Feature migration upgrade, downgrade to `021a00000001` and upgrade passed. The non-browser research suite was also exercised against an actual local server. |
| SQLite | Feature migration upgrade, downgrade and upgrade passed. Existing user-agent, content and automation migration history tests passed. |
| Backend Ruff | Passed. |
| Frontend unit tests | 59 passed. |
| TypeScript and Vite build | Passed. The research workspace is loaded as a separate route chunk. |
| Dedicated browser UI tests | 2 passed, including mobile citations, evidence inspection and recovery from an interrupted stream. |
| Full backend regression run | 426 passed, 1 skipped and 3 errors before all browser runtimes were installed. The targeted Firefox rerun passed. Two targeted WebKit cases remained blocked by missing runtime libraries including GTK 4 and Graphene. |
| Full frontend browser run | 23 passed and one existing workspace test timed out waiting for `networkidle`. The same test timed out on baseline `142a518`. |
| Live provider smoke | Pending. No configured live search provider or model credentials were available in this workspace. |

The browser rendering test uses real Playwright Chromium with controlled HTML, a dynamically rendered article, blocked POST and blocked cross-origin fetch. The search, paid-provider fallback and native Ollama protocol tests use transport fixtures. They do not establish production provider availability or Qwen3:4B accuracy.

The second review checked route ownership, migration rollback, cache scope, provider limits, worker lease races, evidence IDs, browser access and frontend/backend response handling. It found and corrected missing evidence caused by repeated passages, SQLite downgrade compatibility after a parent-table rebuild, cold-provider rate-limit bursts, URL credential forwarding, and concurrent usage reservation. [Known limitations](KNOWN_LIMITATIONS.md)
