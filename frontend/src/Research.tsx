import { useCallback, useEffect, useRef, useState } from "react";
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
  credibility?: { role_hint: string; signals: string[]; assessment: string };
  independence_assessment?: { registrable_domain: string; possible_shared_origin: boolean; method: string };
  metadata?: { document_type?: string; page_count?: number; pages_examined?: number; extraction_truncated?: boolean; pages_with_text?: number[] };
};
type Evidence = { id: string; source_id: string; quote: string; location: string; retrieved_at: number; page?: number };
type SuitabilityCheck = { requirement: string; observed: string | null; status: "met" | "not_met" | "unknown" };
type Product = {
  name: string; brand: string; model: string; retailer: string; price: string | null; currency: string | null;
  availability: string | null; source_id: string; evidence_id: string; last_verified: number;
  variant: Record<string, string>; specifications: Record<string, string>; within_budget: boolean | null;
  geographic_match: string; warranty: string | null; shipping: string | null; review_summary: Record<string, string>;
  extraction_method?: string; comparison_group?: string | null; comparable_sources?: number; budget_requested?: boolean;
  suitability?: { status: "met" | "not_met" | "unknown" | "not_requested"; requirements: SuitabilityCheck[]; workload_hints: SuitabilityCheck[]; score: number };
};
type Claim = { text: string; kind: string; evidence: string[] };
type ResearchSubquestion = {
  id: string; question: string; status: "covered" | "partial" | "missing" | "conflicting";
  evidence: string[]; searches: number; used_in_answer: boolean;
};
type ConversationContext = {
  anchor_id?: string | null; constraints?: string; country?: string | null; freshness?: string | null;
  references?: {kind: "source" | "product"; index: number; name: string; turn_id: string}[];
  unresolved?: string[];
};
type Task = {
  id: string; status: string; question: { question: string; mode: Mode; country?: string; freshness?: string };
  conversation_id: string; mode: Mode; error: string | null;
  result: { answer?: string; quality?: string; notes?: string[]; sources?: Source[]; products?: Product[]; claims?: Claim[]; research_plan?: ResearchSubquestion[]; coverage_rounds?: number; conversation_context?: ConversationContext };
};
type Conversation = { id: string; title: string; updated_at: number; messages?: Task[]; total?: number };
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

function pdfPageURL(source: Source | undefined, page: number): string | undefined {
  const url = safeURL(source?.url);
  if (!url || source?.metadata?.document_type !== "pdf" || !Number.isSafeInteger(page) || page < 1 ||
      page > (source.metadata.pages_examined ?? 0)) return undefined;
  const parsed = new URL(url);
  parsed.hash = `page=${page}`;
  return parsed.href;
}

function AnswerMarkup({ text, sources = [], direct = false }: {text: string; sources?: Source[]; direct?: boolean}) {
  return <Markdown remarkPlugins={[remarkGfm]} skipHtml disallowedElements={["img", "input"]}
    components={{a: ({href, children}) => {
      const match = typeof children === "string" ? /^([1-9]\d*)(?: p\. ([1-9]\d*))?$/.exec(children) : null;
      const citation = match ? sources[Number(match[1]) - 1] : undefined;
      const expected = match?.[2] ? pdfPageURL(citation, Number(match[2])) : safeURL(citation?.url);
      return direct || (expected && safeURL(href) === expected)
        ? <SourceLink href={href || ""}>{children}</SourceLink>
        : <span>{children}</span>;
    }}}>{text}</Markdown>;
}

type PendingMutation = { body: string; key: string };
function idempotencyHeaders(slot: {current: PendingMutation | null}, body: string) {
  if (slot.current?.body !== body) {
    // getRandomValues also works when Adbot is served over HTTP on a LAN.
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    slot.current = {body, key: Array.from(bytes, byte => byte.toString(16).padStart(2, "0")).join("")};
  }
  return {"Idempotency-Key": slot.current.key};
}

