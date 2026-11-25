import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ArrowLeft, BookOpen, ExternalLink, Plus, Search, Send, Square } from "lucide-react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, type Collection, type Event } from "./api";
import { subscribeEventStream, type StreamState } from "./useEventStream";
import "./research.css";

const ROOT = "/research/v1";
const TERMINAL = new Set(["cancelled", "failed", "completed"]);
const MODES = {
  auto: "Auto", direct: "Direct Answer", quick: "Quick Search", deep: "Deep Research",
  shopping: "Shopping", fact_check: "Fact Check", technical: "Technical Research", website_agent: "Website Agent",
};
type Mode = keyof typeof MODES;
type Source = {
  id: string; url: string; title: string; domain: string; published_at: string | null; retrieved_at: number;
  content_hash: string; query: string;
};
type Evidence = { id: string; source_id: string; quote: string; location: string; retrieved_at: number };
type Product = {
  name: string; brand: string; model: string; retailer: string; price: string | null; currency: string | null;
  availability: string | null; source_id: string; evidence_id: string; last_verified: number;
  variant: Record<string, string>; specifications: Record<string, string>; within_budget: boolean | null;
  geographic_match: string; warranty: string | null; shipping: string | null; review_summary: Record<string, string>;
};
type Claim = { text: string; kind: string; evidence: string[] };
type Task = {
  id: string; status: string; question: { question: string; mode: Mode; country?: string; freshness?: string };
  conversation_id: string; mode: Mode; error: string | null;
  result: { answer?: string; quality?: string; notes?: string[]; sources?: Source[]; products?: Product[]; claims?: Claim[] };
};
type Conversation = { id: string; title: string; updated_at: number; messages?: Task[] };
type ProviderConfig = { enabled: boolean; model_configured: boolean; providers: { name: string }[] };

function readDate(seconds: number) {
  return new Date(seconds * 1000).toLocaleString();
}

function safeURL(url?: string) {
  if (!url) return undefined;
  try {
    const parsed = new URL(url);
    return ["https:", "http:"].includes(parsed.protocol) && !parsed.username && !parsed.password ? parsed.href : undefined;
  } catch {
    return undefined;
  }
}

function SourceLink({ href, children }: { href: string; children: React.ReactNode }) {
  const safe = safeURL(href);
  return safe ? <a href={safe} target="_blank" rel="noreferrer noopener">{children}</a> : <span>{children}</span>;
}

