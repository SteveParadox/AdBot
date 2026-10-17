import { useEffect, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  CalendarClock,
  ChevronRight,
  CircleDot,
  Globe2,
  LayoutDashboard,
  LogOut,
  Play,
  Plus,
  Radar,
  Route,
  X,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  api,
  defaults,
  parseEvents,
  type Collection,
  type Config,
  type Event,
  type Job,
  type Overview,
  type Schedule,
  type Step,
  type Visit,
  type Website,
  type Workflow,
} from "./api";
import { Badge, Button, Empty, Field, Pager } from "./ui";
import AgentPanel from "./AgentPanel";

type Tab =
  | "Overview"
  | "Websites"
  | "Jobs"
  | "Workflows"
  | "Schedules"
  | "AI Agent";
type Run = (
  action: () => Promise<unknown>,
  success?: () => void,
) => Promise<void>;
const date = (n: number | null) =>
  n ? new Date(n * 1000).toLocaleString() : "—";
const terminal = (status: string) =>
  ["completed", "cancelled", "failed"].includes(status);

export default function App() {
  const [token, setToken] = useState(
    sessionStorage.getItem("adbot-token") || "",
  );
  const [input, setInput] = useState("");
  const [tab, setTab] = useState<Tab>("Overview");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const client = useQueryClient();
  const run: Run = async (action, success) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await client.invalidateQueries();
      success?.();
      setNotice("Saved successfully");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const sites = useQuery({
    queryKey: ["websites", token],
    queryFn: () => api<Collection<Website>>("/websites?limit=200", token),
    enabled: !!token,
  });
  const jobs = useQuery({
    queryKey: ["recent-jobs", token],
    queryFn: () => api<Collection<Job>>("/jobs?limit=8", token),
    enabled: !!token,
  });
  const overview = useQuery({
    queryKey: ["overview", token],
    queryFn: () => api<Overview>("/analytics/overview", token),
    enabled: !!token,
  });
  const workflows = useQuery({
    queryKey: ["workflows", token],
    queryFn: () => api<Collection<Workflow>>("/workflows?limit=200", token),
    enabled: !!token,
  });
  const [selected, setSelected] = useState<string | null>(null);
  const logout = () => {
    sessionStorage.removeItem("adbot-token");
    setToken("");
    setSelected(null);
    client.clear();
  };
  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/websites?limit=1", input);
      sessionStorage.setItem("adbot-token", input);
      setToken(input);
      setInput("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  if (!token)
    return (
      <main className="login">
        <div className="login-card">
          <div className="brand">
            <Radar />
            AdBot<span>MONITOR</span>
          </div>
          <h1>Your web, in focus.</h1>
          <p>
            One workspace for authorized website automation, reliable crawls,
            and clear results.
          </p>
          <form onSubmit={login}>
            <Field label="Workspace API key">
              <input
                type="password"
                required
                minLength={32}
                value={input}
                onChange={(e) => setInput(e.target.value)}
                autoComplete="off"
                placeholder="Enter your API key"
              />
            </Field>
            {error && (
              <p role="alert" className="error">
                {error}
              </p>
            )}
            <Button type="submit" disabled={busy}>
              Connect workspace <ArrowUpRight size={16} />
            </Button>
          </form>
          <small>
            Use the key configured on your AdBot server. Your key stays in this
            browser session.
          </small>
        </div>
      </main>
    );
  const items = sites.data?.items || [];
  return (
    <div className="shell">
      <aside>
        <div className="brand">
          <Radar />
          AdBot<span>MONITOR</span>
        </div>
        <div className="workspace">
          <div className="workspace-icon">W</div>
          <div>
            My workspace<small>Website operations</small>
          </div>
          <ChevronRight size={14} />
        </div>
        <div className="nav-label">WORKSPACE</div>
        <nav>
          {(
            [
              ["Overview", LayoutDashboard],
              ["AI Agent", Radar],
              ["Websites", Globe2],
              ["Jobs", Activity],
              ["Workflows", Route],
              ["Schedules", CalendarClock],
            ] as const
          ).map(([name, Icon]) => (
            <button
              key={name}
              className={tab === name ? "active" : ""}
              onClick={() => {
                setTab(name);
                setSelected(null);
              }}
            >
              <Icon size={18} />
              {name}
              {name === "Websites" && (
                <span>{overview.data?.websites || 0}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="safety">
            <CircleDot size={15} />
            <div>
              Authorized automation
              <small>Bounded. Observable. In control.</small>
            </div>
          </div>
          <button onClick={logout}>
            <LogOut size={16} />
            Disconnect
          </button>
        </div>
      </aside>
      <div className="main">
        <header>
          <span>
            Workspace <ChevronRight size={14} /> <strong>{tab}</strong>
          </span>
          <span className="connection">
            <i /> API connected
          </span>
        </header>
        <main>
          <div className="page-heading">
            <div>
              <div className="eyebrow">WEBSITE OPERATIONS</div>
              <h1>
                {tab === "Overview" ? "A clearer view of your web." : tab}
              </h1>
              <p>
                {
                  {
                    Overview: "Monitor every run. Understand every result.",
                    "AI Agent":
                      "Set an objective. Let the browser observe, act, and verify.",
                    Websites:
                      "Configure authorized targets and keep your crawls in bounds.",
                    Jobs: "Launch, inspect, and control your browser sessions.",
                    Workflows: "Build repeatable, permitted browser actions.",
                    Schedules: "Put routine checks on a reliable schedule.",
                  }[tab]
                }
              </p>
            </div>
            {tab === "Overview" && (
              <Button onClick={() => setTab("Websites")}>
                <Plus size={16} />
                Add website
              </Button>
            )}
          </div>
          {(error || sites.error || overview.error) && (
            <div role="alert" className="alert error">
              {error || (sites.error || overview.error)?.message}
              <Button
                variant="ghost"
                onClick={() => {
                  setError("");
                  client.invalidateQueries();
                }}
              >
                Retry
              </Button>
            </div>
          )}
          {notice && (
            <div role="status" className="alert success">
              {notice}
              <button
                aria-label="Dismiss notification"
                onClick={() => setNotice("")}
              >
                <X size={14} />
              </button>
            </div>
          )}
          {tab === "AI Agent" && (
            <AgentPanel token={token} sites={items} run={run} busy={busy} />
          )}
          {tab === "Overview" && (
            <>
              <div className="stats">
                {[
                  ["Registered websites", overview.data?.websites, Globe2],
                  ["Pages visited", overview.data?.pages, Route],
                  [
                    "Active jobs",
                    (overview.data?.statuses.running || 0) +
                      (overview.data?.statuses.paused || 0),
                    Activity,
                  ],
                  [
                    "Avg. navigation",
                    Math.round(overview.data?.average_ms || 0) + " ms",
                    CalendarClock,
                  ],
                ].map(([label, value, Icon]) => (
                  <div className="stat" key={String(label)}>
                    <div>
                      <span>{String(label)}</span>
                      {typeof Icon !== "string" &&
                        typeof Icon !== "number" &&
                        Icon && <Icon size={17} />}
                    </div>
                    <strong>{value === undefined ? "—" : String(value)}</strong>
                    <small>From persisted execution results</small>
                  </div>
                ))}
              </div>
              <div className="chart-grid">
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Page activity</h2>
                      <p>Pages recorded over the last 30 days</p>
                    </div>
                    <span className="pill">30 days</span>
                  </div>
                  {overview.data?.daily_pages.length ? (
                    <div className="chart">
                      <ResponsiveContainer width="100%" height="100%">
                        <AreaChart
                          data={overview.data.daily_pages.map((d) => ({
                            ...d,
                            label: new Date(d.day * 1000).toLocaleDateString(
                              undefined,
                              { month: "short", day: "numeric" },
                            ),
                          }))}
                        >
                          <defs>
                            <linearGradient
                              id="fill"
                              x1="0"
                              y1="0"
                              x2="0"
                              y2="1"
                            >
                              <stop
                                offset="0%"
                                stopColor="#4968f5"
                                stopOpacity={0.2}
                              />
                              <stop
                                offset="100%"
                                stopColor="#4968f5"
                                stopOpacity={0}
                              />
                            </linearGradient>
                          </defs>
                          <CartesianGrid vertical={false} stroke="#edf0f4" />
                          <XAxis
                            dataKey="label"
                            tickLine={false}
                            axisLine={false}
                            fontSize={11}
                          />
                          <YAxis
                            allowDecimals={false}
                            tickLine={false}
                            axisLine={false}
                            fontSize={11}
                          />
                          <Tooltip />
                          <Area
                            type="monotone"
                            dataKey="count"
                            name="Pages"
                            stroke="#4968f5"
                            strokeWidth={2.5}
                            fill="url(#fill)"
                          />
                        </AreaChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <Empty
                      text={
                        overview.isLoading
                          ? "Loading activity…"
                          : "Your first crawl will appear here."
                      }
                    />
                  )}
                </section>
                <section className="panel">
                  <div className="panel-heading">
                    <div>
                      <h2>Execution health</h2>
                      <p>All recorded jobs</p>
                    </div>
                    <Activity size={18} />
                  </div>
                  <div className="health-number">
                    {overview.data?.jobs || 0}
                    <span>total jobs</span>
                  </div>
                  {["completed", "failed", "cancelled", "queued"].map((s) => (
                    <div className="health-row" key={s}>
                      <Badge status={s} />
                      <strong>{overview.data?.statuses[s] || 0}</strong>
                    </div>
                  ))}
                </section>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <div>
                    <h2>Recent runs</h2>
                    <p>The latest activity across your websites</p>
                  </div>
                  <Button variant="ghost" onClick={() => setTab("Jobs")}>
                    View all <ChevronRight size={14} />
                  </Button>
                </div>
                <JobTable
                  items={jobs.data?.items || []}
                  sites={items}
                  select={(id) => {
                    setSelected(id);
                    setTab("Jobs");
                  }}
                />
              </section>
              <section className="panel">
                <div className="panel-heading">
                  <h2>HTTP responses</h2>
                </div>
                <div className="response-list">
                  <span className="pill">
                    Page failure rate:{" "}
                    <strong>
                      {((overview.data?.failure_rate || 0) * 100).toFixed(1)}%
                    </strong>
                  </span>
                  <span className="pill">
                    Scheduled runs:{" "}
                    <strong>{overview.data?.scheduled_jobs || 0}</strong>
                  </span>
                  <span className="pill">
                    Scheduled success:{" "}
                    <strong>
                      {overview.data?.scheduled_success_rate == null
                        ? "—"
                        : (overview.data.scheduled_success_rate * 100).toFixed(
                            1,
                          ) + "%"}
                    </strong>
                  </span>
                  {overview.data?.http_statuses.map((s) => (
                    <span className="pill" key={s.status}>
                      {s.status}: <strong>{s.count}</strong>
                    </span>
                  ))}
                  {!overview.data?.http_statuses.length && (
                    <p>No responses recorded yet.</p>
                  )}
                </div>
              </section>
            </>
          )}
          {tab === "Websites" && (
            <Websites
              token={token}
              sites={items}
              run={run}
              busy={busy}
              loading={sites.isLoading}
            />
          )}
          {tab === "Jobs" &&
            (selected ? (
              <JobDetail
                id={selected}
                token={token}
                sites={items}
                run={run}
                busy={busy}
                back={() => setSelected(null)}
              />
            ) : (
              <Jobs
                token={token}
                sites={items}
                workflows={workflows.data?.items || []}
                run={run}
                busy={busy}
                select={setSelected}
              />
            ))}
          {tab === "Workflows" && (
            <Workflows
              token={token}
              sites={items}
              items={workflows.data?.items || []}
              run={run}
              busy={busy}
            />
          )}
          {tab === "Schedules" && (
            <Schedules
              token={token}
              sites={items}
              workflows={workflows.data?.items || []}
              run={run}
              busy={busy}
            />
          )}
        </main>
        <footer>
          AdBot Monitor <span>Built for permitted website operations.</span>
        </footer>
      </div>
    </div>
  );
}

function JobTable({
  items,
  sites,
  select,
}: {
  items: Job[];
  sites: Website[];
  select: (id: string) => void;
}) {
  if (!items.length)
    return (
      <Empty text="No runs yet. Add a website and launch your first job." />
    );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Website / run</th>
            <th>Type</th>
            <th>Status</th>
            <th>Pages</th>
            <th>Created</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((j) => (
            <tr key={j.id}>
              <td>
                <strong>
                  {sites.find((s) => s.id === j.website_id)?.name || "Website"}
                </strong>
                <small>{j.id.slice(0, 8)}</small>
              </td>
              <td>{j.job_type}</td>
              <td>
                <Badge status={j.status} />
              </td>
              <td>{j.pages_visited}</td>
              <td>{date(j.created_at)}</td>
              <td>
                <Button variant="ghost" onClick={() => select(j.id)}>
                  Inspect <ChevronRight size={14} />
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Websites({
  token,
  sites,
  run,
  busy,
  loading,
}: {
  token: string;
  sites: Website[];
  run: Run;
  busy: boolean;
  loading: boolean;
}) {
  const [editing, setEditing] = useState<Website | null>(null);
  const [show, setShow] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [domains, setDomains] = useState("");
  const [config, setConfig] = useState<Config>({ ...defaults });
  const [authorized, setAuthorized] = useState(false);
  function edit(site?: Website) {
    setEditing(site || null);
    setName(site?.name || "");
    setUrl(site?.base_url || "");
    setDomains(site?.allowed_domains.join(", ") || "");
    setConfig(site?.configuration || { ...defaults });
    setAuthorized(false);
    setShow(true);
  }
  function save(e: FormEvent) {
    e.preventDefault();
    run(
      () =>
        api(
          "/websites" + (editing ? "/" + editing.id : ""),
          token,
          editing ? "PATCH" : "POST",
          {
            name,
            base_url: url,
            allowed_domains: domains
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            configuration: config,
            authorized,
          },
        ),
      () => setShow(false),
    );
  }
  const update = (key: keyof Config, value: unknown) =>
    setConfig((c) => ({ ...c, [key]: value }));
  return (
    <>
      <div className="toolbar">
        <span>{sites.length} configured targets</span>
        <Button onClick={() => edit()}>
          <Plus size={16} />
          Add website
        </Button>
      </div>
      {show && (
        <section className="panel form-panel">
          <div className="panel-heading">
            <h2>{editing ? "Edit website" : "Register a website"}</h2>
            <Button
              variant="ghost"
              onClick={() => setShow(false)}
              aria-label="Close website form"
            >
              <X size={16} />
            </Button>
          </div>
          <form onSubmit={save}>
            <div className="form-grid">
              <Field label="Website name">
                <input
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="Company website"
                />
              </Field>
              <Field label="Starting URL">
                <input
                  type="url"
                  required
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://example.com/"
                />
              </Field>
              <Field label="Allowed domains (comma separated)">
                <input
                  required
                  value={domains}
                  onChange={(e) => setDomains(e.target.value)}
                  placeholder="example.com, *.example.com"
                />
              </Field>
              <Field label="Maximum pages">
                <input
                  type="number"
                  min={1}
                  max={1000}
                  value={config.max_pages}
                  onChange={(e) => update("max_pages", +e.target.value)}
                />
              </Field>
              <Field label="Maximum depth">
                <input
                  type="number"
                  min={0}
                  max={10}
                  value={config.max_depth}
                  onChange={(e) => update("max_depth", +e.target.value)}
                />
              </Field>
              <Field label="Delay between pages (seconds)">
                <input
                  type="number"
                  min={0.1}
                  step={0.1}
                  max={300}
                  value={config.delay_seconds}
                  onChange={(e) => update("delay_seconds", +e.target.value)}
                />
              </Field>
            </div>
            <details>
              <summary>Browser, limits, and URL rules</summary>
              <div className="form-grid">
                {(
                  [
                    "navigation_timeout_ms",
                    "max_duration_seconds",
                    "retries",
                  ] as const
                ).map((k) => (
                  <Field key={k} label={k.replace(/_/g, " ")}>
                    <input
                      type="number"
                      value={config[k]}
                      onChange={(e) => update(k, +e.target.value)}
                    />
                  </Field>
                ))}
                <Field label="Browser engine">
                  <select
                    value={config.browser}
                    onChange={(e) => update("browser", e.target.value)}
                  >
                    {["chromium", "firefox", "webkit"].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Viewport">
                  <select
                    value={config.viewport}
                    onChange={(e) => update("viewport", e.target.value)}
                  >
                    <option>desktop</option>
                    <option>mobile</option>
                  </select>
                </Field>
                <Field label="Wait until">
                  <select
                    value={config.wait_until}
                    onChange={(e) => update("wait_until", e.target.value)}
                  >
                    {["domcontentloaded", "load", "networkidle"].map((v) => (
                      <option key={v}>{v}</option>
                    ))}
                  </select>
                </Field>
                <Field label="Wait for selector (optional)">
                  <input
                    value={config.wait_selector || ""}
                    onChange={(e) =>
                      update("wait_selector", e.target.value || null)
                    }
                  />
                </Field>
                <Field label="Allowed URL globs (one per line)">
                  <textarea
                    value={config.allowed_patterns.join("\n")}
                    onChange={(e) =>
                      update("allowed_patterns", e.target.value.split("\n"))
                    }
                  />
                </Field>
                <Field label="Excluded URL globs (one per line)">
                  <textarea
                    value={config.excluded_patterns.join("\n")}
                    onChange={(e) =>
                      update(
                        "excluded_patterns",
                        e.target.value.split("\n").filter(Boolean),
                      )
                    }
                  />
                </Field>
              </div>
              <div className="checks">
                {(
                  [
                    "headless",
                    "screenshots",
                    "discover_links",
                    "scroll",
                    "respect_robots",
                  ] as const
                ).map((k) => (
                  <label key={k}>
                    <input
                      type="checkbox"
                      checked={config[k]}
                      onChange={(e) => update(k, e.target.checked)}
                    />
                    {k.replace(/_/g, " ")}
                  </label>
                ))}
              </div>
              <p className="hint">
                Visible mode requires a display on the worker machine. Include
                each resource hostname in the allowlist.
              </p>
            </details>
            <label className="check">
              <input
                type="checkbox"
                required
                checked={authorized}
                onChange={(e) => setAuthorized(e.target.checked)}
              />
              I am authorized to automate this website and these destinations.
            </label>
            <Button type="submit" disabled={busy}>
              Save website
            </Button>
          </form>
        </section>
      )}
      {loading ? (
        <Empty text="Loading websites…" />
      ) : !sites.length ? (
        <Empty text="Register your first website to start monitoring." />
      ) : (
        <div className="site-grid">
          {sites.map((site) => (
            <section className="panel site-card" key={site.id}>
              <div className="site-icon">
                <Globe2 size={23} />
              </div>
              <h2>{site.name}</h2>
              <p className="url">{site.base_url}</p>
              <div className="site-meta">
                <span>{site.configuration.max_pages} pages / run</span>
                <span>Depth {site.configuration.max_depth}</span>
              </div>
              <div className="site-actions">
                <Button variant="outline" onClick={() => edit(site)}>
                  Configure
                </Button>
                <Button
                  disabled={busy}
                  onClick={() =>
                    run(() =>
                      api(
                        "/jobs",
                        token,
                        "POST",
                        { website_id: site.id },
                        { "Idempotency-Key": crypto.randomUUID() },
                      ),
                    )
                  }
                >
                  <Play size={14} />
                  Run crawl
                </Button>
                <Button
                  variant="ghost"
                  disabled={busy}
                  onClick={() => {
                    if (confirm("Delete this website and its history?"))
                      run(() => api("/websites/" + site.id, token, "DELETE"));
                  }}
                >
                  Delete
                </Button>
              </div>
            </section>
          ))}
        </div>
      )}
    </>
  );
}

function Jobs({
  token,
  sites,
  workflows,
  run,
  busy,
  select,
}: {
  token: string;
  sites: Website[];
  workflows: Workflow[];
  run: Run;
  busy: boolean;
  select: (id: string) => void;
}) {
  const [site, setSite] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [page, setPage] = useState(0);
  const [status, setStatus] = useState("");
  const jobs = useQuery({
    queryKey: ["jobs", token, page, status],
    queryFn: () =>
      api<Collection<Job>>(
        `/jobs?limit=25&offset=${page * 25}${status ? "&status=" + status : ""}`,
        token,
      ),
  });
  function start(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      const job = await api<Job>(
        "/jobs",
        token,
        "POST",
        { website_id: site, workflow_id: workflow || null },
        { "Idempotency-Key": crypto.randomUUID() },
      );
      select(job.id);
    });
  }
  return (
    <>
      <section className="panel form-panel">
        <h2>Launch a browser session</h2>
        <form className="inline-form" onSubmit={start}>
          <Field label="Website">
            <select
              required
              value={site}
              onChange={(e) => {
                setSite(e.target.value);
                setWorkflow("");
              }}
            >
              <option value="">Select a target</option>
              {sites.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Execution mode">
            <select
              value={workflow}
              onChange={(e) => setWorkflow(e.target.value)}
            >
              <option value="">Link-discovery crawl</option>
              {workflows
                .filter((w) => w.website_id === site && w.enabled)
                .map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name} (v{w.version})
                  </option>
                ))}
            </select>
          </Field>
          <Button type="submit" disabled={busy || !site}>
            <Play size={15} />
            Start job
          </Button>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>Run history</h2>
          <select
            aria-label="Filter jobs by status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            <option value="">All statuses</option>
            {[
              "queued",
              "running",
              "paused",
              "completed",
              "failed",
              "cancelled",
            ].map((s) => (
              <option key={s}>{s}</option>
            ))}
          </select>
        </div>
        {jobs.error ? (
          <p role="alert" className="error">
            {jobs.error.message}
          </p>
        ) : jobs.isLoading ? (
          <Empty text="Loading runs…" />
        ) : (
          <JobTable
            items={jobs.data?.items || []}
            sites={sites}
            select={select}
          />
        )}
        <Pager page={page} total={jobs.data?.total || 0} setPage={setPage} />
      </section>
    </>
  );
}

function JobDetail({
  id,
  token,
  sites,
  run,
  busy,
  back,
}: {
  id: string;
  token: string;
  sites: Website[];
  run: Run;
  busy: boolean;
  back: () => void;
}) {
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [live, setLive] = useState<Event[]>([]);
  const [image, setImage] = useState<string | null>(null);
  const job = useQuery({
    queryKey: ["job", id, token],
    queryFn: () => api<Job>("/jobs/" + id, token),
  });
  const pages = useQuery({
    queryKey: ["pages", id, page, search, status, token],
    queryFn: () =>
      api<Collection<Visit>>(
        `/jobs/${id}/pages?offset=${page * 25}&limit=25&q=${encodeURIComponent(search)}${status ? "&http_status=" + status : ""}`,
        token,
      ),
  });
  const logs = useQuery({
    queryKey: ["logs", id, token],
    queryFn: () => api<Collection<Event>>(`/jobs/${id}/logs?limit=200`, token),
  });
  const isTerminal = terminal(job.data?.status || "queued");
  useEffect(() => {
    const controller = new AbortController();
    let last = 0;
    setLive([]);
    async function connect() {
      while (!controller.signal.aborted) {
        try {
          const response = await fetch(`/api/jobs/${id}/events`, {
            headers: {
              Authorization: "Bearer " + token,
              "Last-Event-ID": String(last),
            },
            signal: controller.signal,
          });
          if (!response.ok) throw new Error("Stream unavailable");
          const reader = response.body!.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (true) {
            const chunk = await reader.read();
            if (chunk.done) break;
            buffer += decoder.decode(chunk.value, { stream: true });
            const parsed = parseEvents(buffer);
            buffer = parsed.remaining;
            if (parsed.events.length) {
              last = parsed.events.at(-1)!.id;
              setLive((old) => [...old, ...parsed.events].slice(-200));
            }
          }
          if (isTerminal) return;
        } catch {
          if (controller.signal.aborted) return;
        }
        await new Promise((resolve) => setTimeout(resolve, 1500));
      }
    }
    connect();
    return () => controller.abort();
  }, [id, token, isTerminal]);
  useEffect(
    () => () => {
      if (image) URL.revokeObjectURL(image);
    },
    [image],
  );
  if (job.error)
    return (
      <p className="error" role="alert">
        {job.error.message}
      </p>
    );
  if (!job.data) return <Empty text="Loading job…" />;
  const j = job.data;
  const events = Array.from(
    new Map(
      [...(logs.data?.items || []), ...live].map((e) => [e.id, e]),
    ).values(),
  )
    .sort((a, b) => a.id - b.id)
    .slice(-200);
  const latest = events.at(-1);
  const target = sites.find((s) => s.id === j.website_id);
  return (
    <>
      <Button variant="ghost" onClick={back}>
        ← All jobs
      </Button>
      <section className="panel form-panel">
        <div className="panel-heading">
          <div>
            <h2>
              {target?.name || "Browser session"} <Badge status={j.status} />
            </h2>
            <p className="mono">{j.id}</p>
          </div>
          <div className="button-row">
            {!terminal(j.status) && (
              <>
                <Button
                  variant="outline"
                  disabled={busy || j.status === "queued"}
                  onClick={() =>
                    run(() =>
                      api(
                        `/jobs/${id}/${j.status === "paused" ? "resume" : "pause"}`,
                        token,
                        "POST",
                      ),
                    )
                  }
                >
                  {j.status === "paused" ? "Resume" : "Pause"}
                </Button>
                <Button
                  variant="destructive"
                  disabled={busy}
                  onClick={() =>
                    run(() => api(`/jobs/${id}/cancel`, token, "POST"))
                  }
                >
                  Cancel
                </Button>
              </>
            )}
            {["failed", "cancelled"].includes(j.status) && (
              <Button
                disabled={busy}
                onClick={() =>
                  run(() => api(`/jobs/${id}/retry`, token, "POST"))
                }
              >
                Retry as new job
              </Button>
            )}
          </div>
        </div>
        <div className="run-metrics">
          <div>
            <span>Pages recorded</span>
            <strong>{j.pages_visited}</strong>
          </div>
          <div>
            <span>URLs discovered</span>
            <strong>{j.discovered_count || 0}</strong>
          </div>
          <div>
            <span>Elapsed</span>
            <strong>
              {j.started_at
                ? Math.max(
                    0,
                    Math.round(
                      (j.completed_at || Date.now() / 1000) - j.started_at,
                    ),
                  ) + " s"
                : "Queued"}
            </strong>
          </div>
          <div>
            <span>Browser state</span>
            <strong>
              {terminal(j.status)
                ? "Closed"
                : j.status === "queued"
                  ? "Waiting"
                  : "Active"}
            </strong>
          </div>
        </div>
        <progress
          max={target?.configuration.max_pages || 10}
          value={j.pages_visited}
        />
        <p className="hint">
          {latest?.message || "Waiting for worker"}{" "}
          {latest?.details.url ? String(latest.details.url) : ""}
        </p>
        {j.error_message && <p className="error">{j.error_message}</p>}
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>Visited pages</h2>
          <div className="button-row">
            <input
              aria-label="Search visited URLs"
              placeholder="Search URLs"
              value={search}
              onChange={(e) => {
                setSearch(e.target.value);
                setPage(0);
              }}
            />
            <select
              aria-label="Filter HTTP status"
              value={status}
              onChange={(e) => {
                setStatus(e.target.value);
                setPage(0);
              }}
            >
              <option value="">All HTTP statuses</option>
              {[200, 301, 302, 403, 404, 429, 500, 503].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
        </div>
        {pages.error ? (
          <p role="alert" className="error">
            {pages.error.message}
          </p>
        ) : !pages.data?.items.length ? (
          <Empty text="Page results will appear as the worker records them." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Page</th>
                  <th>HTTP</th>
                  <th>Time</th>
                  <th>Visited</th>
                  <th>Capture</th>
                </tr>
              </thead>
              <tbody>
                {pages.data.items.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <strong>{p.page_title || p.error || "Untitled"}</strong>
                      <small className="url">{p.requested_url}</small>
                      {p.final_url !== p.requested_url && (
                        <small>→ {p.final_url}</small>
                      )}
                    </td>
                    <td>
                      <Badge
                        status={
                          p.http_status ? String(p.http_status) : "failed"
                        }
                      />
                    </td>
                    <td>{Math.round(p.navigation_duration_ms)} ms</td>
                    <td>{date(p.visited_at)}</td>
                    <td>
                      {p.screenshot_path && (
                        <Button
                          variant="ghost"
                          onClick={() =>
                            run(async () => {
                              const r = await fetch(
                                "/api/artifacts/" + p.screenshot_path,
                                {
                                  headers: { Authorization: "Bearer " + token },
                                },
                              );
                              if (!r.ok)
                                throw new Error("Screenshot unavailable");
                              setImage(URL.createObjectURL(await r.blob()));
                            })
                          }
                        >
                          View
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} total={pages.data?.total || 0} setPage={setPage} />
      </section>
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Execution events</h2>
            <p>Live updates with reconnect and replay</p>
          </div>
          <span className="pill">{events.length} events</span>
        </div>
        <div className="event-list">
          {events.map((e) => (
            <div className="event" key={e.id}>
              <time>{new Date(e.timestamp * 1000).toLocaleTimeString()}</time>
              <span className="event-dot" />
              <div>
                <strong>{e.message}</strong>
                <small>{e.event_type}</small>
                {Object.keys(e.details).length > 0 && (
                  <pre>{JSON.stringify(e.details, null, 2)}</pre>
                )}
                {typeof e.details.screenshot_path === "string" && (
                  <Button
                    variant="ghost"
                    onClick={() =>
                      run(async () => {
                        const r = await fetch(
                          "/api/artifacts/" + e.details.screenshot_path,
                          { headers: { Authorization: "Bearer " + token } },
                        );
                        if (!r.ok) throw new Error("Screenshot unavailable");
                        setImage(URL.createObjectURL(await r.blob()));
                      })
                    }
                  >
                    View screenshot
                  </Button>
                )}
              </div>
            </div>
          ))}
          {!events.length && <Empty text="Waiting for execution events…" />}
        </div>
      </section>
      {image && (
        <div
          className="modal"
          role="dialog"
          aria-modal="true"
          aria-label="Page screenshot"
          onClick={() => setImage(null)}
        >
          <Button onClick={() => setImage(null)}>Close screenshot</Button>
          <img src={image} alt="Captured website viewport" />
        </div>
      )}
    </>
  );
}

const actions = [
  "OPEN_URL",
  "WAIT",
  "WAIT_FOR_SELECTOR",
  "CLICK",
  "SCROLL",
  "EXTRACT_TEXT",
  "EXTRACT_LINKS",
  "SCREENSHOT",
  "ASSERT_VISIBLE",
  "ASSERT_TEXT",
  "NAVIGATE_BACK",
  "STOP",
];
function Workflows({
  token,
  sites,
  items,
  run,
  busy,
}: {
  token: string;
  sites: Website[];
  items: Workflow[];
  run: Run;
  busy: boolean;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [site, setSite] = useState("");
  const [name, setName] = useState("");
  const [steps, setSteps] = useState<Step[]>([
    { action: "ASSERT_VISIBLE", selector: "h1", timeout_ms: 10000 },
  ]);
  const [enabled, setEnabled] = useState(true);
  function setStep(index: number, change: Partial<Step>) {
    setSteps((old) =>
      old.map((s, i) => (i === index ? { ...s, ...change } : s)),
    );
  }
  function save(e: FormEvent) {
    e.preventDefault();
    run(
      () =>
        api(
          "/workflows" + (editing ? "/" + editing : ""),
          token,
          editing ? "PATCH" : "POST",
          {
            website_id: site,
            name,
            definition: { schema_version: 1, steps },
            enabled,
          },
        ),
      () => {
        setEditing(null);
        setName("");
      },
    );
  }
  return (
    <>
      <section className="panel form-panel">
        <h2>{editing ? "Edit workflow" : "Build a workflow"}</h2>
        <p className="hint">
          Actions run in order. Selectors are Playwright locators. No user
          scripts are executed.
        </p>
        <form onSubmit={save}>
          <div className="form-grid">
            <Field label="Name">
              <input
                required
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </Field>
            <Field label="Website">
              <select
                required
                disabled={!!editing}
                value={site}
                onChange={(e) => setSite(e.target.value)}
              >
                <option value="">Select website</option>
                {sites.map((s) => (
                  <option value={s.id} key={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          {steps.map((step, index) => (
            <div className="workflow-step" key={index}>
              <span className="step-number">{index + 1}</span>
              <Field label="Action">
                <select
                  value={step.action}
                  onChange={(e) =>
                    setSteps((old) =>
                      old.map((s, i) =>
                        i === index
                          ? { action: e.target.value, timeout_ms: 10000 }
                          : s,
                      ),
                    )
                  }
                >
                  {actions.map((a) => (
                    <option key={a}>{a}</option>
                  ))}
                </select>
              </Field>
              {[
                "WAIT_FOR_SELECTOR",
                "CLICK",
                "EXTRACT_TEXT",
                "ASSERT_VISIBLE",
                "ASSERT_TEXT",
                "SCROLL",
              ].includes(step.action) && (
                <Field label="Selector">
                  <input
                    required={step.action !== "SCROLL"}
                    placeholder="h1, #element, text=Next"
                    value={step.selector || ""}
                    onChange={(e) =>
                      setStep(index, { selector: e.target.value || undefined })
                    }
                  />
                </Field>
              )}
              {step.action === "OPEN_URL" && (
                <Field label="Allowed URL">
                  <input
                    type="url"
                    required
                    value={step.url || ""}
                    onChange={(e) => setStep(index, { url: e.target.value })}
                  />
                </Field>
              )}
              {step.action === "WAIT" && (
                <Field label="Seconds">
                  <input
                    type="number"
                    min={0}
                    max={60}
                    value={step.seconds ?? 1}
                    onChange={(e) =>
                      setStep(index, { seconds: +e.target.value })
                    }
                  />
                </Field>
              )}
              {step.action === "ASSERT_TEXT" && (
                <Field label="Expected text">
                  <input
                    required
                    value={step.text || ""}
                    onChange={(e) => setStep(index, { text: e.target.value })}
                  />
                </Field>
              )}
              {step.action === "SCROLL" && (
                <Field label="Pixels">
                  <input
                    type="number"
                    min={0}
                    max={10000}
                    value={step.pixels ?? 600}
                    onChange={(e) =>
                      setStep(index, { pixels: +e.target.value })
                    }
                  />
                </Field>
              )}
              <Field label="Timeout (ms)">
                <input
                  type="number"
                  min={100}
                  max={60000}
                  value={step.timeout_ms ?? 10000}
                  onChange={(e) =>
                    setStep(index, { timeout_ms: +e.target.value })
                  }
                />
              </Field>
              {step.action === "CLICK" && (
                <label className="check">
                  <input
                    type="checkbox"
                    required
                    checked={step.authorized || false}
                    onChange={(e) =>
                      setStep(index, { authorized: e.target.checked })
                    }
                  />
                  I authorize this click. Forms are blocked; buttons require
                  data-adbot-safe.
                </label>
              )}
              <Button
                variant="ghost"
                disabled={steps.length === 1}
                onClick={() =>
                  setSteps((old) => old.filter((_, i) => i !== index))
                }
                aria-label={"Remove step " + (index + 1)}
              >
                <X size={16} />
              </Button>
            </div>
          ))}
          <div className="button-row">
            <Button
              variant="outline"
              disabled={steps.length >= 100}
              onClick={() =>
                setSteps((old) => [
                  ...old,
                  { action: "WAIT", seconds: 1, timeout_ms: 10000 },
                ])
              }
            >
              <Plus size={14} />
              Add action
            </Button>
            <label className="check">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Enabled
            </label>
            <Button type="submit" disabled={busy || !site}>
              Save workflow
            </Button>
            {editing && (
              <Button
                variant="ghost"
                onClick={() => {
                  setEditing(null);
                  setName("");
                }}
              >
                Cancel edit
              </Button>
            )}
          </div>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>Saved workflows</h2>
        </div>
        {!items.length ? (
          <Empty text="Save a workflow to reuse it in jobs and schedules." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Version</th>
                  <th>Actions</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {items.map((w) => (
                  <tr key={w.id}>
                    <td>
                      <strong>{w.name}</strong>
                      <small>
                        {sites.find((s) => s.id === w.website_id)?.name}
                      </small>
                    </td>
                    <td>v{w.version}</td>
                    <td>{w.definition.steps.length}</td>
                    <td>
                      <Badge status={w.enabled ? "enabled" : "disabled"} />
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setEditing(w.id);
                          setSite(w.website_id);
                          setName(w.name);
                          setSteps(w.definition.steps);
                          setEnabled(w.enabled);
                          window.scrollTo({ top: 0, behavior: "smooth" });
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          run(() => api("/workflows/" + w.id, token, "DELETE"))
                        }
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function Schedules({
  token,
  sites,
  workflows,
  run,
  busy,
}: {
  token: string;
  sites: Website[];
  workflows: Workflow[];
  run: Run;
  busy: boolean;
}) {
  const [site, setSite] = useState("");
  const [workflow, setWorkflow] = useState("");
  const [mode, setMode] = useState("daily");
  const [cron, setCron] = useState("0 8 * * *");
  const [zone, setZone] = useState(
    Intl.DateTimeFormat().resolvedOptions().timeZone,
  );
  const [when, setWhen] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const schedules = useQuery({
    queryKey: ["schedules", token],
    queryFn: () => api<Collection<Schedule>>("/schedules?limit=200", token),
  });
  function save(e: FormEvent) {
    e.preventDefault();
    const expression =
      mode === "once"
        ? null
        : mode === "hourly"
          ? "0 * * * *"
          : mode === "daily"
            ? "0 8 * * *"
            : mode === "weekly"
              ? "0 8 * * 1"
              : cron;
    const data = {
      cron_expression: expression,
      timezone: zone,
      run_at: mode === "once" ? new Date(when).toISOString() : null,
      enabled: true,
    };
    run(
      () =>
        api(
          "/schedules" + (editing ? "/" + editing : ""),
          token,
          editing ? "PATCH" : "POST",
          editing
            ? data
            : { website_id: site, workflow_id: workflow || null, ...data },
        ),
      () => setEditing(null),
    );
  }
  return (
    <>
      <section className="panel form-panel">
        <h2>{editing ? "Edit schedule" : "Create a schedule"}</h2>
        <form onSubmit={save}>
          <div className="form-grid">
            <Field label="Website">
              <select
                required
                disabled={!!editing}
                value={site}
                onChange={(e) => {
                  setSite(e.target.value);
                  setWorkflow("");
                }}
              >
                <option value="">Select website</option>
                {sites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Workflow">
              <select
                disabled={!!editing}
                value={workflow}
                onChange={(e) => setWorkflow(e.target.value)}
              >
                <option value="">Crawl</option>
                {workflows
                  .filter((w) => w.website_id === site && w.enabled)
                  .map((w) => (
                    <option key={w.id} value={w.id}>
                      {w.name}
                    </option>
                  ))}
              </select>
            </Field>
            <Field label="Frequency">
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="hourly">Hourly</option>
                <option value="daily">Daily at 08:00</option>
                <option value="weekly">Monday at 08:00</option>
                <option value="custom">Custom cron</option>
                <option value="once">One time</option>
              </select>
            </Field>
            {mode === "custom" && (
              <Field label="Five-field cron">
                <input
                  required
                  value={cron}
                  onChange={(e) => setCron(e.target.value)}
                />
              </Field>
            )}
            {mode === "once" && (
              <Field label="Run at (your browser's local time)">
                <input
                  type="datetime-local"
                  required
                  value={when}
                  onChange={(e) => setWhen(e.target.value)}
                />
              </Field>
            )}
            <Field label="Schedule timezone">
              <input
                required
                value={zone}
                onChange={(e) => setZone(e.target.value)}
                placeholder="Africa/Lagos"
              />
            </Field>
          </div>
          <div className="button-row">
            <Button type="submit" disabled={busy || !site}>
              Save schedule
            </Button>
            {editing && (
              <Button variant="ghost" onClick={() => setEditing(null)}>
                Cancel edit
              </Button>
            )}
          </div>
        </form>
      </section>
      <section className="panel">
        <div className="panel-heading">
          <h2>Scheduled checks</h2>
        </div>
        {schedules.error ? (
          <p role="alert" className="error">
            {schedules.error.message}
          </p>
        ) : !schedules.data?.items.length ? (
          <Empty text="No schedules yet. Your recurring checks will appear here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Website</th>
                  <th>Schedule</th>
                  <th>Next run</th>
                  <th>Status</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {schedules.data.items.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <strong>
                        {sites.find((w) => w.id === s.website_id)?.name}
                      </strong>
                      <small>{s.workflow_id ? "Workflow" : "Crawl"}</small>
                    </td>
                    <td>
                      {s.cron_expression || "One time"}
                      <small>{s.timezone}</small>
                    </td>
                    <td>{date(s.next_run_at)}</td>
                    <td>
                      <Badge status={s.enabled ? "enabled" : "disabled"} />
                    </td>
                    <td>
                      <Button
                        variant="ghost"
                        onClick={() => {
                          setEditing(s.id);
                          setSite(s.website_id);
                          setWorkflow(s.workflow_id || "");
                          setMode(s.cron_expression ? "custom" : "once");
                          setCron(s.cron_expression || "0 8 * * *");
                          setZone(s.timezone);
                          setWhen(
                            new Date(
                              s.next_run_at * 1000 -
                                new Date().getTimezoneOffset() * 60000,
                            )
                              .toISOString()
                              .slice(0, 16),
                          );
                        }}
                      >
                        Edit
                      </Button>
                      <Button
                        variant="outline"
                        disabled={busy}
                        onClick={() =>
                          run(() =>
                            api("/schedules/" + s.id, token, "PATCH", {
                              enabled: !s.enabled,
                            }),
                          )
                        }
                      >
                        {s.enabled ? "Pause" : "Resume"}
                      </Button>
                      <Button
                        variant="ghost"
                        disabled={busy}
                        onClick={() =>
                          run(() => api("/schedules/" + s.id, token, "DELETE"))
                        }
                      >
                        Delete
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
