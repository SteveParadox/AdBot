# Goal-driven AI browser agent

AdBot now supports natural-language browsing tasks alongside its existing crawler
and scripted workflows. The same API, worker, SQL queue, network controls and
dashboard serve both paths. No additional queue service or agent orchestrator
is required.

## Upgrade and start

From the repository root on Windows CMD:

```bat
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd backend
..\.venv\Scripts\python -m alembic upgrade head
```

On Linux/macOS:

```sh
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd backend
../.venv/bin/python -m alembic upgrade head
```

If installing from scratch, follow the root README to create the virtual
environment, install Playwright browsers, generate `.env`, and install frontend
dependencies with `npm ci`. Existing `.env` files are preserved by the initializer;
add the new settings below manually when upgrading.

## Configure Groq

Edit the **root `.env`**:

```dotenv
ADBOT_AI_PROVIDER=groq
ADBOT_GROQ_BASE_URL=https://api.groq.com/openai/v1
ADBOT_GROQ_API_KEY=YOUR_GROQ_KEY
ADBOT_AI_MODEL=openai/gpt-oss-120b
```

The model ID is an example from the requested configuration; use a model your
account can access. The client sends requests to the configured Groq base URL
plus `/chat/completions`. Do not prefix the model with `groq/` when using this
OpenAI-compatible endpoint. Provider keys stay on the server and are never
returned by the dashboard configuration API.

For another OpenAI-compatible endpoint:

```dotenv
ADBOT_AI_PROVIDER=openai_compatible
ADBOT_AI_BASE_URL=https://YOUR_PROVIDER/v1
ADBOT_AI_API_KEY=YOUR_PROVIDER_KEY
ADBOT_AI_MODEL=YOUR_MODEL_ID
```

For a locally hosted server implementing `/v1/chat/completions`:

```dotenv
ADBOT_AI_PROVIDER=local
ADBOT_AI_BASE_URL=http://127.0.0.1:11434/v1
ADBOT_AI_MODEL=YOUR_INSTALLED_MODEL
```

The local service must actually support chat-completions JSON responses and the
selected model. No local model is bundled or automatically installed. In Docker,
`127.0.0.1` means the container; configure an address reachable from the API/worker
containers. Provider requests use direct HTTP connections, without inheriting
shell proxy variables. Remote providers require HTTPS; only operator-configured
local providers may use HTTP.

To use a local Ollama model as an automatic fallback for any primary-model
failure, keep Groq as the primary provider and add these settings:

```dotenv
ADBOT_AI_FALLBACK_PROVIDER=local
ADBOT_AI_FALLBACK_BASE_URL=http://127.0.0.1:11434/v1
ADBOT_AI_FALLBACK_MODEL=dolphin3:8b
```

The primary provider gets one request. Any HTTP response other than 200, timeout,
network failure, invalid response, schema mismatch, or exhausted primary token
reserve immediately switches the same request to the fallback. The fallback uses
the configured retry budget and separate 60-second timeout for local inference by
default. Model responses are capped at 800 output tokens by default, which is
enough for the structured action and verification JSON.
If the fallback returns malformed JSON or a response that fails the action schema,
it retries internally before the agent records a failed step.
When fallback is enabled,
the agent reserves 10,000 tokens of each task's existing token budget for fallback
calls by default. Set `ADBOT_AGENT_FALLBACK_TOKENS` to change that reserve; it must
cover at least one maximum-length response. The reserve stays inside the task's
overall token cap. If the primary model reaches its share of the budget, the next
request runs on the fallback model. Provider throttling and availability errors
continue to trigger fallback as before.
Rejected primary requests release their token reservation before fallback, so they
do not consume the task token budget.

The agent also bounds each serialized model request to 18,000 characters by
default (`ADBOT_AI_MAX_REQUEST_CHARS`). It prioritizes the goal, current URL,
visible page text, and controls, then removes supplementary accessibility and
old-memory data if needed. This prevents oversized observations from reaching
the provider and triggering HTTP 413.
For Docker, use a host address reachable inside the backend container instead of
`127.0.0.1`.

`ADBOT_AI_PROVIDER=disabled` preserves crawl/workflow functionality without an
LLM. Agent creation then returns 503 with configuration instructions. Enabling a
provider requires a model ID and, except for local endpoints, its API key at
startup. Restart both the API and worker after changing provider settings.

## Run processes

From `backend/`, using the virtual environment's Python, in separate terminals:

```sh
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.worker
python -m app.scheduler
```

For Windows, replace `python` with `..\.venv\Scripts\python`; on Linux/macOS
use `../.venv/bin/python`. From `frontend/`, run `npm run dev`.

