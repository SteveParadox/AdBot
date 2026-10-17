# AdBot Monitor

An authorized website automation workspace with a React dashboard, FastAPI API,
isolated Playwright browsers, a durable SQL crawl frontier, schedules, and live
execution events. This repository implements the attached browser-monitoring
specification. Its name does not imply ad interaction: it does not click ads or
generate artificial engagement.

**Goal-driven AI browsing is now available.** Open the **AI Agent** workspace to
submit a natural-language objective, inspect live decisions/captures and retrieve
cited results. Configure Groq, another compatible provider or a local model using
the [agent setup guide](docs/AGENT_GUIDE.md). Existing crawls work with AI disabled.

## Start locally on Windows

Install Python 3.12+ and Node.js 22.12+ (or Node 24). Run from the repository root
in **Command Prompt**:

```bat
python -m venv .venv
.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
.venv\Scripts\python -m playwright install chromium firefox webkit
python scripts\init_env.py
cd backend
..\.venv\Scripts\python -m alembic upgrade head
..\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep that terminal open. In a second terminal from the repository root:

```bat
cd backend
..\.venv\Scripts\python -m app.worker
```

In a third terminal:

```bat
cd backend
..\.venv\Scripts\python -m app.scheduler
```

In a fourth terminal:

```bat
cd frontend
npm ci
npm run dev
```

Open **http://127.0.0.1:5173** and enter `ADBOT_API_KEYS` from the generated
root `.env`. Do not enter the variable name; paste its generated value. Each
process reads the same `.env` when started from `backend/`. SQLite stores data in
`backend/adbot.db`, and captures go in `backend/data/screenshots/`.

**PowerShell:** the same commands work without activating the virtual environment;
prefix Python paths with `&` if your shell requires it. No execution-policy change
is necessary. For example:

```powershell
cd backend
& ..\.venv\Scripts\python.exe -m app.worker
```

If port 8000 is reserved on Windows, use `--port 8001` and change the Vite proxy
destination in `frontend/vite.config.ts` to the same port.

## Linux / macOS

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m playwright install --with-deps chromium firefox webkit
.venv/bin/python scripts/init_env.py
cd backend
../.venv/bin/python -m alembic upgrade head
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In separate terminals, from `backend/`, run
`../.venv/bin/python -m app.worker` and
`../.venv/bin/python -m app.scheduler`. From `frontend/`, run `npm ci` then
`npm run dev`. On Linux, browser OS dependencies require package-install privileges.
On macOS, omit `--with-deps` if platform dependency installation is unavailable.

## First job

1. Connect using your workspace API key.
2. Open **Websites → Add website**. Enter a starting URL, explicit allowed
   hostnames, page/depth limits, and a delay. Confirm your authorization.
3. Include resource hosts in the allowlist if the target needs a CDN. Wildcards
   must be explicit, for example `*.example.com`; `example.com` alone includes
   only that exact hostname.
4. Keep robots compliance enabled for crawling. Enable screenshots or scrolling
   in the browser options if needed.
5. Open **Jobs**, choose the website, and start a crawl. Inspect its progress,
   page results, HTTP statuses, events, and captures.
6. Build a workflow for ordered read-only checks, or create a schedule with your
   timezone. Pause/resume takes effect between actions or page visits. Session
   deadlines continue running while paused.

Targets require authorization. Production additionally requires an operator
allowlist. HTTP/HTTPS are the only supported protocols. Standard ports, public IPs,
domain boundaries and redirects are checked. All subresources must also belong to
the target allowlist. Forms, non-GET/HEAD requests, downloads, popups, sockets and
unapproved clicks are blocked.

## Docker

```sh
python scripts/init_env.py
docker compose up -d --build --wait
docker compose logs -f worker scheduler
```

Open **http://127.0.0.1:8080**. Compose runs PostgreSQL, Redis, migrations, API,
worker, scheduler and Nginx frontend. Database and artifact volumes persist across
restarts. Only the frontend is published, bound to loopback. Docker Desktop with
Linux containers works on Windows. `docker compose down` stops the stack while
preserving volumes.

Before production set `ADBOT_ENVIRONMENT=production` and
`ADBOT_AUTHORIZED_DOMAINS` to your approved domains in `.env`, configure TLS and
external egress controls, and follow [operations guidance](docs/OPERATIONS.md).
Compose supplies PostgreSQL and Redis URLs regardless of local SQLite settings.
The browser image is large; reserve capacity for browser processes and shared
memory. Compose caps the worker at 2 GiB and 2 CPUs; validate limits with your own
pages before increasing concurrency.

## Tests

From `backend/`:

```sh
../.venv/bin/python -m pytest -q
../.venv/bin/ruff check app tests
../.venv/bin/python -m alembic check
```

Windows substitutes `..\.venv\Scripts\python` and
`..\.venv\Scripts\ruff`. Tests create isolated temporary databases and a
loopback-only fixture. Real-browser tests require Chromium installed. Run just
non-browser checks with `python -m pytest -q -m "not browser"`.

From `frontend/`:

```sh
npm test
npm run build
npm run test:e2e
```

The end-to-end runner starts its own API, worker, scheduler, fixture and Vite
server, uses a temporary database, and shuts them down. Ports **8000, 5173, 8765**
must be free. It expects the root `.venv` and installed frontend dependencies.
For an interactive manual fixture, set `ADBOT_FIXTURE_MODE=true` in a development
`.env`, restart the API and worker, and run from `backend/`:

```sh
../.venv/bin/python -m uvicorn app.fixture:app --host 127.0.0.1 --port 8765
```

Register `http://127.0.0.1:8765/` with allowed domain `127.0.0.1`.
Only that exact loopback address/port is exempted; other internal addresses remain
blocked. Fixture mode is forbidden in production.

## Project guide

- [Configuration, deployment, security and troubleshooting](docs/OPERATIONS.md)
- [API and workflow reference](docs/API.md)
- [Architecture and durability](docs/ARCHITECTURE.md)
- [Implementation verification report](docs/VERIFICATION.md)
- [Agent architecture, provider setup and operation](docs/AGENT_GUIDE.md)
- [Agent implementation audit](docs/AGENT_IMPLEMENTATION_MAP.md)
- [Agent verification and limitations](docs/AGENT_VERIFICATION.md)
- [Natural interaction actions, traces and analytics](docs/INTERACTION_ENGINE.md)
- OpenAPI: http://127.0.0.1:8000/docs during local development.

The initial release is a runnable monitoring platform. Production certification
requires validation of the actual PostgreSQL/Redis deployment, browser egress
rules, backup restoration, capacity, and all selected browser engines. See the
verification report for checks that were actually executed.
