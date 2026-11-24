import { waitForInitialCursor } from "./queryBarrier";
import { count } from "./traffic";
export class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name="ApiError"; } }
export type Collection<T> = { items: T[]; total: number };
export type Config = {
  extraction_dataset_id?: string | null;
  max_pages: number;
  max_depth: number;
  navigation_timeout_ms: number;
  delay_seconds: number;
  max_duration_seconds: number;
  headless: boolean;
  viewport: string;
  browser: string;
  screenshots: boolean;
  discover_links: boolean;
  scroll: boolean;
  respect_robots: boolean;
  retries: number;
  wait_until: string;
  wait_selector: string | null;
  allowed_patterns: string[];
  excluded_patterns: string[];
};
export const defaults: Config = {
  max_pages: 10,
  max_depth: 2,
  navigation_timeout_ms: 30000,
  delay_seconds: 2,
  max_duration_seconds: 600,
  headless: true,
  viewport: "desktop",
  browser: "chromium",
  screenshots: false,
  discover_links: true,
  scroll: false,
  respect_robots: true,
  retries: 2,
  wait_until: "domcontentloaded",
  wait_selector: null,
  allowed_patterns: ["*"],
  excluded_patterns: [],
};
export type Website = {
  id: string;
  name: string;
  base_url: string;
  allowed_domains: string[];
  configuration: Config;
};
export type Job = {
  priority: number;
  depends_on: string | null;
  id: string;
  website_id: string;
  job_type: string;
  status: string;
  pages_visited: number;
  created_at: number;
  started_at: number | null;
  completed_at: number | null;
  error_message: string | null;
  failure?: { category: string; stage: string; last_successful_action: {action: string; step: number | null} | null; retry_eligible: boolean; automatic_retry_scheduled: boolean; suggested_recovery: string } | null;
  discovered_count?: number;
};
export type Visit = {
  id: number;
  requested_url: string;
  final_url: string;
  page_title: string;
  http_status: number | null;
  navigation_duration_ms: number;
  visited_at: number;
  screenshot_path: string | null;
  error: string | null;
};
export type Event = {
  snapshot_batch?: boolean;
  job_id?: string;
  change_cursor?: number;
  server_epoch?: string;
  resource?: {job?: Job; task?: Record<string, unknown>; steps?: {id: number; number: number; [key: string]: unknown}[]; dataset_id?: string | null};
  id: number;
  event_type: string;
  message: string;
  details: Record<string, unknown>;
  timestamp: number;
};
export type Step = {
  action: string;
  selector?: string;
  url?: string;
  text?: string;
  seconds?: number;
  pixels?: number;
  timeout_ms?: number;
  authorized?: boolean;
};
export type Workflow = {
  id: string;
  website_id: string;
  name: string;
  definition: { schema_version: 1; steps: Step[] };
  version: number;
  enabled: boolean;
};
export type Schedule = {
  id: string;
  website_id: string;
  workflow_id: string | null;
  cron_expression: string | null;
  timezone: string;
  next_run_at: number;
  enabled: boolean;
};
export type Overview = {
  websites: number;
  jobs: number;
  statuses: Record<string, number>;
  pages: number;
  average_ms: number;
  failure_rate: number;
  scheduled_jobs: number;
  scheduled_success_rate: number | null;
  daily_pages: { day: number; count: number }[];
  http_statuses: { status: string | number; count: number }[];
};

// Share a cooldown across endpoints in this tab so polling cannot keep hitting a
// workspace that the server has already rate limited. Never persist credentials.
const cooldowns = new Map<string, number>();
type PendingRead = {token: string; promise: Promise<unknown>; controller: AbortController; consumers: number; settled: boolean; abortTimer?: ReturnType<typeof setTimeout>};
const pendingReads = new Map<string, PendingRead>();
type MutationListener = (path: string, token: string, requestId?: string) => Promise<unknown>;
const mutationListeners = new Set<MutationListener>();
export function discardSessionReads(token: string) {
  for (const [key, entry] of pendingReads) if (entry.token === token) {
    entry.controller.abort(); pendingReads.delete(key);
  }
}
export function onApiMutation(listener: MutationListener) {
  mutationListeners.add(listener);
  return () => { mutationListeners.delete(listener); };
}