Open **http://127.0.0.1:5173**, connect with `ADBOT_API_KEYS` (your workspace
authentication key, not the LLM key), and choose **AI Agent**.

1. Select a registered target or enter a new starting URL and confirm authorization.
2. Enter an objective, for example: “Find the launch month for Orion AI and cite
   the source.” Optionally specify separate completion criteria, one per line.
3. Choose assisted, autonomous or supervised mode. Set a step limit. Enable text
   input/search, downloads, memory, vision or encrypted session persistence as needed.
4. Start the task. Inspect actual browser captures, current URL, semantic
   decisions, model usage, tabs, action outcomes and session memory.
5. Review non-click actions in assisted mode, reply to questions, or
   pause/resume/stop the task. Review waits consume the task's original deadline.
6. Read the final claims, exact source quotes and criterion verification. Failed
   or budget-limited runs remain failed; they are not reported as completed.

Existing target settings govern browser engine, headed/headless mode, robots
handling, page limit, navigation timeout, session duration and allowed domains.
Add needed resource hosts explicitly in **Websites → Configure**. New targets
created from the agent panel allow only the starting hostname, use 30 pages and a
900-second session budget. All clicks execute autonomously in every mode,
including consequential buttons and form submissions.

Existing deployments with `ADBOT_AGENT_MAX_STEPS=30` must update that setting to
`500` and restart the API and workers to expose the increased limit. Step limits
do not override the task's token, page or session-duration budgets.

## How execution works

The agent observes bounded main/viewport text, headings, semantic controls and an
accessibility snapshot. It assigns observation-local element IDs, preferring
Playwright role/name locators. The model returns a strict JSON decision; a
controlled action registry executes it. No generated Python, JavaScript or CSS
selector is executed. Re-observation records actual outcomes before continuing.

Navigation, click, type, GET search, scrolling, tab open/switch/close, back,
observe, wait, quote extraction, cited summarization, bounded download, ask-user,
complete and fail actions are supported. Search is limited to observed GET
search forms. Form input must be enabled for a task. Secret/payment/file inputs
are unavailable. Clicks do not request approval. An observed non-GET form click
permits one matching method and destination through the request boundary. A
JavaScript button without a non-GET form permits one policy-checked write during
the click, expiring after five seconds or when the action finishes. Other assisted
actions and explicit ASK_USER questions still wait for a response.
Review approval is rejected as stale when the observed page or form state changes.

Downloads use explicitly observed links through the validated proxy, enforce
allowlists and redirect checks, and stop at 10 MiB. Files are stored as generated
`.bin` attachments and served through the authenticated artifact API. Native
browser downloads and unexpected popups remain disabled.

`EXTRACT` accepts only a contiguous quote from the current observed text. Final
claims must cite collected evidence IDs. A separate model request evaluates
every original success criterion, and deterministic checks reject absent evidence,
unmatched criteria or a negative verification. This provides an inspectable
model verification with grounded source material, not a mathematical guarantee
that every model interpretation is correct.

Transient page data, recent actions and failed attempts form short-term memory.
URL/tab history, quotes, answers and outcomes persist as session memory. Successful
cited results become workspace-and-target-scoped long-term memories with retention
and explicit deletion. Historical memories are hints and must be checked against
current pages. Text relevance ranks prior results; no vector database is needed.

Recovery restores recorded URLs and optional encrypted browser state, then
re-observes and replans. It does not reconstruct arbitrary JavaScript application
state. Ambiguous in-flight clicks, typing and submissions fail for manual review.
Read-only interrupted steps can recover within the existing worker retry budget.
Independent tasks own separate browser contexts and share existing SQL capacity
and domain leases.

## New modules and migration

| Module | Responsibility |
| --- | --- |
| `app/agent/contracts.py` | Validated task, action, review and completion schemas |
| `app/agent/model.py` | Provider transport, JSON validation, retries, token accounting, optional images |
| `app/agent/observe.py` | Main/viewport text, accessibility, semantic elements, form-state fingerprints |
| `app/agent/controller.py` | Controlled actions, tabs, autonomous submissions and bounded downloads |
| `app/agent/runner.py` | Observe/decide/act/verify/remember loop and completion checks |
| `app/agent/memory.py` | Memory relevance/isolation and encrypted browser state |
| `app/agent/api.py` | Task, review, memory, configuration and metrics endpoints |
| `app/api_support.py` | Shared authentication, ownership and pagination helpers |
| `frontend/src/AgentPanel.tsx` | Connected task workspace and history |

Migration **`37745660af92`**, following `bafc4dc14d9a`, adds `agent_tasks`,
`agent_steps` and `agent_memories`, including foreign keys, ownership indexes,
expiry indexes and unique task/step numbers. Existing APIs and tables remain.
Agent task ID and stable logical session ID are the underlying job UUID.