function ProductResults({ products, sources }: { products: Product[]; sources: Source[] }) {
  if (!products.length) return null;
  const labels: Record<string, string> = {domain_hint: "Country domain", currency_hint: "Local currency", explicit: "Ships to market"};
  return <section className="research-products" aria-label="Product comparison">
    <h4>Product comparison</h4>
    <div className="research-table"><table>
      <thead><tr><th>Product</th><th>Retailer</th><th>Price</th><th>Availability</th><th>Verified</th></tr></thead>
      <tbody>{products.map((product) => <tr key={product.evidence_id}>
        <th scope="row"><SourceLink href={sources.find(s => s.id === product.source_id)?.url || ""}>{product.name}</SourceLink>
          <small>{[product.model, ...Object.values(product.variant)].filter(Boolean).join(" · ")}</small>
        </th>
        <td>{product.retailer}<small>{labels[product.geographic_match] || ""}</small></td>
        <td>{product.price ? `${product.currency} ${product.price}` : "Unverified"}
          {product.within_budget !== null && <small>{product.within_budget ? "Within budget" : "Above budget"}</small>}</td>
        <td>{product.availability || "Unverified"}</td><td>{readDate(product.last_verified)}</td>
      </tr>)}</tbody>
    </table></div>
    <ul className="research-product-cards">{products.slice(0, 8).map(p => <li key={p.evidence_id}>
      <details><summary>{p.name}</summary>
        <dl>{Object.entries({ Brand: p.brand, Model: p.model, Warranty: p.warranty, Shipping: p.shipping,
          Rating: p.review_summary.ratingValue, Reviews: p.review_summary.reviewCount || p.review_summary.ratingCount,
          ...p.specifications }).filter(([, value]) => value).map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
      </details>
    </li>)}</ul>
  </section>;
}

function Answer({ task, token, onRetry, retryDisabled }: {task: Task; token: string; onRetry: () => void; retryDisabled: boolean}) {
  const [open, setOpen] = useState(false);
  const [evidence, setEvidence] = useState<Evidence[]>([]);
  const [evidenceError, setEvidenceError] = useState("");
  const sources = task.result.sources || [];
  const products = task.result.products || [];
  const markdown = task.result.answer;
  useEffect(() => {
    if (!open || !sources.length) return;
    const controller = new AbortController();
    async function load() {
      const records: Evidence[] = [];
      let offset = 0;
      while (!controller.signal.aborted) {
        const page = await api<Collection<Evidence>>(
          `${ROOT}/tasks/${task.id}/evidence?limit=200&offset=${offset}`, token, "GET", undefined, undefined, controller.signal,
        );
        if (controller.signal.aborted) return;
        records.push(...page.items);
        setEvidence([...records]);
        setEvidenceError("");
        offset += page.items.length;
        if (!page.items.length || offset >= page.total) return;
      }
    }
    void load().catch(error => {if (!controller.signal.aborted) setEvidenceError((error as Error).message);});
    return () => controller.abort();
  }, [open, token, task.id, sources.length]);

  return <article className="research-turn">
    <h3 className="research-question">{task.question.question}</h3>
    {task.status === "failed" || task.status === "cancelled" ? <p role="status">{task.error || "Research was stopped."}</p> : null}
    {task.result.quality === "partial" && <p className="research-partial">Partial result</p>}
    {markdown && <div className="research-markdown">
      <Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img", "input"]}
        components={{a: ({href, children}) => <SourceLink href={href || ""}>{children}</SourceLink>}}>{markdown}</Markdown>
    </div>}
    {!!task.result.notes?.length && <ul className="research-notes">{task.result.notes.map(note => <li key={note}>{note}</li>)}</ul>}
    <ProductResults products={products} sources={sources} />
    {!!sources.length && <details className="research-sources" onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>Sources and evidence ({sources.length})</summary>
      {evidenceError && <p role="alert">{evidenceError}</p>}
      <ol>{sources.map(source => <li key={source.id}>
        <SourceLink href={source.url}>{source.title} <ExternalLink size={13} /></SourceLink>
        <p>{source.domain} · Retrieved {readDate(source.retrieved_at)}{source.published_at ? ` · Published ${source.published_at.slice(0, 10)}` : ""}</p>
        {evidence.filter(row => row.source_id === source.id).map(row =>
          <figure key={row.id}><blockquote>{row.quote}</blockquote><figcaption>{row.location}</figcaption></figure>)}
      </li>)}</ol>
    </details>}
    {(task.status === "failed" || task.status === "cancelled" || task.result.quality === "partial") &&
      <button type="button" className="research-button" onClick={onRetry} disabled={retryDisabled}>Retry</button>}
  </article>;
}

export default function Research() {
  const [token, setToken] = useState(() => sessionStorage.getItem("adbot-token") || "");
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [country, setCountry] = useState("");
  const [freshness, setFreshness] = useState("");
  const [thread, setThread] = useState<string | null>(null);
  const [history, setHistory] = useState<Conversation[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [config, setConfig] = useState<ProviderConfig>();
  const [progress, setProgress] = useState<Event[]>([]);
  const [stream, setStream] = useState<StreamState>("closed");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const active = tasks.find(t => !TERMINAL.has(t.status));

  const loadHistory = useCallback(async (signal?: AbortSignal) => {
    const result = await api<Collection<Conversation>>(`${ROOT}/conversations`, token, "GET", undefined, undefined, signal);
    if (!signal?.aborted) setHistory(result.items);
  }, [token]);

  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    function expired() {
      sessionStorage.removeItem("adbot-token");
      setToken("");
      setTasks([]);
      setHistory([]);
      setThread(null);
    }
    window.addEventListener("adbot:auth-expired", expired);
    Promise.all([
      loadHistory(controller.signal),
      api<ProviderConfig>(`${ROOT}/providers`, token, "GET", undefined, undefined, controller.signal)
        .then(value => {if (!controller.signal.aborted) setConfig(value);}),
    ]).catch(e => {if (!controller.signal.aborted) setError((e as Error).message);});
    return () => {controller.abort(); window.removeEventListener("adbot:auth-expired", expired);};
  }, [token, loadHistory]);

  const activeId = active?.id;
  useEffect(() => {
    if (!token || !activeId) return;
    const controller = new AbortController();
    let transport: StreamState = "connecting";
    setProgress([]);
    const check = async () => {
      try {
        const updated = await api<Task>(`${ROOT}/tasks/${activeId}`, token, "GET", undefined, undefined, controller.signal);
        if (!controller.signal.aborted) setTasks(current => current.map(task => task.id === activeId ? updated : task));
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      }
    };
    const unsubscribe = subscribeEventStream(`${ROOT}/tasks/${activeId}/events`, token, events => {
      if (controller.signal.aborted) return;
      setProgress(current => [...current, ...events].slice(-100));
      if (events.some(event => TERMINAL.has(event.event_type) || event.event_type === "cancellation_requested"
        || event.event_type === "recovered")) void check();
    }, state => {transport = state; setStream(state);});
    const poll = setInterval(() => {if (transport !== "open") void check();}, 4000);
    return () => {controller.abort(); unsubscribe(); clearInterval(poll);};
  }, [activeId, token]);

  async function openThread(id: string | null) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const details = id && await api<Conversation>(`${ROOT}/conversations/${id}`, token);
      setThread(id);
      setProgress([]);
      setTasks(details ? details.messages || [] : []);
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || active || busy || mode === "website_agent") return;
    setBusy(true);
    setError("");
    try {
      const result = await api<Task>(`${ROOT}/query`, token, "POST", {
        question: question.trim(), mode, conversation_id: thread,
        country: country.trim().toUpperCase() || null, freshness: freshness || null,
      }, {"Idempotency-Key": crypto.randomUUID()});
      setThread(result.conversation_id);
      setProgress([]);
      setTasks(items => [...items, result]);
      setQuestion("");
      await loadHistory();
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  async function control(task: Task, action: "cancel" | "retry") {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Task>(`${ROOT}/tasks/${task.id}/${action}`, token, "POST", undefined,
        {"Idempotency-Key": crypto.randomUUID()});
      if (action === "retry") setTasks(items => [...items, updated]);
      else {
        const current = await api<Task>(`${ROOT}/tasks/${task.id}`, token);
        setTasks(items => items.map(item => item.id === task.id ? current : item));
      }
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  if (!token) return <main className="research-logged-out"><h1>Web Research</h1><p>Connect your AdBot workspace to start a research conversation.</p>
    <a className="research-button" href="/">Connect workspace</a> <a href="/docs/web-research">Research documentation</a>
  </main>;

  const status = [...progress].reverse().find(event => event.event_type !== "answer_chunk");
  const chunks = progress.filter(event => event.event_type === "answer_chunk" && typeof event.details.text === "string");
  return <main className="research-shell">
    <header className="research-header"><a href="/"><ArrowLeft size={17}/> AdBot dashboard</a>
      <h1><Search size={22}/> Web Research</h1><a href="/docs/web-research"><BookOpen size={17}/> Help</a></header>
    <div className="research-grid">
      <aside className="research-history" aria-label="Research history">
        <button type="button" onClick={() => void openThread(null)} disabled={busy}><Plus size={17}/> New conversation</button>
        {history.map(item => <button key={item.id} type="button" aria-current={thread === item.id ? "page" : undefined}
          disabled={busy} onClick={() => void openThread(item.id)}>{item.title || "Untitled conversation"}</button>)}
      </aside>
      <section className="research-chat" aria-label="Research conversation">
        {config && !config.enabled && <p role="status" className="research-partial">Research is disabled. Ask the workspace operator to enable it.</p>}
        {config?.enabled && !config.providers.length && <p role="status" className="research-partial">No search providers are configured.</p>}
        {config?.enabled && !config.model_configured && <p role="status" className="research-partial">A model provider is needed for answer synthesis.</p>}
        {!tasks.length && <div className="research-empty"><h2>What would you like to research?</h2>
          {["What are the latest developments in quantum computing?", "Find affordable AI engineering laptops in Nigeria",
            "Compare PostgreSQL and Cassandra for high-throughput applications"].map(text =>
              <button key={text} type="button" onClick={() => setQuestion(text)}>{text}</button>)}
        </div>}
        {tasks.map(task => <Answer key={task.id} task={task} token={token} retryDisabled={!!active || busy} onRetry={() => void control(task, "retry")} />)}
        {active && <div className="research-running"><div role="status" aria-live="polite">
          <strong>{status?.message || "Research queued"}</strong>
          {stream === "backoff" && <small> Reconnecting to progress updates.</small>}
          {chunks.map(chunk => <div key={chunk.id}><Markdown skipHtml disallowedElements={["img", "input"]} components={{a: ({href, children}) =>
            <SourceLink href={href || ""}>{children}</SourceLink>}}>{String(chunk.details.text)}</Markdown></div>)}
        </div><button type="button" className="research-button" disabled={busy} onClick={() => void control(active, "cancel")}><Square size={14}/> Stop</button></div>}
        {error && <p className="research-error" role="alert">{error}</p>}
        <form className="research-composer" onSubmit={submit}>
          <label htmlFor="research-question">Question</label>
          <textarea id="research-question" value={question} onChange={e => setQuestion(e.target.value)} rows={3} maxLength={1400}
            placeholder={thread ? "Ask a follow-up question" : "Ask a question or compare products"} />
          <div className="research-options">
            <label>Mode<select value={mode} onChange={e => setMode(e.target.value as Mode)}>
              {Object.entries(MODES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select></label>
            <label>Country code<input value={country} onChange={e => setCountry(e.target.value)} maxLength={2} pattern="[A-Za-z]{2}" placeholder="NG" /></label>
            <label>Freshness<select value={freshness} onChange={e => setFreshness(e.target.value)}>
              <option value="">Any time</option><option value="day">Past day</option><option value="week">Past week</option>
              <option value="month">Past month</option><option value="year">Past year</option>
            </select></label>
            {mode === "website_agent" ? <a className="research-primary" href="/?tab=agent">Open Website Agent</a> :
              <button className="research-primary" disabled={busy || !!active || !question.trim() || config?.enabled === false}><Send size={16}/> Send</button>}
          </div>
        </form>
      </section>
    </div>
  </main>;
}
