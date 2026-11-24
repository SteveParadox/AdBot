import { QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, mutationKeys, invalidateFresh, setRealtimeState } from "./queryClient";
import { mergeEvents } from "./useJobEvents";
import { startEventStream, subscribeEventStream } from "./useEventStream";
import type { Event } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.useRealTimers(); });

it("keeps static resources and terminal details off timers, independently refreshes metrics", () => {
  const client = createQueryClient();
  for (const key of ["agent-task", "agent-steps", "websites", "workflows", "agent-config", "agent-memories", "extraction", "content"]) {
    const options = client.defaultQueryOptions({queryKey:[key]});
    const interval = options.refetchInterval;
    const query = client.getQueryCache().build(client, {queryKey:[key]});
    expect(typeof interval === "function" ? interval(query) : interval).toBe(false);
    expect(options.staleTime).toBe(Infinity);
    expect(options.refetchIntervalInBackground).toBe(false);
  }
  const metric = client.defaultQueryOptions({queryKey:["agent-metrics"]});
  const overview = client.defaultQueryOptions({queryKey:["overview"]});
  expect((metric.refetchInterval as Function)()).toBe(15000);
  expect((overview.refetchInterval as Function)()).toBe(60000);
  client.clear();
});

it("merges replayed events once, in order, retaining the latest entries", () => {
  const event = (id: number, message = "") => ({id, message} as Event);
  expect(mergeEvents([event(1),event(3)], [event(3,"updated"),event(2),event(4)], 3))
    .toEqual([event(2),event(3,"updated"),event(4)]);
});