## Configuration reference

All names below have the `ADBOT_` prefix.

| Variable | Default / purpose |
| --- | --- |
| AI_PROVIDER | `disabled`, `groq`, `openai_compatible` or `local` |
| AI_MODEL | Required when enabling a provider |
| AI_BASE_URL / AI_API_KEY | Generic compatible endpoint and secret |
| GROQ_BASE_URL / GROQ_API_KEY | Groq endpoint and secret |
| AI_TIMEOUT_SECONDS | `30`; 1–120 seconds per HTTP request |
| AI_RETRIES | `2`; bounded transport retries |
| AI_MAX_OUTPUT_TOKENS | `1800`; maximum per model response |
| AI_JSON_MODE | `true`; sends `response_format: json_object` |
| AGENT_MAX_STEPS | `500`; server ceiling, max 500 |
| AGENT_MAX_TOKENS | `60000`; token budget ceiling |
| AGENT_MAX_TABS | `4`; maximum simultaneous tabs |
| AGENT_MAX_RETRIES | `3`; consecutive action/model recovery failures |
| AGENT_MEMORY_ENABLED | `true`; permit reusable memories |
| AGENT_VISUAL_REASONING | `false`; permit screenshot input to a vision-capable model |
| BROWSER_SESSION_PERSISTENCE | `false`; permit encrypted cookies/local storage checkpoints |
| SESSION_ENCRYPTION_KEY | Fernet key; required when enabling session persistence |

Use a vision-capable model before enabling images; text-only models may reject
image inputs. Image delivery is optional and downscaled before model requests.
The initializer generates a session key for new `.env` files. To add one to an
existing deployment:

```sh
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Place it in `.env` securely. It is never exposed by the API. Keep it with encrypted
backups; losing/rotating it prevents decryption of older session checkpoints.
Screenshots and extracted page content may still contain target information;
session encryption does not encrypt every artifact. Provider requests send the
observed content you authorize to the configured model service.

The worker reserves a conservative token estimate before each request, including
ambiguous retry attempts, and adjusts with provider-reported usage when available.
Missing usage retains the reservation. Token budgets are not dollar-denominated
billing caps. Review waits, backoffs and model calls also share the original
maximum session duration.

## API additions

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/api/agent/config` | Sanitized provider readiness and limits |
| POST / GET | `/api/agent/tasks` | Enqueue / paginate tasks |
| GET | `/api/agent/tasks/{id}` | Status, objective, usage, memory and result |
| GET | `/api/agent/tasks/{id}/steps` | Observations, decisions and actual outcomes |
| POST | `/api/agent/tasks/{id}/review` | Approve/decline the pending step and supply a reply |
| GET / DELETE | `/api/agent/memories` / `/api/agent/memories/{id}` | Inspect / forget reusable knowledge |
| GET | `/api/agent/metrics` | Success, duration, step and usage metrics |

Use existing `/api/jobs/{id}/pause`, `/resume`, `/cancel`, `/events`, `/logs`,
`/pages` and authenticated `/api/artifacts/{filename}` endpoints. Task creation
supports `Idempotency-Key` with payload-conflict checks. Reviews include the
exact pending `step_id` and reject stale/already answered requests.

```json
{
  "website_id": "REGISTERED_TARGET_UUID",
  "objective": "Find the most recent AI release and cite its source.",
  "mode": "supervised",
  "max_steps": 20,
  "max_tokens": 60000,
  "allow_form_input": false,
  "allow_downloads": false,
  "memory_enabled": true
}
```

## Tests and local demonstration

From `backend/`, with dependencies and Chromium installed:

```sh
python -m pytest -q
python -m pytest -q tests/test_agent.py
python -m alembic upgrade head
python -m alembic check
```

From `frontend/`:

```sh
npm test
npm run build
npm run test:e2e
```

The end-to-end runner needs free ports **8000, 5173, 8765, 8766**. It starts
real browsers and a local OpenAI-compatible **model test double**, whose choices
depend on the current observation and goal. It is deliberately not represented
as a live LLM. Fixtures cover news, changed link order, a dynamic page, documentation
search, a product catalog without checkout, an autonomous multistep form, and downloads.

For a live-model local demonstration, configure your actual provider, enable
development fixture mode, start `app.fixture:app` on loopback port 8765, and use
the AI Agent panel with URL `http://127.0.0.1:8765/agent/news` and objective
“Find the launch month for Orion AI and cite the source.” The model should discover
the article, quote its launch statement and return a cited result. Fixture mode
is prohibited in production.

See `AGENT_VERIFICATION.md` for executed results and limits. Docker/production,
native Windows execution and live provider quality must be validated in those
environments. The earlier production egress/sandbox guidance remains applicable.
