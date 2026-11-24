import { QueryObserver } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createQueryClient, mutationKeys, invalidateFresh } from "./queryClient";
import { mergeEvents } from "./useJobEvents";
import { startEventStream } from "./useEventStream";
import type { Event } from "./api";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("keeps static resources and terminal details off timers, independently refreshes metrics", () => {
  const client = createQueryClient();
  for (const key of ["agent-task", "agent-steps", "websites", "workflows", "agent-config", "agent-memories", "extraction", "content"]) {
    const options = client.defaultQueryOptions({queryKey:[key]});
    expect(options.refetchInterval).toBe(false);
    expect(options.staleTime).toBe(Infinity);
    expect(options.refetchIntervalInBackground).toBe(false);
  }
  expect(client.defaultQueryOptions({queryKey:["agent-metrics"]}).refetchInterval).toBe(15000);
  expect(client.defaultQueryOptions({queryKey:["overview"]}).refetchInterval).toBe(60000);
  expect(client.defaultQueryOptions({queryKey:["jobs"]}).refetchInterval).toBe(30000);
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
  expect(mutationKeys("/agent/tasks/preview")).toEqual([]);
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