describe("event stream lifecycle", () => {
  function setup() {
    vi.useFakeTimers();
    const doc = Object.assign(new EventTarget(), {hidden:false});
    vi.stubGlobal("document", doc);
    vi.stubGlobal("window", new EventTarget());
    vi.spyOn(Math, "random").mockReturnValue(0);
    const fetch = vi.fn<typeof globalThis.fetch>(async () => new Response('data: {"id":42}\n\n'));
    vi.stubGlobal("fetch", fetch);
    return {doc, fetch};
  }
  it("resumes with a cursor and stops reconnecting after cleanup", async () => {
    const {fetch} = setup();
    const received = vi.fn();
    const stop = startEventStream("/events", "test", received);
    await vi.advanceTimersByTimeAsync(0);
    expect(received).toHaveBeenCalledWith([{id:42}]);
    await vi.advanceTimersByTimeAsync(1500);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect((fetch.mock.calls[1][1]!.headers as Record<string, string>)["Last-Event-ID"]).toBe("42");
    stop();
    await vi.advanceTimersByTimeAsync(120000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("aborts while hidden, resumes once visible, and removes listeners on cleanup", async () => {
    const {doc,fetch} = setup();
    const stop = startEventStream("/events", "test", vi.fn());
    await vi.advanceTimersByTimeAsync(0);
    doc.hidden = true; doc.dispatchEvent(new globalThis.Event("visibilitychange"));
    expect(fetch.mock.calls[0][1]!.signal!.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(1);
    doc.hidden = false; doc.dispatchEvent(new globalThis.Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(2);
    stop();
    doc.dispatchEvent(new globalThis.Event("visibilitychange"));
    await vi.advanceTimersByTimeAsync(60000);
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it("honors rate limits and does not retry rejected credentials", async () => {
    const {fetch} = setup();
    fetch.mockResolvedValueOnce(new Response("", {status:429,headers:{"Retry-After":"60"}}))
      .mockResolvedValueOnce(new Response("", {status:401}));
    const stop = startEventStream("/events", "test", vi.fn());
    await vi.advanceTimersByTimeAsync(59999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(120000);
    expect(fetch).toHaveBeenCalledTimes(2);
    stop();
  });
});


it("invalidates affected resources after writes without refreshing configuration or unrelated task details", () => {
  expect(mutationKeys("/workflows/123")).toEqual([["workflows"]]);
  expect(mutationKeys("/agent/preview")).toEqual([]);
  expect(mutationKeys("/jobs/task-123/cancel")).toContainEqual(["agent-task", "task-123"]);
  expect(mutationKeys("/jobs/task-123/cancel")).not.toContainEqual(["agent-config"]);
  expect(mutationKeys("/admin/content/home")).toEqual([["content"], ["admin-content"]]);
});


it("reconciles an event arriving while an older snapshot is still in flight", async () => {
  const client = createQueryClient();
  let complete!: (value: string) => void;
  const queryFn = vi.fn().mockImplementationOnce(() => new Promise<string>(resolve => {complete = resolve;}))
    .mockResolvedValue("completed");
  const observer = new QueryObserver(client, {queryKey:["agent-task", "one"], queryFn});
  const unsubscribe = observer.subscribe(() => undefined);
  const refresh = invalidateFresh(client, ["agent-task", "one"]);
  complete("running");
  await refresh;
  expect(client.getQueryData(["agent-task", "one"])).toBe("completed");
  expect(queryFn).toHaveBeenCalledTimes(2);
  unsubscribe(); client.clear();
});


it("activates only execution fallback polling and stops it after recovery or terminal state", () => {
  const client = createQueryClient();
  const key = ["agent-task", "one", "owner"];
  const query = client.getQueryCache().build(client, {queryKey:key});
  const interval = client.defaultQueryOptions({queryKey:key}).refetchInterval as Function;
  expect(interval(query)).toBe(false);
  setRealtimeState(client, "backoff"); expect(interval(query)).toBe(30000);
  client.setQueryData(key, {status:"completed"}); expect(interval(query)).toBe(false);
  client.setQueryData(key, {status:"running"});
  setRealtimeState(client, "open"); expect(interval(query)).toBe(false);
  setRealtimeState(client, "unauthorized"); expect(interval(query)).toBe(false);
  client.clear();
});


describe("shared stream safeguards", () => {
  function setup() {
    vi.useFakeTimers();
    vi.stubGlobal("document", Object.assign(new EventTarget(), {hidden:false}));
    vi.stubGlobal("window", new EventTarget());
    vi.spyOn(Math,"random").mockReturnValue(0);
    const fetch = vi.fn<typeof globalThis.fetch>(async (_url, options) => new Response(new ReadableStream({
      start(controller) { options!.signal!.addEventListener("abort",()=>controller.error(new DOMException("aborted","AbortError")),{once:true}); }
    })));
    vi.stubGlobal("fetch",fetch); return fetch;
  }
  it("shares ownership and survives Strict Mode's cleanup/setup without opening another connection", async () => {
    const fetch = setup();
    const first = subscribeEventStream("/shared-test","owner",vi.fn());
    first();
    const second = subscribeEventStream("/shared-test","owner",vi.fn());
    const third = subscribeEventStream("/shared-test","owner",vi.fn());
    await vi.advanceTimersByTimeAsync(0); expect(fetch).toHaveBeenCalledTimes(1);
    second(); await vi.advanceTimersByTimeAsync(101);
    expect(fetch.mock.calls[0][1]!.signal!.aborted).toBe(false);
    third(); await vi.advanceTimersByTimeAsync(101);
    expect(fetch.mock.calls[0][1]!.signal!.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60000); expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("detects stalled reads and exposes degraded state for fallback polling", async () => {
    const fetch = setup(), state = vi.fn();
    const stop = startEventStream("/watchdog","owner",vi.fn(),state);
    await vi.advanceTimersByTimeAsync(45001);
    expect(fetch.mock.calls[0][1]!.signal!.aborted).toBe(true);
    expect(state).toHaveBeenCalledWith("backoff"); stop();
  });
  it("deduplicates replay, accepts unique out-of-order logs, and keeps its reconnect cursor monotonic", async () => {
    const fetch = setup();
    fetch.mockResolvedValue(new Response('data: {"id":5}\n\ndata: {"id":5}\n\ndata: {"id":3}\n\n'));
    const received = vi.fn();
    const stop = startEventStream("/ordered","owner",received);
    await vi.advanceTimersByTimeAsync(0);
    expect(received).toHaveBeenCalledWith([{id:5},{id:3}]);
    await vi.advanceTimersByTimeAsync(1500);
    expect((fetch.mock.calls[1][1]!.headers as Record<string,string>)["Last-Event-ID"]).toBe("5"); stop();
  });
  it("exhausts repeated failures and restarts only on explicit recovery", async () => {
    const fetch = setup(); fetch.mockRejectedValue(new Error("offline"));
    const state = vi.fn(); const stop = startEventStream("/bounded","owner",vi.fn(),state);
    await vi.advanceTimersByTimeAsync(500000);
    expect(fetch).toHaveBeenCalledTimes(9); expect(state).toHaveBeenCalledWith("exhausted");
    window.dispatchEvent(new globalThis.Event("online"));
    await vi.advanceTimersByTimeAsync(0); expect(fetch).toHaveBeenCalledTimes(10); stop();
  });
});


it("reconciles configuration when a reconnect reaches a restarted API worker", async () => {
  vi.useFakeTimers(); vi.stubGlobal("document",Object.assign(new EventTarget(),{hidden:false}));vi.stubGlobal("window",new EventTarget());
  vi.spyOn(Math,"random").mockReturnValue(0);
  const sync=(epoch:string)=>new Response(`data: ${JSON.stringify({id:0,event_type:"sync",server_epoch:epoch,details:{reconcile:false}})}\n\n`);
  const fetch=vi.fn<typeof globalThis.fetch>().mockResolvedValueOnce(sync("first")).mockResolvedValueOnce(sync("second"));
  vi.stubGlobal("fetch",fetch);const received=vi.fn();const stop=startEventStream("/epoch","owner",received);
  await vi.advanceTimersByTimeAsync(1500);
  expect(received.mock.calls[1][0][0].details).toMatchObject({reconcile:true,snapshot_gap:true});stop();
});
