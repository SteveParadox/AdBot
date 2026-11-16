export class ApiError extends Error { constructor(message: string, public status: number) { super(message); this.name="ApiError"; } }
export type Collection<T> = { items: T[]; total: number };
export type Config = {
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
export async function api<T>(
  path: string,
  token: string,
  method = "GET",
  data?: unknown,
  extraHeaders?: Record<string, string>,
): Promise<T> {
  const now = Date.now();
  for (const [key, until] of cooldowns) if (until <= now) cooldowns.delete(key);
  const until = cooldowns.get(token) || 0;
  if (until > now) throw new ApiError(`Too many requests. Retry in ${Math.ceil((until-now)/1000)} seconds.`, 429);
  const response = await fetch("/api" + path, {
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
  return response.status === 204 ? (undefined as T) : response.json();
}

export function parseEvents(buffer: string) {
  const chunks = buffer.replace(/\r/g, "").split("\n\n");
  const remaining = chunks.pop() || "";
  const events: Event[] = [];
  for (const chunk of chunks) {
    const data = chunk.split("\n").find((line) => line.startsWith("data: "));
    if (data) events.push(JSON.parse(data.slice(6)));
  }
  return { events, remaining };
}
