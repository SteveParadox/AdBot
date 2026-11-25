export type DocSection = { id: string; title: string; paragraphs: string[]; steps: string[] };
export type DocPage = { slug: string; title: string; group: string; description: string; sections: DocSection[] };

export const docs: DocPage[] = [
  {
    slug: "web-research",
    title: "Web Research",
    group: "Workspace tools",
    description: "Ask a question, compare products and inspect the public sources behind the answer.",
    sections: [
      {id: "start", title: "Start a research conversation", paragraphs: [
        "Open Web Research in the dashboard and enter a question. AdBot discovers relevant public sources using the search providers your operator configured."
      ], steps: ["Choose Auto for routing, or choose a specific research mode.", "Use the country and freshness controls to narrow the search.", "Expand Sources and evidence to inspect the quotations, source URLs and retrieval times."]},
      {id: "modes", title: "Choose a mode", paragraphs: [
        "Direct Answer uses the configured model without web retrieval. Quick Search limits search and page retrieval. Deep Research runs additional bounded rounds. Shopping extracts supported product offers. Fact Check looks for independent sources. Technical Research prioritizes technical references. Website Agent opens the existing authorized browser workspace."
      ], steps: []},
      {id: "quality", title: "Interpret results", paragraphs: [
        "Inline numbers link to supporting sources. Partial results may contain retrieved excerpts, missing publication dates or sources that could not be accessed. Product prices and availability reflect the retailer data recorded at the retrieval time. Country and currency hints are distinct from a retailer's stated shipping destination."
      ], steps: []},
      {id: "continue", title: "Continue, stop or retry", paragraphs: [
        "Select a saved conversation to continue it. Use Stop to cancel active work, or Retry to repeat a cancelled, failed or partial turn. AdBot rechecks time-sensitive sources when their cache expires."
      ], steps: []}
    ]
  },
  {
    "slug": "introduction",
    "title": "Welcome to AdBot",
    "group": "Start here",
    "description": "Understand the workspace and choose the right tool for your task.",
    "sections": [
      {
        "id": "section-1",
        "title": "What AdBot does",
        "paragraphs": [
          "AdBot brings authorized website monitoring, browser automation, AI-assisted research and structured data collection into one workspace. Register a target, run a task, then inspect the evidence and results."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Choose your tool",
        "paragraphs": [
          "Websites defines where a browser may go. Jobs launches crawls or saved workflows. Workflows stores repeatable browser steps. Schedules creates recurring or one-time work. AI Agent handles natural-language objectives. Data Extraction turns page content into records."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Understand the workspace",
        "paragraphs": [
          "Overview summarizes activity and execution health. Content manages published copy, User-Agent settings and routing diagnostics. Automation provides administrator controls over queues, workers and runtime policy. These guides describe the dashboard; administrator-only features still require an authorized key."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "How a run works",
        "paragraphs": [
          "The API saves a job, a worker claims it and operates an isolated browser, and the dashboard displays stored results and live progress. The scheduler enqueues due work; it does not run browsers. A queued job needs an available worker."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "quick-start",
    "title": "Your first successful run",
    "group": "Start here",
    "description": "Connect, register a website and inspect a crawl.",
    "sections": [
      {
        "id": "section-1",
        "title": "Connect your workspace",
        "paragraphs": [
          "Open the app and enter the actual workspace API key supplied by your operator. Keys must have at least 32 characters. The browser stores the key for the current session; Disconnect removes it. Never paste provider keys into this form."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Register and run",
        "paragraphs": [],
        "steps": [
          "Open Websites and choose Add website. Enter a name and starting URL for a target you are authorized to automate.",
          "Set explicit allowed domains, conservative page/depth limits and a delay. Include approved resource hosts required by the page. Confirm authorization and save.",
          "Open Jobs, choose the website and Link-discovery crawl, then launch.",
          "Open the run to inspect its status, execution events, visited URLs, HTTP responses and screenshots when enabled."
        ]
      },
      {
        "id": "section-3",
        "title": "Continue from your results",
        "paragraphs": [
          "Use Workflows for a repeatable sequence, Schedules for periodic checks, AI Agent for a goal-driven task, or Data Extraction for reusable records. If the job stays queued, consult Troubleshooting before launching duplicates."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "overview",
    "title": "Overview and workspace navigation",
    "group": "Workspace",
    "description": "Read activity summaries and find your work.",
    "sections": [
      {
        "id": "section-1",
        "title": "Read the overview",
        "paragraphs": [
          "Overview shows registered targets, execution summaries, recent runs, page activity and HTTP responses. Change the activity period to compare recent behavior. Click a summary or run to inspect the underlying work. A completed job does not by itself prove the business objective was achieved; check its results."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Find and refresh",
        "paragraphs": [
          "Use workspace search to open a section or add a website. Refresh workspace reloads active data. Compact view changes information density and is remembered in this browser. API unavailable and Offline indicators identify connection problems."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Workspace ownership",
        "paragraphs": [
          "Ordinary jobs and records are scoped to the connected key. Global administration is a separate permission and does not grant access to other keys’ private jobs. Disconnect before sharing the device."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "websites",
    "title": "Websites and crawl settings",
    "group": "Workspace",
    "description": "Define authorized targets and browser boundaries.",
    "sections": [
      {
        "id": "section-1",
        "title": "Register a target",
        "paragraphs": [],
        "steps": [
          "Choose Add website, enter the website name and starting URL, and list permitted hosts separated by commas.",
          "Set maximum pages, depth and delay between pages. Start small to verify behavior.",
          "Choose browser engine, viewport, loading condition and optional selector wait. Configure captures and scrolling as needed.",
          "Review authorization and robots settings, then save."
        ]
      },
      {
        "id": "section-2",
        "title": "Allowed domains and URL patterns",
        "paragraphs": [
          "example.com permits that exact host; *.example.com explicitly permits subdomains. Add approved CDN/resource hosts needed for rendering. Allowed and excluded URL globs narrow the crawl further; they do not expand the operator’s domain authorization. Production also enforces ADBOT_AUTHORIZED_DOMAINS."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Browser compatibility",
        "paragraphs": [
          "Choose Chromium, Firefox or WebKit according to the target. Waiting for a selector can help with dynamic content. Page/depth/time limits still apply. A User-Agent string does not change the underlying browser engine."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Manage targets",
        "paragraphs": [
          "Search registered websites and switch grid/list views to locate a target. Edit settings before the next run and inspect existing jobs separately; changing a target is not a substitute for cancelling active work."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "jobs",
    "title": "Jobs, evidence and run controls",
    "group": "Workspace",
    "description": "Launch work and understand its outcome.",
    "sections": [
      {
        "id": "section-1",
        "title": "Launch a job",
        "paragraphs": [
          "Choose a registered website and either Link-discovery crawl or a saved workflow for that target. Optional priority ranges from -10 to 10. A required successful job ID creates a dependency; dependent work waits for that prerequisite."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Read run status",
        "paragraphs": [
          "Queued work is persisted but may be waiting for capacity, a dependency, manual release or an enabled worker. Running work has been claimed. Completed, failed and cancelled are terminal outcomes. Filter run history by status and open a run for details."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Inspect the evidence",
        "paragraphs": [
          "Visited pages include URLs and HTTP outcomes; filter or search them when diagnosing missing content. Execution events explain progress and failures. Captures show browser output when enabled. Inspect partial results even when a run fails."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Pause, cancel and retry",
        "paragraphs": [
          "Available controls depend on run status. Pause/resume occurs at safe boundaries, and elapsed session deadlines continue while paused. Cancellation cannot undo requests already sent. Review partial results before retrying an operation with side effects."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "workflows",
    "title": "Reusable workflows",
    "group": "Workspace",
    "description": "Save a sequence of browser actions for repeatable work.",
    "sections": [
      {
        "id": "section-1",
        "title": "Build a workflow",
        "paragraphs": [],
        "steps": [
          "Open Workflows and enter a name and registered website.",
          "Add actions in execution order. Supply the selector, allowed URL, wait duration, expected text or scroll amount required by each action.",
          "Set appropriate action timeouts and remove unnecessary steps. Save the workflow.",
          "Select the workflow in Jobs for a small trial run, then inspect events and captures before scheduling it."
        ]
      },
      {
        "id": "section-2",
        "title": "Choose stable targets",
        "paragraphs": [
          "Prefer stable selectors that identify the intended element. A navigation URL must remain inside the website’s authorization boundary. Assertion steps help detect page changes instead of silently continuing with an incorrect assumption."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Run repeatedly",
        "paragraphs": [
          "Workflows can be selected by Jobs or Schedules. Repeating a workflow repeats its actions, so verify whether it submits forms or changes external state before enabling a recurring schedule."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "schedules",
    "title": "Schedules and recurring checks",
    "group": "Workspace",
    "description": "Queue work at the right time and timezone.",
    "sections": [
      {
        "id": "section-1",
        "title": "Create a schedule",
        "paragraphs": [],
        "steps": [
          "Open Schedules and select a website plus either Crawl or a saved workflow.",
          "Choose hourly, daily, weekly, custom cron or one time. For custom recurrence, enter a five-field cron expression.",
          "Set the schedule timezone explicitly. The one-time input is shown in your browser’s local time. Review the next-run time and enabled state.",
          "Save and keep both scheduler and worker services running."
        ]
      },
      {
        "id": "section-2",
        "title": "Timezone example",
        "paragraphs": [
          "For Nigerian business hours, select Africa/Lagos. A cron expression of 0 8 * * * means 08:00 every day in the schedule’s selected timezone. Check timezone and next-run time when a check appears late."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Scheduling and execution",
        "paragraphs": [
          "The scheduler only queues due jobs. Worker availability, capacity, dependencies and global automation policy determine when execution starts. Inspect Jobs for the actual outcome, and disable a recurring schedule when it is no longer needed."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "ai-agent",
    "title": "AI Agent and task planning",
    "group": "Workspace",
    "description": "Give the browser a clear goal and review verified results.",
    "sections": [
      {
        "id": "section-1",
        "title": "Submit an objective",
        "paragraphs": [],
        "steps": [
          "Ensure an operator has configured an AI provider, model and credentials on the server. Crawls can work without AI.",
          "Open AI Agent. Select an existing target or register a new URL, then write a specific objective with a clear stopping point.",
          "Choose an autonomy mode, maximum steps and optional success criteria. Set priority or a required successful job ID if needed.",
          "For structured output, choose a dataset belonging to the target and the required output format. Start the task and follow its plan and events."
        ]
      },
      {
        "id": "section-2",
        "title": "Write a useful objective",
        "paragraphs": [
          "Example: “Open the authorized product listing, collect the first ten product names and displayed prices, and return a cited answer with source URLs. Stop after ten records.” Include scope, required fields and success criteria. The server still enforces step, time, token and permission budgets."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Observe and respond",
        "paragraphs": [
          "The task view includes browser preview, current decision, tabs/context, plan, recovery details and semantic diagnostics. When the task asks for review or additional instruction, read the pending action and use the displayed controls. Autonomy mode does not bypass destination policies or server restrictions."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Evaluate the answer",
        "paragraphs": [
          "Inspect Verified task result and Observed actions and verification. Confirm evidence and citations support the requested result. A fluent model response is not sufficient evidence. Inspect task history and reusable task memory before repeating a similar task."
        ],
        "steps": []
      },
      {
        "id": "section-5",
        "title": "Model failures",
        "paragraphs": [
          "Invalid structured output, provider quotas, unavailable models and exhausted budgets can stop a task. An operator may configure an approved local fallback. No local model is bundled or downloaded automatically; inspect failure details before increasing limits."
        ],
        "steps": []
      },
      {
        "id": "autonomy-modes",
        "title": "Choose an autonomy mode",
        "paragraphs": [
          "Supervised mode offers live progress and intervention. Autonomous mode enables clicks and browsing. Assisted mode keeps clicks autonomous while other actions may require review. Clicks do not automatically require sensitive-action approval; other permissions and server policies still apply. Read any pending review before responding."
        ],
        "steps": []
      },
      {
        "id": "optional-capabilities",
        "title": "Forms, downloads and visual reasoning",
        "paragraphs": [
          "Enable Allow form input and search only when the task needs it. Allow bounded downloads opts into permitted downloads within server limits. Vision-capable model is available only when the operator enables visual reasoning and configures a compatible model. Disabled options require operator configuration; selecting a mode does not enable them."
        ],
        "steps": []
      },
      {
        "id": "memory-and-sessions",
        "title": "Reusable memory and encrypted sessions",
        "paragraphs": [
          "Reuse successful task memory uses prior successful, cited results scoped to this workspace and target; historical hints are checked against current pages. Inspect stored hints under Reusable task memory and use Forget memory to delete an entry.",
          "Encrypted browser session is available only when enabled by the operator. It can preserve sensitive browser state, so use it only for the intended target and keep the server encryption key protected. Task memory and browser-session persistence serve different purposes."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "data-extraction",
    "title": "Schemas, datasets and exports",
    "group": "Workspace",
    "description": "Turn website content into versioned, reusable records.",
    "sections": [
      {
        "id": "section-1",
        "title": "Create an extraction schema",
        "paragraphs": [],
        "steps": [
          "Open Data Extraction and choose a built-in template or create a schema.",
          "Define fields, types, extraction methods and selectors or paths. Supported methods in the builder include CSS, XPath, JSON-LD, metadata, source URL, page title and AI.",
          "Choose identity fields in Schema JSON for record identity/deduplication, and set required fields and normalization as appropriate.",
          "Validate the schema, then create it. Editing a saved schema creates a new immutable version."
        ]
      },
      {
        "id": "section-2",
        "title": "Create and run a dataset",
        "paragraphs": [
          "Create a named dataset tied to a registered website and saved schema. Review the dataset options before saving. Select the dataset and run extraction; use its records, changes and runs panels to inspect valid/invalid counts, provenance and failures. AI extraction requires a configured provider."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Monitor changes",
        "paragraphs": [
          "Identity fields let the system compare records across runs. Inspect the changes panel for recorded changes, and the runs panel for partial failures and usage. A missing record can also reflect a selector change or failed page load; verify evidence before interpreting it as a real-world deletion."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Export JSON or CSV",
        "paragraphs": [
          "Open the exports panel, choose a format and any filters, sort, limit or columns, then queue an export. Wait for completion before downloading. Exports have expiry information; regenerate an expired export. Downloads require the owning workspace key."
        ],
        "steps": []
      },
      {
        "id": "section-5",
        "title": "Use extraction in agent tasks",
        "paragraphs": [
          "Select an owned dataset for the same website in AI Agent and choose JSON or CSV output. Scheduled extraction retains its dataset association; use the dataset’s scheduling controls and check subsequent runs."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "content",
    "title": "Content and publication",
    "group": "Administration",
    "description": "Edit public copy and publish revisions.",
    "sections": [
      {
        "id": "section-1",
        "title": "Administrator access",
        "paragraphs": [
          "Content requires a valid workspace key that the operator also lists in ADBOT_CONTENT_ADMIN_KEYS. Ordinary keys cannot gain this role from the dashboard. Global copy changes can affect all visitors."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Edit and publish",
        "paragraphs": [],
        "steps": [
          "Select a content section or choose New section. Edit its title, description and any supported image/link fields.",
          "Inspect the preview and choose draft, published or archived.",
          "Save the loaded revision. If another administrator changed it first, preserve your draft, reload and reconcile the edits."
        ]
      },
      {
        "id": "section-3",
        "title": "Publication states",
        "paragraphs": [
          "Draft stores changes while keeping the previous public snapshot. Published replaces the public snapshot. Archived hides the section; Delete removes it. Reserved sections control login, page copy and SEO. Custom sections appear on the login page; ordering controls their placement."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Media and refresh",
        "paragraphs": [
          "Use supported local or HTTPS image/link URLs and descriptive alternative text. There is no upload library. Public content refreshes every 30 seconds, and editor writes invalidate that browser’s cache immediately. SEO metadata is client-rendered. Navigation labels can differ from page headings."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "user-agents",
    "title": "User-Agent profiles",
    "group": "Administration",
    "description": "Manage outbound identities and browser compatibility.",
    "sections": [
      {
        "id": "section-1",
        "title": "Manage identities",
        "paragraphs": [
          "Open Content > User-Agent management, or the User-Agent section in Automation. Edit the global string, manage profiles and assign service overrides. Preview and save the revision. Referenced profiles must be unassigned before deletion, and the application-default profile is protected."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Validation and precedence",
        "paragraphs": [
          "Values must be nonempty printable ASCII with no leading/trailing whitespace or control characters, within the configured length. Required operator identities take precedence, followed by authorized request overrides, service custom values, enabled profiles, the global value and application default. Disabled settings fall back."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "When changes apply",
        "paragraphs": [
          "Revision watchers propagate saved changes, with a five-second read-cache fallback. Existing browser contexts keep a stable identity for browsing, robots and downloads. Open a new context to observe a newly selected identity. A User-Agent change does not change browser engine or TLS behavior."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Pools and conflicts",
        "paragraphs": [
          "Automated selection pools require explicit operator permission and compatible routing policy. Coordination occurs when a new context is created. For a 409 conflict, reload and reconcile edits; for a 422 validation error, check the message, references and policy restrictions."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "network",
    "title": "Network routing and diagnostics",
    "group": "Administration",
    "description": "Understand approved proxies, route health and connection failures.",
    "sections": [
      {
        "id": "section-1",
        "title": "Read routing health",
        "paragraphs": [
          "Content > Network routing and Automation’s Network health section show routing diagnostics. With Redis, expiring process heartbeats aggregate worker/API information; without Redis, the dashboard reports API-process information only. A healthy API route does not prove a worker route is healthy."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Operator configuration",
        "paragraphs": [
          "Outbound protection and rotation are off by default. Approved HTTP(S) CONNECT endpoints and service policies are configured in a private server-side JSON file. Enable ADBOT_OUTBOUND_PROXY_ENABLED and set ADBOT_OUTBOUND_PROXY_CONFIG_PATH, validate with python -m app.outbound --check from backend, then restart API/workers. Keep credentials out of published copy and browser forms."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Routing behavior",
        "paragraphs": [
          "Required proxy services fail closed rather than silently switching direct. Stable sessions retain their assigned route. Circuit breakers and bounded failover handle approved connection failures; target denials and HTTP 429 do not authorize identity rotation or mutation replay. SOCKS and remote DNS are unsupported."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Diagnose failures",
        "paragraphs": [
          "Check approved health URL, credentials, proxy CA/TLS, CONNECT support, cooldown and service policy. Verify actual exit addresses using controlled target/provider records. Cloudflare Tunnel is an inbound connector and is configured separately from outbound proxies."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "automation",
    "title": "Automation Control Center",
    "group": "Administration",
    "description": "Control queue policy and inspect worker health.",
    "sections": [
      {
        "id": "section-1",
        "title": "Inspect the control center",
        "paragraphs": [
          "Automation requires administrator access. It shows global queue counts, workers, scheduler heartbeats, leased browser sessions, recent events and policy history. Recent job actions remain scoped to your own workspace."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Control execution",
        "paragraphs": [
          "Enable automatic pickup to allow eligible queued work to be claimed; manual mode requires release. Pause waits at safe action boundaries. Emergency stop cancels queued/active work and cannot undo requests already sent. Clearing the stop does not restore cancelled jobs."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Set operating limits",
        "paragraphs": [
          "Adjust concurrent jobs, recovery attempts, queue capacity and health interval within operator limits. Apply operating limits or review the advanced JSON policy. Saves use revision protection; if policy changes while editing, preserve your draft and reload before saving. Previously approved policies can be loaded for review."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Worker health and recovery",
        "paragraphs": [
          "Connected worker cards show leases and optional fallback warm-up state. Concurrency diagnostics show active work, I/O, CPU, memory and backpressure where available. No connected workers means no browser execution. Review ambiguous or partially executed actions before retrying; agent tasks require a new explicit launch."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "installation",
    "title": "Installation and configuration",
    "group": "Operations",
    "description": "Run the API, workers, scheduler and dashboard.",
    "sections": [
      {
        "id": "section-1",
        "title": "Prerequisites",
        "paragraphs": [
          "Use Python 3.12+, Node.js 22.12+ or a compatible newer release, npm and Git. Install Playwright browser binaries and OS dependencies. Docker Desktop must use Linux containers. Full platform-specific commands are maintained in the repository README linked below."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Local setup",
        "paragraphs": [],
        "steps": [
          "Clone the repository and create a Python virtual environment. Install backend/requirements-dev.txt and Playwright Chromium, Firefox and WebKit.",
          "Run python scripts/init_env.py from the root to create private configuration only when absent. Preserve existing secrets when merging new example settings.",
          "Run npm ci from frontend. From backend, apply python -m alembic upgrade head using your virtual environment.",
          "From backend, run the API with python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --no-server-header --no-access-log.",
          "In separate terminals from backend, run python -m app.worker and python -m app.scheduler. From frontend, run npm run dev. Open http://127.0.0.1:5173."
        ]
      },
      {
        "id": "section-3",
        "title": "Configure access",
        "paragraphs": [
          "The private root .env defines ADBOT_API_KEYS, database connection and optional providers. Add authorized administrator keys to ADBOT_CONTENT_ADMIN_KEYS. Backend commands run from backend because settings load ../.env. Vite proxies /api to port 8000; set ADBOT_API_PROXY_TARGET if your API uses a different port."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "AI configuration",
        "paragraphs": [
          "Configure groq with ADBOT_GROQ_API_KEY, ADBOT_GROQ_BASE_URL and ADBOT_AI_MODEL; openai_compatible/local use ADBOT_AI_BASE_URL, ADBOT_AI_API_KEY and ADBOT_AI_MODEL. Choose a model your provider supports. Remote providers require HTTPS. Restart API and worker after configuration changes."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "deployment",
    "title": "Deployment, backups and recovery",
    "group": "Operations",
    "description": "Operate the services and preserve durable data.",
    "sections": [
      {
        "id": "section-1",
        "title": "Docker deployment",
        "paragraphs": [
          "Generate or merge private configuration first. Configure approved production targets in ADBOT_AUTHORIZED_DOMAINS and the real incoming hostnames/CORS origins. Run docker compose config --quiet, then docker compose up -d --build. Inspect docker compose ps and API/worker/scheduler logs."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Service boundaries",
        "paragraphs": [
          "Compose uses production mode, PostgreSQL/Redis and fixture mode off. Host port 5173 reaches frontend Nginx on loopback; API/database/Redis remain internal. Migrations run before application startup. The base HTTP stack requires a verified TLS edge or the configured Cloudflare Tunnel overlay before public use."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Back up and restore",
        "paragraphs": [
          "Back up SQL data, artifacts, required private configuration and session encryption keys before migrations. Use PostgreSQL-consistent backups; stop SQLite writers or use its backup API. Restore into an isolated environment and verify history, artifacts and encrypted-session access."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Upgrade and rollback",
        "paragraphs": [
          "Deploy matching migrations, API, workers and scheduler together. Inspect alembic current/history and review destructive downgrades before rollback. Compose shutdown preserves volumes by default; removing volumes deletes durable data. Keep the same overlay flags across startup, inspection and shutdown."
        ],
        "steps": []
      },
      {
        "id": "section-5",
        "title": "Frontend docs and API docs",
        "paragraphs": [
          "This /docs route is the frontend user guide and remains available without an API key. FastAPI’s development-only Swagger/OpenAPI endpoints are a separate backend feature and remain disabled in production. The production frontend already falls back to index.html for direct guide URLs."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "security",
    "title": "Access and authorization boundaries",
    "group": "Operations",
    "description": "Understand workspace credentials and target restrictions.",
    "sections": [
      {
        "id": "section-1",
        "title": "Credentials and roles",
        "paragraphs": [
          "Workspace bearer keys identify owners; administrator keys are separately authorized for global controls. Keep real keys, provider credentials, proxy secrets and backups private. Public documentation contains no workspace records or secret values."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Destination controls",
        "paragraphs": [
          "Register only targets you are authorized to automate. Website allowlists and production operator authorization both apply. Private/mixed DNS results, unsupported protocols and ports are rejected. Fixture mode has a narrow development exemption and is forbidden in production."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Request and browser controls",
        "paragraphs": [
          "Incoming allowed hosts, exact CORS origins, trusted proxy peers, HTTPS enforcement and rate limits have separate purposes. Do not widen trust or disable TLS to hide a configuration problem. Automated identities retain automation markers. Browser isolation keeps concurrent tasks from sharing navigation state."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Limits of controls",
        "paragraphs": [
          "AdBot is intended for authorized monitoring and automation. Allowed destinations and job completion are not proof that every action is appropriate. Inspect workflow mutations, model permissions and partial results. Application egress checks do not replace host firewall rules or deployment verification."
        ],
        "steps": []
      }
    ]
  },
  {
    "slug": "troubleshooting",
    "title": "Troubleshooting",
    "group": "Operations",
    "description": "Find the next useful check when something fails.",
    "sections": [
      {
        "id": "section-1",
        "title": "Cannot connect or open administration",
        "paragraphs": [
          "401: verify the actual generated workspace key, its length and the API process environment. Administrator 403: the key must also appear in ADBOT_CONTENT_ADMIN_KEYS; restart after environment changes. Invalid Host/400: configure the real incoming hostname. HTTPS required/426: check TLS and exact trusted proxy configuration."
        ],
        "steps": []
      },
      {
        "id": "section-2",
        "title": "Job stays queued",
        "paragraphs": [
          "Check worker process and database connection, queue capacity, manual release, successful dependency and global pause/emergency-stop state. The scheduler alone cannot execute jobs. Look at Automation heartbeats when you have administrator access."
        ],
        "steps": []
      },
      {
        "id": "section-3",
        "title": "Schedule does not fire",
        "paragraphs": [
          "Check that the scheduler is running, the schedule is enabled and the timezone/next-run time is correct. Inspect Jobs to distinguish missing scheduling from delayed worker execution."
        ],
        "steps": []
      },
      {
        "id": "section-4",
        "title": "Target or page is rejected",
        "paragraphs": [
          "Check website and operator domain allowlists, public DNS policy, resource hosts and supported ports. If rendering is incomplete, inspect HTTP results and wait-for-selector/browser settings. Do not add unapproved hosts just to clear an error."
        ],
        "steps": []
      },
      {
        "id": "section-5",
        "title": "AI task fails or times out",
        "paragraphs": [
          "Check the provider/model, credentials, quota and step/token/time budgets. Inspect task events for invalid model output or failed verification. A fallback must be installed, reachable and configured by the operator. Review partial actions before relaunching."
        ],
        "steps": []
      },
      {
        "id": "section-6",
        "title": "Extraction returns missing or invalid data",
        "paragraphs": [
          "Inspect the dataset schema version, required fields, selectors/paths, identity fields and source pages. Use run details to distinguish page failures from validation failures. Wait for an export to complete; regenerate it if its download expired."
        ],
        "steps": []
      },
      {
        "id": "section-7",
        "title": "Content or policy save conflict",
        "paragraphs": [
          "409 means another revision was saved: retain your draft, reload and merge the edits. 422 means validation failed: read field errors and check references and permissions. New User-Agent settings apply to new browser contexts, not existing sessions."
        ],
        "steps": []
      },
      {
        "id": "section-8",
        "title": "API unavailable or readiness fails",
        "paragraphs": [
          "Check API availability, frontend proxy target, incoming Host/CORS and production Nginx routing. Readiness 503 may indicate unavailable database/Redis or unapplied migrations. Review service logs with secrets redacted and confirm the deployed versions match."
        ],
        "steps": []
      }
    ]
  }
];

export function matchDocsPath(path: string): boolean { return path === "/docs" || path.startsWith("/docs/"); }
export function findDoc(path: string): DocPage | undefined {
  const match = /^\/docs(?:\/([^/]+))?\/?$/.exec(path);
  if (!match) return undefined;
  return docs.find(page => page.slug === (match[1] || "introduction"));
}

export function searchDocs(search: string): DocPage[] {
  const query = search.trim().toLocaleLowerCase();
  return docs.filter(page => [page.title, page.description,
    ...page.sections.flatMap(section => [section.title, ...section.paragraphs, ...section.steps]),
  ].join(" ").toLocaleLowerCase().includes(query));
}
