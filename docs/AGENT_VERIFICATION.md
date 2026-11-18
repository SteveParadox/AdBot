# Autonomous agent delivery and verification

Date: 2026-10-17. Starting revision: `9dd3a00`. The repository initially had
working crawling, scripted workflows, durable jobs, scheduling, live events and
a React dashboard. It had no LLM, goal-driven planner, semantic control registry,
task memory, tab manager, review queue or task completion verifier.

## Delivered changes

The existing worker and browser lifecycle now execute `agent` jobs. New modules
in `backend/app/agent/` separate model transport, structured contracts, page
observation, controlled browser actions, memory, task APIs and the execution loop.
Shared API authentication/serialization moved to `app/api_support.py` while
preserving existing endpoints. No second production orchestrator was introduced.

The agent observes DOM/main/viewport text, accessibility information, current
controls and tabs; chooses a validated model action; executes it; observes the
outcome; records it; and updates memory. Failed or stale actions trigger bounded
replanning. A repeated failed action on unchanged state is rejected. Step,
token, tab, recovery, navigation, download and original session budgets terminate
incomplete work as failed.

Task modes support assisted approvals for non-click actions, autonomous browsing
and live supervision. All clicks, including non-GET submissions, execute without
approval. Targets must still match the observed page/form state. A form click
grants one matching method/destination; a JavaScript click permits one
policy-checked write during the action, bounded to five seconds.
Ambiguous in-flight mutations stop for review after a worker/browser interruption.
Read-only progress can recover from committed URL/tab checkpoints.

Short-term context, session URL/evidence/action memory and successful reusable
task memory are implemented. Reusable knowledge is isolated by workspace and
website, ranked for relevance, retained for a bounded period and deletable. Optional
cookies/local-storage checkpoints use a server-side Fernet key and are excluded
from API output. Image reasoning is optional and requires a compatible model.

The new **AI Agent** dashboard connects to real task APIs and SSE: objective/URL
entry, autonomy and budget settings, previews, current decisions, controls,
review replies, steps, history, memory, usage metrics and cited results. The model
settings panel exposes readiness and limits, while secrets remain in server
configuration. Existing crawling and workflow screens remain usable.

Migration **37745660af92** adds `agent_tasks`, `agent_steps` and `agent_memories`.
The `.env.example`, initializer, dependency list, fixture application, CI and
test runner were extended. See `AGENT_GUIDE.md` for every new setting, module,
endpoint and installation/start command.

## Executed checks

Commands below run from `backend/` using the virtual environment's executable:

| Command | Result |
| --- | --- |
| `python -m pytest -q --tb=short --show-capture=no` | 47 passed, including 18 new agent tests |
| `ruff check app tests testsupport` | Passed |
| `python -m alembic upgrade head` | Initial + agent migrations applied successfully on SQLite |
| `python -m alembic check` | No model/schema drift |
| PostgreSQL `alembic upgrade head --sql` | Offline SQL generation passed; no live database involved |

From `frontend/`:

| Command | Result |
| --- | --- |
| `npm test` | 2 parser tests passed |
| `npm run build` | TypeScript and production build passed |
| `npm run test:e2e` | 2 UI journeys passed, using real Chromium browsers |
| `npm audit --audit-level=moderate` | 0 known vulnerabilities |

From the repository root, `pip-audit -r backend/requirements.txt` reported no
known vulnerabilities. One existing Starlette TestClient/httpx compatibility
deprecation warning remains; it does not fail the tests.

New agent tests cover strict decision parsing, provider gating, idempotency
conflicts, task/memory ownership isolation, authenticated results, malformed
model JSON, usage accounting, token reservation, exact source evidence,
completion rejection without observed citations, step-budget failure, stale
review prevention, interrupted mutation handling, form review and an actual
POST, semantic search, changed link order, dynamic loading, tab creation,
bounded downloads, encrypted real browser cookies, and recovery/replanning
after an unavailable target element.

## Demonstrated natural-language workflow

The UI test supplies the objective:

> Find the launch month for Orion AI and cite the source.

Starting from the local news fixture with reversed link order, the worker
observes the actual page and semantic links. The model endpoint selects the
relevant observed element ID. A real browser clicks the article, extracts its
exact statement, and returns a cited claim after a separate criterion check.
The dashboard displays the real capture, source URL and action outcomes.

Observed sequence: **CLICK → EXTRACT → COMPLETE**, plus the independent
verification request. The recorded fixture usage is four model calls and
3200 tokens. The returned quote is “Orion AI will launch in November 2026.”
This is deliberately fictional test-site content, not a real product claim.
Desktop and 390-pixel mobile layouts were captured and visually inspected;
the UI test also checks that the mobile document does not overflow horizontally.

Other real-browser fixtures exercise search, a dynamically inserted link, a
product catalog without checkout, a two-stage registration form requiring two
reviews, a second tab, and a downloaded source document. Decisions bind to current
observed controls rather than hardcoded production page selectors.

## Model test boundary and remaining limitations

**The local model endpoint is a test double.** `backend/testsupport/model_fixture.py`
returns schema-conforming decisions based on current observations and lexical
goal relevance. It is not a bundled LLM or a production fallback. Browser, proxy,
database, worker, API, review and dashboard operations are real in these tests.
No live Groq/OpenAI-compatible credentials were supplied, and no live model
quality, latency or real-world task success rate was verified. The real transport
supports those services; run the live-provider fixture journey in `AGENT_GUIDE.md`
after configuring your provider.

Additional deployment/product limits:

- Docker images and a live PostgreSQL/Redis stack were not run in this
  environment. The existing dedicated PostgreSQL CI job remains supplied.
- Chromium was executed; other engine paths and native Windows execution were
  not newly certified. Browser/runtime updates still need deployment validation.
- Visual input construction is implemented, but a live vision-model response
  was not tested. A screenshot preview itself does not imply model vision ran.
- Recovery restores URL history and optional cookies/local storage, not an
  arbitrary browser process, open download, sessionStorage or every SPA state.
  In-flight consequential interactions require manual review rather than replay.
- Semantic role/name targeting falls back to an observation-bound control index
  when accessibility metadata is ambiguous. Difficult custom widgets may require
  another observation, vision-enabled planning or user intervention.
- Evidence and completion checks constrain source fabrication but cannot prove
  every interpretation made by an LLM. Success quality must be evaluated on the
  actual model and websites you deploy.
- The task panel's provider settings are read-only; provider secrets/configuration
  are managed through environment variables. No user-account/RBAC or universal
  credential-login feature was added.
- Native automatic downloads/popups remain disabled. Controlled link downloads
  are bounded to 10 MiB and stored as authenticated `.bin` attachments.
- Screenshots/page observations can contain information from approved targets;
  browser session encryption does not encrypt every screenshot or report.
  Review actual retention and provider-data needs when deploying.
- Application URL/request checks do not replace production browser sandbox and
  egress enforcement. Existing operational guidance still applies.

Assessment: integrated, runnable goal-driven agent implementation with real
browser and UI verification, using a model test double for reproducibility.
Live-model behavior and production deployment remain explicit verification
tasks; they are not represented as completed here.