function ProductResults({ products, sources }: { products: Product[]; sources: Source[] }) {
  if (!products.length) return null;
  const labels: Record<string, string> = {domain_hint: "Country domain", currency_hint: "Local currency", explicit: "Ships to market"};
  return <section className="research-products" aria-label="Product comparison">
    <h4>Product comparison</h4>
    <div className="research-table"><table>
      <thead><tr><th>Product</th><th>Retailer</th><th>Price</th><th>Availability</th><th>Requirement fit</th><th>Verified</th></tr></thead>
      <tbody>{products.map((product, index) => <tr key={product.evidence_id}>
        <th scope="row"><SourceLink href={sources.find(s => s.id === product.source_id)?.url || ""}>{index + 1}. {product.name}</SourceLink>
          <small>{[product.model, ...Object.values(product.variant)].filter(Boolean).join(" · ")}</small>
        </th>
        <td>{product.retailer}<small>{labels[product.geographic_match] || ""}</small></td>
        <td>{product.price ? `${product.currency} ${product.price}` : "Unverified"}
          {product.within_budget != null ? <small>{product.within_budget ? "Within budget" : "Above budget"}</small> :
            product.budget_requested ? <small>Budget fit unverified</small> : null}</td>
        <td>{product.availability || "Unverified"}</td>
        <td>{product.suitability?.status === "met" ? "Observed requirements met" : product.suitability?.status === "not_met" ? "Does not meet requirements" : product.suitability?.status === "unknown" ? "Specifications incomplete" : "No explicit specification constraints"}
          {(product.comparable_sources || 0) > 1 && <small>Matching identifier/configuration at {product.comparable_sources} retailer domains</small>}</td>
        <td>{readDate(product.last_verified)}</td>
      </tr>)}</tbody>
    </table></div>
    <p>Prices are retailer observations, not guaranteed checkout totals. Different currencies are not directly compared. Workload hints are not compatibility or performance guarantees.</p>
    <ul className="research-product-cards">{products.map(p => <li key={p.evidence_id}>
      <details><summary>{p.name}</summary>
        <dl>{Object.entries({ Brand: p.brand, Model: p.model, Condition: p.variant.condition, Extraction: p.extraction_method === "dom" ? "Observed product page" : p.extraction_method === "json-ld" ? "Retailer structured metadata" : undefined, Warranty: p.warranty, Shipping: p.shipping,
          Rating: p.review_summary.ratingValue, Reviews: p.review_summary.reviewCount || p.review_summary.ratingCount,
          ...p.specifications }).filter(([, value]) => value).map(([label, value]) =>
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
        {!!p.suitability?.requirements.length && <ul>{p.suitability.requirements.map((check, i) => <li key={i}>{check.requirement}: {check.observed || "Not established"} ({check.status.replace("_", " ")})</li>)}</ul>}
        {!!p.suitability?.workload_hints.length && <><p>Workload heuristics:</p><ul>{p.suitability.workload_hints.map((check, i) => <li key={i}>{check.requirement}: {check.observed || "Not established"} ({check.status.replace("_", " ")})</li>)}</ul></>}
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
      <AnswerMarkup text={markdown} sources={sources} direct={task.mode === "direct"} />
    </div>}
    {!!task.result.notes?.length && <ul className="research-notes">{task.result.notes.map(note => <li key={note}>{note}</li>)}</ul>}
    {task.result.conversation_context?.anchor_id && <details className="research-sources">
      <summary>Conversation context used</summary>
      <p>{task.result.conversation_context.constraints || "No explicit shopping constraints carried forward."}</p>
      {task.result.conversation_context.country && <p>Market: {task.result.conversation_context.country}</p>}
      {task.result.conversation_context.freshness && <p>Freshness: {task.result.conversation_context.freshness}</p>}
      {!!task.result.conversation_context.references?.length && <ul>{task.result.conversation_context.references.map((ref, index) =>
        <li key={index}>{ref.kind} {ref.index}: {ref.name}</li>)}</ul>}
      {!!task.result.conversation_context.unresolved?.length && <p>Unresolved: {task.result.conversation_context.unresolved.join(", ")}</p>}
    </details>}
    {!!task.result.research_plan?.length && <details className="research-sources">
      <summary>Research coverage ({task.result.research_plan.filter(q => q.used_in_answer).length}/{task.result.research_plan.length} addressed)</summary>
      <ul>{task.result.research_plan.map(q => <li key={q.id}>
        <strong>{q.question}</strong>
        <p>{q.status === "covered" ? (q.used_in_answer ? "Covered and cited" : "Evidence collected, not cited in answer") :
          q.status === "partial" ? "Partial evidence" : q.status === "conflicting" ? "Conflicting evidence" : "Missing evidence"}
          {" · "}{q.searches} targeted {q.searches === 1 ? "query" : "queries"}</p>
      </li>)}</ul>
    </details>}
    <ProductResults products={products} sources={sources} />
    {!!sources.length && <details className="research-sources" onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>Sources and evidence ({sources.length})</summary>
      {evidenceError && <p role="alert">{evidenceError}</p>}
      <ol>{sources.map(source => <li key={source.id}>
        <SourceLink href={source.url}>{source.title} <ExternalLink size={13} /></SourceLink>
        {source.metadata?.document_type === "pdf" && <p>PDF · {source.metadata.pages_examined} of {source.metadata.page_count} pages examined{source.metadata.extraction_truncated ? " · extraction limited" : ""}</p>}
        <p>{source.domain} · Retrieved {readDate(source.retrieved_at)}{source.published_at ? ` · Published ${source.published_at.slice(0, 10)}` : ""}</p>
        {!!source.credibility?.signals.length && <p>Source signals (heuristic): {source.credibility.signals.join(" · ")}</p>}
        {source.independence_assessment?.possible_shared_origin && <p>Possible shared origin with another source; not counted as independent corroboration.</p>}
        {evidence.filter(row => row.source_id === source.id).map(row =>
          <figure key={row.id}><blockquote>{row.quote}</blockquote><figcaption>{row.location}{row.page && pdfPageURL(source, row.page) && <> · <SourceLink href={pdfPageURL(source, row.page)!}>Open page {row.page}</SourceLink></>}</figcaption></figure>)}
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
  const [turnCount, setTurnCount] = useState(0);
  const submission = useRef<PendingMutation | null>(null);
  const retryMutation = useRef<PendingMutation | null>(null);
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
      setTurnCount(0);
      submission.current = null;
      retryMutation.current = null;
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
      setTurnCount(details ? details.total ?? details.messages?.length ?? 0 : 0);
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  async function loadEarlierTurns() {
    if (!thread || busy) return;
    setBusy(true);
    setError("");
    try {
      const details = await api<Conversation>(`${ROOT}/conversations/${thread}?offset=${tasks.length}`, token);
      const alreadyLoaded = new Set(tasks.map(task => task.id));
      setTasks(items => [...(details.messages || []).filter(task => !alreadyLoaded.has(task.id)), ...items]);
      setTurnCount(details.total ?? turnCount);
    } catch (e) {setError((e as Error).message);}
    finally {setBusy(false);}
  }

  function appendTask(result: Task) {
    if (tasks.some(task => task.id === result.id)) return;
    setTasks(items => [...items, result]);
    setTurnCount(count => count + 1);
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!question.trim() || active || busy || mode === "website_agent") return;
    setBusy(true);
    setError("");
    const data = {
      question: question.trim(), mode, conversation_id: thread,
      country: country.trim().toUpperCase() || null, freshness: freshness || null,
    };
    try {
      const result = await api<Task>(`${ROOT}/query`, token, "POST", data,
        idempotencyHeaders(submission, JSON.stringify(data)));
      submission.current = null;
      setThread(result.conversation_id);
      setProgress([]);
      appendTask(result);
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
      const headers = action === "retry" ? idempotencyHeaders(retryMutation, task.id) : undefined;
      const updated = await api<Task>(`${ROOT}/tasks/${task.id}/${action}`, token, "POST", undefined, headers);
      if (action === "retry") {
        retryMutation.current = null;
        appendTask(updated);
      } else {
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
        {turnCount > tasks.length && <button type="button" className="research-button" disabled={busy}
          onClick={() => void loadEarlierTurns()}>Load earlier turns</button>}
        {tasks.map(task => <Answer key={task.id} task={task} token={token} retryDisabled={!!active || busy} onRetry={() => void control(task, "retry")} />)}
        {active && <div className="research-running"><div role="status" aria-live="polite">
          <strong>{status?.message || "Research queued"}</strong>
          {stream === "backoff" && <small> Reconnecting to progress updates.</small>}
          {chunks.map(chunk => <div key={chunk.id}><AnswerMarkup text={String(chunk.details.text)}
            direct={active.mode === "direct"} /></div>)}
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