export function api<T>(
  path: string, token: string, method = "GET", data?: unknown,
  extraHeaders?: Record<string, string>, signal?: AbortSignal,
): Promise<T> {
  if (signal?.aborted) return Promise.reject(new DOMException("Request cancelled", "AbortError"));
  if (method !== "GET") return request<T>(path, token, method, data, extraHeaders, signal);
  const key = JSON.stringify([token, path, Object.entries(extraHeaders || {}).sort()]);
  let pending = pendingReads.get(key);
  if (pending?.controller.signal.aborted) pending = undefined;
  if (!pending) {
    if (pendingReads.size >= 256) return Promise.reject(new ApiError("Request capacity reached", 429));
    const controller = new AbortController();
    pending = {token, controller, consumers: 0, settled: false, promise: Promise.resolve()};
    const entry = pending;
    entry.promise = request<T>(path, token, method, data, extraHeaders, controller.signal).finally(() => {
      entry.settled = true;
      if (pendingReads.get(key) === entry) pendingReads.delete(key);
    });
    pendingReads.set(key, entry);
  } else count("deduplicated_reads");
  const entry = pending;
  clearTimeout(entry.abortTimer);
  // Uncancellable callers share the original promise, preserving existing API behavior.
  if (!signal) {
    entry.consumers++;
    void entry.promise.then(() => {entry.consumers--;}, () => {entry.consumers--;});
    return entry.promise as Promise<T>;
  }
  entry.consumers++;
  return new Promise<T>((resolve, reject) => {
    let finished = false;
    function release() {
      if (finished) return false;
      finished = true;
      signal!.removeEventListener("abort", abort);
      entry.consumers--;
      if (!entry.settled && entry.consumers === 0) {
        // Let a Strict Mode remount attach before cancelling the shared transport.
        entry.abortTimer = setTimeout(() => {
          if (!entry.settled && entry.consumers === 0) {count("cancelled_reads"); entry.controller.abort();}
        }, 15);
      }
      return true;
    }
    function abort() { if (release()) reject(new DOMException("Request cancelled", "AbortError")); }
    signal.addEventListener("abort", abort, {once: true});
    entry.promise.then(value => {if (release()) resolve(value as T);}, error => {if (release()) reject(error);});
  });
}

export async function queryApi<T>(path: string, token: string, signal: AbortSignal) {
  await waitForInitialCursor(token, signal);
  return api<T>(path, token, "GET", undefined, undefined, signal);
}

async function request<T>(
  path: string,
  token: string,
  method = "GET",
  data?: unknown,
  extraHeaders?: Record<string, string>,
  signal?: AbortSignal,
): Promise<T> {
  const now = Date.now();
  for (const [key, until] of cooldowns) if (until <= now) cooldowns.delete(key);
  const until = cooldowns.get(token) || 0;
  if (until > now) throw new ApiError(`Too many requests. Retry in ${Math.ceil((until-now)/1000)} seconds.`, 429);
  signal = signal ? AbortSignal.any([signal, AbortSignal.timeout(30000)]) : AbortSignal.timeout(30000);
  count("http_requests");
  const response = await fetch("/api" + path, {
    signal,
    method,
    headers: {
      Authorization: "Bearer " + token,
      ...(data ? { "Content-Type": "application/json" } : {}),
      ...extraHeaders,
    },
    body: data ? JSON.stringify(data) : undefined,
  });
  if (response.status === 429) {
    const header = response.headers.get("Retry-After");
    const seconds = header && /^\d+$/.test(header) ? Number(header) : header ? (Date.parse(header)-Date.now())/1000 : 60;
    const delay = Number.isFinite(seconds) ? Math.max(1, seconds) : 60;
    if (cooldowns.size >= 512) cooldowns.delete(cooldowns.keys().next().value!);
    cooldowns.set(token, Date.now()+delay*1000);
  }
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ detail: "Request failed" }));
    throw new ApiError(
      typeof body.detail === "string"
        ? body.detail
        : JSON.stringify(body.detail), response.status,
    );
  }
  const result = response.status === 204 ? (undefined as T) : await response.json();
  if (method !== "GET") {
    // Cache refresh failure must not turn a successful write into a failed write.
    const requestId = response.headers.get("X-Request-ID");
    const noticePath = method === "DELETE" ? path.split("?")[0] + "/deleted" : path;
    await Promise.allSettled([...mutationListeners].map(listener => requestId ? listener(noticePath, token, requestId) : listener(noticePath, token)));
  }
  return result;
}

export function parseEvents(buffer: string) {
  if (buffer.length > 2_000_000) throw new Error("SSE frame capacity exceeded");
  const chunks = buffer.replace(/\r/g, "").split("\n\n");
  const remaining = chunks.pop() || "";
  const events: Event[] = [];
  for (const chunk of chunks) {
    const data = chunk.split("\n").filter(line => line.startsWith("data:"))
      .map(line => line.slice(5).replace(/^ /, "")).join("\n");
    if (!data) continue;
    const event = JSON.parse(data);
    if (!Number.isSafeInteger(event.id) || event.id < 0) throw new Error("Invalid event cursor");
    events.push(event);
  }
  return { events, remaining };
}
