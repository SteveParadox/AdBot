import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { ApiError } from "./api";
import type { StreamState } from "./useEventStream";
import { count } from "./traffic";

const states = new WeakMap<QueryClient, StreamState>();
const fallbackFamilies = new Set(["jobs", "recent-jobs", "agent-tasks", "job", "agent-task", "agent-steps", "pages", "logs", "extraction"]);
export function setRealtimeState(client: QueryClient, state: StreamState) {
  const previous = states.get(client);
  if (previous === state || (state === "connecting" && (previous === "backoff" || previous === "exhausted"))) return;
  states.set(client, state);
  for (const query of client.getQueryCache().getAll()) query.setState({});
  if (["backoff", "exhausted"].includes(state) && !["backoff", "exhausted"].includes(previous || "")) {
    void client.refetchQueries({type: "active", predicate: query => fallbackEligible(client, query.queryKey, query.state.data)}, {cancelRefetch: false});
  }
}
function fallbackEligible(client: QueryClient, key: QueryKey, data: unknown) {
  const family = String(key[0]);
  if (!fallbackFamilies.has(family)) return false;
  if (family === "extraction" && !["records", "changes", "runs", "exports"].includes(String(key[2]))) return false;
  const record = data as {status?: string} | undefined;
  let status = record?.status;
  if (["agent-steps", "pages", "logs"].includes(family)) {
    const token = key.at(-1);
    const task = client.getQueryData<{status: string}>(["agent-task", key[1], token]) || client.getQueryData<{status: string}>(["job", key[1], token]);
    status = task?.status;
  }
  return !["completed", "failed", "cancelled"].includes(status || "");
}
export function createQueryClient() {
  const client: QueryClient = new QueryClient({defaultOptions: {queries: {
    staleTime: Infinity, gcTime: 5 * 60 * 1000,
    refetchInterval: false, refetchIntervalInBackground: false, refetchOnWindowFocus: false,
    retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status >= 500),
  }}});
  for (const family of fallbackFamilies) client.setQueryDefaults([family], {refetchInterval: query =>
    ["backoff", "exhausted"].includes(states.get(client) || "") && fallbackEligible(client, query.queryKey, query.state.data) ? 30000 : false});
  client.setQueryDefaults(["agent-metrics"], {staleTime: 15000, refetchInterval: () => states.get(client) === "unauthorized" ? false : 15000});
  client.setQueryDefaults(["overview"], {staleTime: 30000, refetchInterval: () => states.get(client) === "unauthorized" ? false : 60000});
  for (const key of ["automation", "schedules"]) client.setQueryDefaults([key], {staleTime: 15000, refetchInterval: 30000});
  client.getQueryCache().subscribe(event => {
    if (event.type === "observerAdded") count(event.query.state.data === undefined ? "cache_misses" : "cached_observer_mounts");
    if (event.type === "observerResultsUpdated") count("query_observer_updates");
    if (event.type === "updated" && event.action.type === "fetch") count("query_fetches");
    if (event.type === "updated" && event.action.type === "invalidate") count("query_invalidations");
  });
  return client;
}

function mutationFamilies(path: string, token?: string): readonly QueryKey[] {
  const [root, id, action, operation] = path.split("?")[0].split("/").filter(Boolean);
  const extraction = (kind: string, dataset?: string): QueryKey => ["extraction", token, kind, ...(dataset ? [dataset] : [])];
  if (root === "websites") return action === "deleted" ? [["websites"], ["workflows"], ["schedules"], ["jobs"], ["recent-jobs"], ["agent-tasks"], ["agent-datasets"], extraction("datasets"), ["overview"]] : [["websites"]];
  if (root === "workflows") return [["workflows"]];
  if (root === "schedules") return [["schedules"], ["overview"]];
  if (root === "jobs") return [["jobs"], ["recent-jobs"], ["automation"], ["agent-tasks"], ...["job", "pages", "logs", "agent-task", "agent-steps"].map(key => [key, id])];
  if (root === "agent" && id === "tasks") return [["agent-tasks"], ["recent-jobs"], ["jobs"], ...(action ? [["agent-task", action], ["agent-steps", action]] : [])];
  if (root === "agent" && id === "config") return [["agent-config"]];
  if (root === "agent" && id === "memories") return [["agent-memories"]];
  if (root === "extraction" && id === "schemas") return action === "validate" ? [] : [extraction("schemas")];
  if (root === "extraction" && id === "datasets") {
    if (operation === "deleted") return [extraction("datasets"), ["agent-datasets"], ["websites"], ...["records", "changes", "runs", "exports"].map(kind => extraction(kind, action))];
    if (operation === "run") return [extraction("runs", action), ["jobs"], ["recent-jobs"]];
    if (operation === "exports") return [extraction("exports", action)];
    if (operation === "schedules") return [["schedules"]];
    if (operation === "bind") return [["websites"]];
    return [extraction("datasets"), ["agent-datasets"]];
  }
  if (root === "admin" && id === "content") return [["content"], ["admin-content"]];
  if (root === "admin" && id === "automation") return [["automation"]];
  if (root === "admin" && id === "user-agents") return [["user-agents"]];
  return [];
}

export function mutationKeys(path: string, token?: string, client?: QueryClient): readonly QueryKey[] {
  const keys = mutationFamilies(path, token).map(key => {
    if (!token || key[0] === "content" || key[0] === "extraction") return key;
    if (key.length === 1) return [key[0], token];
    if (["job", "agent-task", "agent-steps", "logs"].includes(String(key[0]))) return [...key, token];
    return key;
  });
  if (token && client && /^\/websites\/[^/]+\/deleted$/.test(path)) {
    const websiteId = path.split("/")[2], jobIds = new Set<string>();
    for (const query of client.getQueryCache().getAll()) {
      if (!query.queryKey.includes(token)) continue;
      const data = query.state.data as {website_id?: string; id?: string; items?: {id: string; website_id?: string}[]} | undefined;
      if (data?.website_id === websiteId && data.id) jobIds.add(data.id);
      for (const item of data?.items || []) if (item.website_id === websiteId) jobIds.add(item.id);
    }
    for (const query of client.getQueryCache().getAll()) {
      if (query.queryKey.includes(token) && jobIds.has(String(query.queryKey[1])) && ["job", "agent-task", "agent-steps", "pages", "logs"].includes(String(query.queryKey[0]))) keys.push(query.queryKey);
    }
  }
  return keys;
}

const pendingInvalidations = new WeakMap<QueryClient, Map<string, Promise<void>>>();
export function invalidateFresh(client: QueryClient, queryKey: QueryKey) {
  let pending = pendingInvalidations.get(client);
  if (!pending) {pending = new Map(); pendingInvalidations.set(client, pending);}
  const key = JSON.stringify(queryKey);
  const current = pending.get(key);
  if (current) return current;
  const fetching = client.getQueryCache().findAll({queryKey}).some(query => query.state.fetchStatus === "fetching");
  const promise = (async () => {
    await client.invalidateQueries({queryKey}, {cancelRefetch: false});
    if (fetching) await client.invalidateQueries({queryKey}, {cancelRefetch: false});
  })().finally(() => pending!.delete(key));
  pending.set(key, promise);
  return promise;
}
