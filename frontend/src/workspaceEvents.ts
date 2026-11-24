import { type QueryClient, type QueryKey } from "@tanstack/react-query";
import { discardSessionReads, type Collection, type Event, type Job } from "./api";
import { invalidateFresh, mutationKeys } from "./queryClient";
import { count, gauge, highWater } from "./traffic";

export function mergeEvents(previous: Event[], incoming: Event[], limit: number) {
  return [...new Map([...previous, ...incoming].map(event => [event.id, event])).values()]
    .sort((a, b) => a.id - b.id).slice(-limit);
}
const terminal = (status: string) => ["completed", "failed", "cancelled"].includes(status);
type Identified = {id: number; number: number; [key: string]: unknown};

export function createWorkspaceEventHandler(client: QueryClient, token: string) {
  const dirty = new Map<string, QueryKey>();
  const versions = new Map<string, number>();
  const acknowledged = new Set<string>();
  let timer: ReturnType<typeof setTimeout> | undefined, disposed = false, generation = 0, overflowed = false;
  function enqueue(key: QueryKey) {
    const id = JSON.stringify(key);
    if (dirty.size >= 256 && !dirty.has(id)) overflowed = true;
    else dirty.set(id, key);
    gauge("event_queue_depth", dirty.size); highWater("event_queue_peak_depth", dirty.size);
    if (!timer) timer = setTimeout(flush, 1000);
  }
  function flush() {
    clearTimeout(timer); timer = undefined;
    if (disposed) return;
    if (overflowed) {
      count("event_queue_overflows");
      // Overload recovery is deliberately broader than normal event processing.
      void client.invalidateQueries({predicate: query => query.queryKey.includes(token)}, {cancelRefetch: false});
    } else for (const key of dirty.values()) void invalidateFresh(client, key);
    dirty.clear(); gauge("event_queue_depth", 0); overflowed = false;
  }
  async function patch(key: QueryKey, id: number, update: (old: unknown) => unknown, ordered = true) {
    const epoch = generation;
    const query = client.getQueryCache().find({queryKey: key, exact: true});
    if (!query) return;
    // Preserve initial history/pages. Later snapshots are cancelled before patches.
    if (query.state.fetchStatus === "fetching") {
      if (query.state.data === undefined) await query.promise?.catch(() => undefined);
      else await client.cancelQueries({queryKey: key, exact: true}, {revert: false});
    }
    const versionKey = JSON.stringify(key);
    if (disposed || epoch !== generation || (ordered && id < (versions.get(versionKey) || 0))) return;
    if (ordered) versions.set(versionKey, id);
    // Version entries only correspond to the bounded Query cache, never every event.
    if (versions.size > 500) versions.delete(versions.keys().next().value!);
    client.setQueryData(key, update);
  }
  function patchCollections(family: string, event: Event, value: Record<string, unknown>) {
    for (const query of client.getQueryCache().findAll({queryKey: [family, token]})) {
      const data = query.state.data as Collection<Record<string, unknown>> | undefined;
      if (!data?.items.some(item => item.id === value.id)) {
        // Status-filtered pages may gain an existing job. Reconcile their membership.
        if (family === "jobs" && query.queryKey[3] && query.queryKey[3] === value.status) enqueue(query.queryKey);
        continue;
      }
      void patch(query.queryKey, event.id, old => {
        const collection = old as Collection<Record<string, unknown>>;
        const filter = family === "jobs" ? query.queryKey[3] : undefined;
        const items = collection.items.map(item => item.id === value.id ? {...item, ...value} : item);
        const filtered = filter ? items.filter(item => item.status === filter) : items;
        return {...collection, items: filtered, total: collection.total - (items.length - filtered.length)};
      });
    }
  }
  function resource(event: Event) {
    const data = event.resource;
    const jobType = data?.job?.job_type || event.details.job_type;
    const datasetId = data?.dataset_id || (typeof event.details.dataset_id === "string" ? event.details.dataset_id : undefined);
    const id = event.job_id;
    if (!id) return;
    // Log appends wait for a pending initial snapshot and merge by durable ID.
    void patch(["logs", id, token], event.id, old => {
      const previous = old as Collection<Event> | undefined;
      const items = mergeEvents(previous?.items || [], [event], 200);
      return {items, total: Math.max(previous?.total || 0, items.length)};
    }, false);
    if (data?.job) {
      void patch(["job", id, token], event.id, old => old ? {...old, ...data.job} : old);
      patchCollections("jobs", event, data.job);
      patchCollections("recent-jobs", event, data.job);
      if (data.task) {
        void patch(["agent-task", id, token], event.id, old => old ? {...old, ...data.task} : old);
        patchCollections("agent-tasks", event, data.task);
      }
      if (data.steps?.length) void patch(["agent-steps", id, token], event.id, old => {
        const previous = old as Collection<Identified> | undefined;
        if (!previous) return old;
        const merged = [...new Map([...previous.items, ...data.steps!].map(step => [step.id, step])).values()].sort((a, b) => a.number - b.number);
        // The detail currently displays offset zero / limit 100. Do not shift its page.
        return {...previous, items: merged.slice(0, 100), total: Math.max(previous.total, ...merged.map(step => step.number))};
      });
    } else if (!event.snapshot_batch) {
      // Old servers and payload-size fallbacks still work with narrowly scoped reads.
      if (["started", "paused", "running", "waiting_user", "completed", "failed", "cancelled", "review_requested", "review_answered", "recovered", "pause_requested", "resume_requested", "dependency_failed"].includes(event.event_type)) {
        enqueue(["job", id, token]); enqueue(["agent-task", id, token]);
      }
      if (event.event_type.startsWith("agent_") || event.event_type.startsWith("review_")) {
        enqueue(["agent-steps", id, token]); enqueue(["agent-task", id, token]);
      }
      if (terminal(event.event_type)) {
        enqueue(["jobs", token]); enqueue(["recent-jobs", token]); enqueue(["agent-tasks", token]);
      }
    }
    if (["queued", "agent_queued"].includes(event.event_type)) {
      enqueue(["jobs", token]); enqueue(["recent-jobs", token]);
      if (data?.job?.job_type === "agent" || event.event_type === "agent_queued") enqueue(["agent-tasks", token]);
    }
    if (event.event_type === "navigation_completed" || event.event_type === "navigation_failure") enqueue(["pages", id]);
    if (!datasetId && !event.snapshot_batch && (event.event_type === "records_extracted" || terminal(event.event_type))) {
      // Legacy servers cannot identify the dataset; reconcile only mounted results.
      for (const query of client.getQueryCache().findAll({queryKey: ["extraction", token]}))
        if (query.isActive() && ["records", "changes", "runs", "exports"].includes(String(query.queryKey[2]))) enqueue(query.queryKey);
      if (event.event_type === "records_extracted") enqueue(["extraction", token, "datasets"]);
    }
    if (datasetId && (event.event_type === "records_extracted" || terminal(event.event_type))) {
      const dataset = datasetId;
      const kinds = jobType === "export" ? ["exports"] : ["records", "changes", "runs"];
      for (const kind of kinds) enqueue(["extraction", token, kind, dataset]);
      if (event.event_type === "records_extracted") enqueue(["extraction", token, "datasets"]);
    }
    if (event.event_type === "completed" && jobType === "agent") enqueue(["agent-memories", token]);
    if (terminal(event.event_type) || event.event_type === "review_requested") flush();
  }
  return {
    acknowledge(requestId: string) {
      if (!/^[a-f0-9]{32}$/.test(requestId)) return;
      acknowledged.add(requestId);
      if (acknowledged.size > 512) acknowledged.delete(acknowledged.values().next().value!);
    },
    receive(events: Event[]) {
      if (disposed) return;
      const started = performance.now();
      count("event_batches");
      for (const event of events) {
        if (event.event_type === "resources_changed") {
          const changes = event.details.changes as {path: string; request_id?: string}[] | undefined;
          const paths = changes ? changes.filter(change => !change.request_id || !acknowledged.has(change.request_id)).map(change => change.path) : event.details.paths as string[] || [];
          for (const path of paths) for (const key of mutationKeys(path, token, client)) enqueue(key);
        } else if (event.event_type === "sync") {
          if (event.details.reconcile) {
            if (event.details.reset) {
              generation++; versions.clear(); acknowledged.clear();
              discardSessionReads(token);
              void client.cancelQueries({predicate: query => query.queryKey.includes(token)});
              for (const query of client.getQueryCache().findAll({queryKey: ["logs"]})) if (query.queryKey.includes(token)) client.setQueryData(query.queryKey, {items: [], total: 0});
            }
            // Reconcile active execution state after a genuine reconnect, not every heartbeat.
            for (const query of client.getQueryCache().getAll()) {
              if ((!event.details.reset && !query.isActive()) || (!query.queryKey.includes(token) && query.queryKey[0] !== "content")) continue;
              const family = String(query.queryKey[0]);
              if (event.details.reset || event.details.snapshot_gap || ["jobs", "recent-jobs", "agent-tasks", "job", "agent-task", "agent-steps", "logs", "pages", "extraction"].includes(family)) enqueue(query.queryKey);
            }
            flush();
          }
        } else resource(event);
      }
      count("event_processing_ms_total", performance.now() - started);
    },
    dispose() {disposed = true; clearTimeout(timer); dirty.clear(); gauge("event_queue_depth", 0); versions.clear(); acknowledged.clear();},
  };
}
