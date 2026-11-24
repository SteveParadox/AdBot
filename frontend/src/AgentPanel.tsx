import { useJobEvents } from "./useJobEvents";
import { JobFailure } from "./JobFailure";
import { useEffect, useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { BrainCircuit, Play, ArrowLeft, RefreshCw } from "lucide-react";
import {
  api,
  type Collection,
  type Job,
  type Website,
} from "./api";
import { Badge, Button, Empty, Field, Pager } from "./ui";
import { AgentPlan, type Planning } from "./AgentPlan";
import { SemanticTrace, SemanticObservation, type SemanticObservationData, type SemanticAction, type SemanticInteraction } from "./SemanticTrace";

type Run = (
  action: () => Promise<unknown>,
  success?: () => void,
) => Promise<void>;
type Evidence = { id: string; url: string; quote: string; step_id: number };
type Claim = { text: string; evidence_ids: string[] };
type Task = Job & {
  planning?: Planning;
  budget?: { elapsed_seconds: number; remaining_seconds: number; remaining_tokens: number };
  objective: string;
  mode: string;
  options: {
    success_criteria: string[];
    max_steps: number;
    max_tokens: number;
  };
  result: {
    artifact?: { format: string; download_url: string };
    claims?: Claim[];
    evidence?: Evidence[];
    verification?: { complete: boolean; explanation: string };
  };
  pending_step_id: number | null;
  memory: Record<string, unknown>;
  model_calls: number;
  prompt_tokens: number;
  completion_tokens: number;
  model_latency_ms: number;
};
type Step = {
  id: number;
  number: number;
  status: string;
  observation: SemanticObservationData & {
    url: string;
    screenshot_path: string;
    tabs?: { tab_id: string; url: string; purpose: string }[];
    elements?: { element_id: string; name: string; role: string }[];
  };
  decision: {
    decision?: string;
    reason?: string;
    text?: string;
    expected_result?: string;
    target?: { element_id: string };
  };
  outcome: {
    semantic?: SemanticAction;
    trace?: { phase: string; started_at: number; duration_ms: number; status: string }[];
    interaction?: SemanticInteraction & { changed: boolean; scroll?: {y: number; height: number} | null };
    [key: string]: unknown;
  };
};
export function InteractionOutcome({ interaction }: { interaction: Step["outcome"]["interaction"] }) {
  if (!interaction) return null;
  const y = interaction.scroll?.y;
  return <p className="hint">
    UI outcome: {interaction.verified ? "verified" : "no confirmed change"}
    {" · "}{interaction.verification}
    {typeof y === "number" && Number.isFinite(y) && <>{" · Scroll "}{y}px</>}
  </p>;
}
type Config = {
  provider: string;
  model: string;
  fallback_provider: string;
  fallback_model: string | null;
  configured: boolean;
  max_steps: number;
  max_tokens: number;
  memory_enabled: boolean;
  visual_reasoning: boolean;
  session_persistence: boolean;
  max_tabs: number;
  max_concurrency: number;
};
type Metrics = {
  tasks: number;
  success_rate: number | null;
  average_steps: number;
  tokens: number;
  average_model_latency_ms: number;
  statuses: Record<string, number>;
};
const finished = (status: string) =>
  ["completed", "failed", "cancelled"].includes(status);

export default function AgentPanel({
  token,
  sites,
  run,
  busy,
}: {
  token: string;
  sites: Website[];
  run: Run;
  busy: boolean;
}) {
  const [selected, setSelected] = useState<string | null>(null),
    [page, setPage] = useState(0);
  const [website, setWebsite] = useState(""),
    [url, setUrl] = useState(""),
    [objective, setObjective] = useState("");
  const [criteria, setCriteria] = useState(""),
    [mode, setMode] = useState("supervised"),
    [maxSteps, setMaxSteps] = useState(500);
  const [formInput, setFormInput] = useState(false),
    [authorized, setAuthorized] = useState(false),
    [memory, setMemory] = useState(true),
    [vision, setVision] = useState(false),
    [persist, setPersist] = useState(false);
  const [downloads, setDownloads] = useState(false);
  const [priority, setPriority] = useState(0);
  const [dependency, setDependency] = useState("");
  const [dataset, setDataset] = useState("");
  const [datasetQuery, setDatasetQuery] = useState("{}");
  const [outputFormat, setOutputFormat] = useState("");
  const [preview, setPreview] = useState<Planning | null>(null);
  const datasets = useQuery({
    queryKey: ["agent-datasets", token, website],
    queryFn: () => api<Collection<{ id: string; name: string; website_id: string }>>("/extraction/datasets?limit=100", token),
    enabled: Boolean(website),
  });
  const taskOptions = {
    objective, success_criteria: criteria.split("\n").filter(s => s.trim()), mode,
    max_steps: maxSteps, allow_form_input: formInput,
    allow_downloads: downloads, dataset_id: dataset || null, output_format: outputFormat || null,
  };
  const config = useQuery({
    queryKey: ["agent-config", token],
    queryFn: () => api<Config>("/agent/config", token),
  });
  const metrics = useQuery({
    queryKey: ["agent-metrics", token],
    queryFn: () => api<Metrics>("/agent/metrics", token),
  });
  useEffect(() => {
    if (config.data) setMaxSteps((n) => Math.min(n, config.data!.max_steps));
  }, [config.data?.max_steps]);
  const tasks = useQuery({
    queryKey: ["agent-tasks", token, page],
    queryFn: () =>
      api<Collection<Task>>(`/agent/tasks?limit=25&offset=${page * 25}`, token),
  });
  const memories = useQuery({
    queryKey: ["agent-memories", token],
    queryFn: () =>
      api<Collection<{ id: string; objective: string; content: unknown }>>(
        "/agent/memories",
        token,
      ),
  });
  function submit(e: FormEvent) {
    e.preventDefault();
    run(async () => {
      let identifier = website;
      if (!identifier) {
        const parsed = new URL(url);
        const site = await api<Website>("/websites", token, "POST", {
          name: parsed.hostname,
          base_url: url,
          allowed_domains: [parsed.hostname],
          authorized,
          configuration: {
            max_pages: 30,
            max_duration_seconds: 900,
            screenshots: true,
            delay_seconds: 1,
          },
        });
        identifier = site.id;
      }
      const result = await api<Task>(
        "/agent/tasks",
        token,
        "POST",
        {
          website_id: identifier,
          priority,
          depends_on: dependency || null,
          objective,
          success_criteria: criteria.split("\n").filter((s) => s.trim()),
          mode,
          max_steps: Math.min(maxSteps, config.data?.max_steps || 500),
          max_tokens: config.data?.max_tokens || 60000,
          memory_enabled: memory,
          visual_reasoning: vision,
          session_persistence: persist,
          allow_form_input: formInput,
          allow_downloads: downloads,
          dataset_id: dataset || null,
          output_format: outputFormat || null,
          dataset_query: datasetQuery.trim() === "{}" ? null : JSON.parse(datasetQuery),
        },
        { "Idempotency-Key": crypto.randomUUID() },
      );
      setSelected(result.id);
    });
  }
  if (selected)
    return (
      <AgentDetail
        id={selected}
        token={token}
        run={run}
        busy={busy}
        back={() => setSelected(null)}
      />
    );
  return (
    <>
      <section className="panel form-panel">
        <div className="panel-heading">
          <div>
            <h2>
              <BrainCircuit size={18} /> Goal-driven browser agent
            </h2>
            <p>
              Give the browser an objective. Follow its observations, decisions,
              and evidence.
            </p>
          </div>
          <Badge status={config.data?.configured ? "enabled" : "disabled"} />
        </div>
        {config.error && (
          <p role="alert" className="error">
            {config.error.message}
          </p>
        )}
        <details className="provider-settings">
          <summary>Model and provider settings</summary>
          <p>
            Provider: <strong>{config.data?.provider || "Loading"}</strong> ·
            Model: <strong>{config.data?.model || "Not configured"}</strong>
          </p>
          {config.data?.fallback_model && (
            <p>
              Fallback: <strong>{config.data.fallback_provider}</strong> ·
              Model: <strong>{config.data.fallback_model}</strong>
            </p>
          )}
          <p className="hint">
            Configure ADBOT_AI_PROVIDER, ADBOT_AI_MODEL and the provider key in
            the server .env, then restart the API and worker. Groq uses
            ADBOT_GROQ_BASE_URL and ADBOT_GROQ_API_KEY. Secrets stay on the
            server.
          </p>
          <p className="hint">
            Limits: {config.data?.max_steps} steps,{" "}
            {config.data?.max_tokens.toLocaleString()} tokens,{" "}
            {config.data?.max_tabs} tabs, {config.data?.max_concurrency}{" "}
            concurrent jobs.
          </p>
        </details>
        {!config.data?.configured && (
          <div role="status" className="alert error">
            The AI provider is disabled. Configure a model before starting a
            task.
          </div>
        )}
        <form onSubmit={submit} onChange={() => setPreview(null)}>
          <Field label="Natural-language objective">
            <textarea
              required
              minLength={8}
              maxLength={4000}
              value={objective}
              onChange={(e) => setObjective(e.target.value)}
              placeholder="Find three recent AI articles and summarize their main findings with source quotes."
            />
          </Field>
          <div className="form-grid">
            <Field label="Agent target">
              <select
                value={website}
                onChange={(e) => { setWebsite(e.target.value); setDataset(""); setPreview(null); }}
              >
                <option value="">Register a new URL</option>
                {sites.map((s) => (
                  <option value={s.id} key={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </Field>
            {!website && (
              <Field label="Task starting URL">
                <input
                  type="url"
                  required
                  placeholder="https://example.com/"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </Field>
            )}
            <Field label="Autonomy mode">
              <select value={mode} onChange={(e) => setMode(e.target.value)}>
                <option value="supervised">
                  Supervised — live progress and intervention
                </option>
                <option value="autonomous">
                  Autonomous — clicks and browsing
                </option>
                <option value="assisted">
                  Assisted — review other actions; autonomous clicks
                </option>
              </select>
            </Field>
            <Field label="Maximum agent steps">
              <input
                type="number"
                min={1}
                max={config.data?.max_steps || 500}
                value={maxSteps}
                onChange={(e) => setMaxSteps(+e.target.value)}
              />
            </Field>
          </div>
          <Field label="Success criteria (optional, one per line)">
            <textarea
              maxLength={10000}
              value={criteria}
              onChange={(e) => setCriteria(e.target.value)}
              placeholder="Find three relevant articles&#10;Include source citations for each finding"
            />
          </Field>
          <details className="agent-advanced">
            <summary>Dataset output, priority and dependencies</summary>
            <div className="form-grid">
            <Field label="Agent priority (-10 to 10)"><input type="number" min={-10} max={10} value={priority} onChange={e=>setPriority(+e.target.value)} /></Field>
            <Field label="Required successful job ID (optional)"><input maxLength={36} value={dependency} onChange={e=>setDependency(e.target.value)} /></Field>
            <Field label="Dataset filters, sort and limit (JSON)">
              <textarea value={datasetQuery} onChange={e => setDatasetQuery(e.target.value)} />
            </Field>
            <p className="hint">For the cheapest ten captured products, use {'{"sort":[{"field":"price","direction":"asc"}],"limit":10}'}. Applies to captured records.</p>
            <Field label="Structured extraction dataset">
              <select value={dataset} onChange={e => { setDataset(e.target.value); setPreview(null); }}>
                <option value="">Use target default (if configured)</option>
                {datasets.data?.items.filter(d => d.website_id === website).map(d => <option key={d.id} value={d.id}>{d.name}</option>)}
              </select>
            </Field>
            <Field label="Output format">
              <select value={outputFormat} onChange={e => { setOutputFormat(e.target.value); setPreview(null); }}>
                <option value="">From objective</option><option value="answer">Cited answer</option><option value="json">JSON artifact</option><option value="csv">CSV artifact</option>
              </select>
            </Field>
            </div>
          </details>
          <div className="checks">
            <label>
              <input
                type="checkbox"
                checked={memory}
                disabled={!config.data?.memory_enabled}
                onChange={(e) => setMemory(e.target.checked)}
              />
              Reuse successful task memory
            </label>
            <label>
              <input
                type="checkbox"
                checked={formInput}
                onChange={(e) => setFormInput(e.target.checked)}
              />
              Allow form input and search
            </label>
            <label>
              <input
                type="checkbox"
                checked={vision}
                disabled={!config.data?.visual_reasoning}
                onChange={(e) => setVision(e.target.checked)}
              />
              Vision-capable model
            </label>
            <label>
              <input
                type="checkbox"
                checked={downloads}
                onChange={(e) => setDownloads(e.target.checked)}
              />
              Allow bounded downloads
            </label>
            <label>
              <input
                type="checkbox"
                checked={persist}
                disabled={!config.data?.session_persistence}
                onChange={(e) => setPersist(e.target.checked)}
              />
              Encrypted browser session
            </label>
          </div>
          {!website && (
            <label className="check">
              <input
                type="checkbox"
                required
                checked={authorized}
                onChange={(e) => setAuthorized(e.target.checked)}
              />
              I authorize browser automation on this URL.
            </label>
          )}
          <div className="agent-submit-actions">
          <Button type="submit" disabled={busy || !config.data?.configured}>
            <Play size={15} />
            Start agent task
          </Button>
          <Button type="button" variant="outline" disabled={busy || !website || objective.length < 8} onClick={() => run(async () => {
            setPreview(await api<Planning>("/agent/preview", token, "POST", { ...taskOptions, dataset_query: datasetQuery.trim() === "{}" ? null : JSON.parse(datasetQuery), website_id: website }));
          })}>Preview task understanding</Button>
          </div>
          <p className="hint">Preview uses the selected saved target and current form values. Starting a task creates a fresh plan; complex tasks receive model decomposition in the worker.</p>
        </form>
        {preview && <AgentPlan planning={preview} />}
      </section>
      <div className="stats">
        {[
          ["Tasks", metrics.data?.tasks || 0],
          [
            "Verified success",
            metrics.data?.success_rate == null
              ? "—"
              : (metrics.data.success_rate * 100).toFixed(0) + "%",
          ],
          ["Average steps", (metrics.data?.average_steps || 0).toFixed(1)],
          ["Model tokens", metrics.data?.tokens || 0],
        ].map(([label, value]) => (
          <div className="stat" key={label}>
            <div>{label}</div>
            <strong>{value}</strong>
            <small>Persisted agent execution data</small>
          </div>
        ))}
      </div>
      <section className="panel">
        <div className="panel-heading">
          <h2>Agent task history</h2>
        </div>
        {tasks.error ? (
          <p role="alert" className="error">
            {tasks.error.message}
          </p>
        ) : !tasks.data?.items.length ? (
          <Empty text="Your agent tasks and verified results will appear here." />
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Objective</th>
                  <th>Mode</th>
                  <th>Status</th>
                  <th>Tokens</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {tasks.data.items.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <strong>{t.objective}</strong>
                      <small>{t.id.slice(0, 8)}</small>
                    </td>
                    <td>{t.mode}</td>
                    <td>
                      <Badge status={t.status} />
                    </td>
                    <td>{t.prompt_tokens + t.completion_tokens}</td>
                    <td>
                      <Button variant="ghost" onClick={() => setSelected(t.id)}>
                        Inspect task
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} total={tasks.data?.total || 0} setPage={setPage} />
      </section>
      <section className="panel form-panel">
        <h2>Reusable task memory</h2>
        <p className="hint">
          Successful, cited results are isolated to this workspace and target.
          The agent verifies historical hints against current pages.
        </p>
        {memories.data?.items.map((m) => (
          <details key={m.id}>
            <summary>{m.objective}</summary>
            <pre className="agent-json">
              {JSON.stringify(m.content, null, 2)}
            </pre>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                run(() => api("/agent/memories/" + m.id, token, "DELETE"))
              }
            >
              Forget memory
            </Button>
          </details>
        ))}
        {!memories.data?.items.length && (
          <p>No successful task memories yet.</p>
        )}
      </section>
    </>
  );
}

function AgentDetail({
  id,
  token,
  run,
  busy,
  back,
}: {
  id: string;
  token: string;
  run: Run;
  busy: boolean;
  back: () => void;
}) {
  const task = useQuery({
    queryKey: ["agent-task", id, token],
    queryFn: () => api<Task>("/agent/tasks/" + id, token),
  });
  const steps = useQuery({
    queryKey: ["agent-steps", id, token],
    queryFn: () =>
      api<Collection<Step>>(`/agent/tasks/${id}/steps?limit=100`, token),
  });
  const events = useJobEvents(id, token, task.data?.status, ["agent-task", "agent-steps"], 100);
  const latest = steps.data?.items.at(-1),
    pending = steps.data?.items.find(
      (s) => s.id === task.data?.pending_step_id,
    );
  const imageEvent = [...events]
    .reverse()
    .find((e) => typeof e.details.screenshot_path === "string");
  const capture =
    (imageEvent?.details.screenshot_path as string | undefined) ||
    latest?.observation.screenshot_path;
  const [image, setImage] = useState<string | null>(null),
    [answer, setAnswer] = useState("");
  useEffect(() => {
    if (!capture) return;
    const controller = new AbortController();
    let blobUrl: string | undefined;
    fetch("/api/artifacts/" + capture, {
      headers: { Authorization: "Bearer " + token },
      signal: controller.signal,
    })
      .then((r) => {
        if (!r.ok) throw new Error("Preview unavailable");
        return r.blob();
      })
      .then((blob) => {
        blobUrl = URL.createObjectURL(blob);
        setImage(blobUrl);
      })
      .catch(() => {});
    return () => {
      controller.abort();
      if (blobUrl) URL.revokeObjectURL(blobUrl);
    };
  }, [capture, token]);
  if (task.error)
    return (
      <p className="error" role="alert">
        {task.error.message}
      </p>
    );
  if (!task.data) return <Empty text="Loading agent task…" />;
  const t = task.data;
  return (
    <>
      <Button variant="ghost" onClick={back}>
        <ArrowLeft size={15} />
        All agent tasks
      </Button>
      <section className="panel form-panel">
        <div className="panel-heading">
          <div>
            <h2>{t.objective}</h2>
            <p>
              {t.mode} · {t.id}
            </p>
          </div>
          <Badge status={t.status} />
        </div>
        <div className="button-row">
          {!finished(t.status) && (
            <>
              <Button
                variant="outline"
                disabled={busy || t.status === "queued"}
                onClick={() =>
                  run(() =>
                    api(
                      `/jobs/${id}/${t.status === "paused" ? "resume" : "pause"}`,
                      token,
                      "POST",
                    ),
                  )
                }
              >
                {t.status === "paused" ? "Resume agent" : "Pause agent"}
              </Button>
              <Button
                variant="destructive"
                disabled={busy}
                onClick={() =>
                  run(() => api(`/jobs/${id}/cancel`, token, "POST"))
                }
              >
                Stop agent
              </Button>
            </>
          )}
          <span className="pill">
            {steps.data?.total || 0}/{t.options.max_steps} steps
          </span>
          <span className="pill">
            {t.prompt_tokens + t.completion_tokens} tokens · {t.model_calls}{" "}
            model calls
          </span>
          {t.budget && <span className="pill">{Math.floor(t.budget.elapsed_seconds)}s elapsed · {Math.floor(t.budget.remaining_seconds)}s budget remaining · {t.budget.remaining_tokens} tokens remaining</span>}
        </div>
        <JobFailure failure={t.failure} />
        {t.error_message && (
          <p className="error" role="alert">
            {t.error_message}
          </p>
        )}
      </section>
      {pending && (
        <section className="panel form-panel review-panel">
          <h2>Action needs your review</h2>
          <p>
            {pending.decision.decision === "ASK_USER"
              ? pending.decision.text
              : pending.decision.reason}
          </p>
          <p className="hint">
            {pending.decision.decision}{" "}
            {
              pending.observation.elements?.find(
                (e) => e.element_id === pending.decision.target?.element_id,
              )?.name
            }{" "}
            · {pending.decision.expected_result}
          </p>
          <Field label="Reply or additional instruction">
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
            />
          </Field>
          <div className="button-row">
            <Button
              disabled={
                busy ||
                (pending.decision.decision === "ASK_USER" && !answer.trim())
              }
              onClick={() =>
                run(
                  () =>
                    api(`/agent/tasks/${id}/review`, token, "POST", {
                      step_id: pending.id,
                      approved: true,
                      answer,
                    }),
                  () => setAnswer(""),
                )
              }
            >
              Approve and continue
            </Button>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                run(
                  () =>
                    api(`/agent/tasks/${id}/review`, token, "POST", {
                      step_id: pending.id,
                      approved: false,
                      answer,
                    }),
                  () => setAnswer(""),
                )
              }
            >
              Decline and replan
            </Button>
          </div>
        </section>
      )}
      <AgentPlan planning={t.planning} />
      <div className="agent-grid">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>Browser preview</h2>
              <p className="url">
                {latest?.observation.url || "Waiting for browser"}
              </p>
            </div>
            <RefreshCw size={15} />
          </div>
          {image ? (
            <img
              className="agent-preview"
              src={image}
              alt="Current agent browser page"
            />
          ) : (
            <Empty text="A real browser capture will appear after the first observation." />
          )}
        </section>
        <section className="panel form-panel">
          <h2>Current decision</h2>
          <p className="hint">
            <strong>{latest?.decision.decision || "Observing"}</strong> ·{" "}
            {latest?.decision.reason || "Waiting for the worker"}
          </p>
          <p>Expected: {latest?.decision.expected_result || "—"}</p>
          <h2 className="agent-subheading">Tabs and context</h2>
          {latest?.observation.tabs?.map((tab) => (
            <p className="hint url" key={tab.tab_id}>
              <strong>{tab.tab_id}</strong> {tab.purpose}
              <br />
              {tab.url}
            </p>
          ))}
          <details>
            <summary>Session memory</summary>
            <pre className="agent-json">
              {JSON.stringify(t.memory, null, 2)}
            </pre>
          </details>
          <SemanticObservation observation={latest?.observation} />
        </section>
      </div>
      {t.status === "completed" && t.result.verification?.complete && t.result.claims && (
        <section className="panel form-panel">
          <h2>Verified task result</h2>
          {t.status === "completed" && t.result.artifact && <Button disabled={busy} onClick={() => run(async () => {
            const response = await fetch(t.result.artifact!.download_url, { headers: { Authorization: "Bearer " + token } });
            if (!response.ok) throw new Error("Export unavailable or expired");
            const url = URL.createObjectURL(await response.blob());
            const link = document.createElement("a"); link.href = url; link.download = `agent-${id}.${t.result.artifact!.format}`; link.click();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
          })}>Download verified artifact</Button>}
          <p className="hint">{t.result.verification?.explanation}</p>
          {t.result.claims.map((claim, index) => (
            <div className="agent-claim" key={index}>
              <p>{claim.text}</p>
              <small>Citations: {claim.evidence_ids.join(", ")}</small>
            </div>
          ))}
          {t.result.evidence?.map((e) => (
            <blockquote key={e.id}>
              <p>{e.quote}</p>
              <a href={e.url} target="_blank" rel="noreferrer">
                {e.id} · {e.url}
              </a>
            </blockquote>
          ))}
        </section>
      )}
      <section className="panel">
        <div className="panel-heading">
          <h2>Observed actions and verification</h2>
          <p className="hint">These metrics describe automated sessions only. Filter X-AdBot-Automation or the AdBotMonitor user agent in your site analytics to exclude this traffic from visitor reports.</p>
        </div>
        {steps.error && (
          <p role="alert" className="error">
            {steps.error.message}
          </p>
        )}
        <div className="event-list">
          {steps.data?.items.map((step) => (
            <div className="event" key={step.id}>
              <span className="step-number">{step.number}</span>
              <div>
                <strong>
                  {step.decision.decision || "Observe"}{" "}
                  <Badge status={step.status} />
                </strong>
                <p className="hint">{step.decision.reason}</p>
                <small className="url">{step.observation.url}</small>
                <InteractionOutcome interaction={step.outcome.interaction} />
                <SemanticTrace semantic={step.outcome.semantic} interaction={step.outcome.interaction} resolution={step.outcome.trace?.find(s => s.phase === "resolution")} />
                {typeof step.outcome.error === "string" && <p className="error" role="status">{step.outcome.error}</p>}
                {!!step.outcome.trace?.length && <details>
                  <summary>Interaction trace · automated session</summary>
                  <table className="interaction-trace"><thead><tr><th scope="col">Phase</th><th scope="col">Started (UTC)</th><th scope="col">Duration</th><th scope="col">Status</th></tr></thead>
                    <tbody>{step.outcome.trace.map((span, i) => <tr key={i}>
                      <td>{span.phase}</td><td>{new Date(span.started_at * 1000).toISOString().slice(11, 23)}</td>
                      <td>{Math.round(span.duration_ms)} ms</td><td>{span.status}</td>
                    </tr>)}</tbody></table>
                </details>}
                <details>
                  <summary>Observation and outcome</summary>
                  <pre className="agent-json">
                    {JSON.stringify(
                      { decision: step.decision, outcome: step.outcome },
                      null,
                      2,
                    )}
                  </pre>
                </details>
              </div>
            </div>
          ))}
        </div>
      </section>
      <section className="panel form-panel">
        <details>
          <summary>Live execution events</summary>
          <pre className="agent-json">
            {events.map((e) => e.message).join("\n")}
          </pre>
        </details>
      </section>
    </>
  );
}
