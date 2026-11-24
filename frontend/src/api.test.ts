import { describe, expect, it, vi } from "vitest";
import { api, onApiMutation, parseEvents } from "./api";

describe("SSE reconnect input", () => {
  it("buffers incomplete events across network chunks", () => {
    const first = parseEvents(
      'id: 12\nevent: progress\ndata: {"id":12,"message":"hello"}',
    );
    expect(first.events).toHaveLength(0);
    const next = parseEvents(
      first.remaining + '\n\n: heartbeat\n\nid: 13\ndata: {"id":13}\n\n',
    );
    expect(next.events.map((e) => e.id)).toEqual([12, 13]);
    expect(next.remaining).toBe("");
  });
  it("handles CRLF line endings", () => {
    expect(parseEvents('id: 1\r\ndata: {"id":1}\r\n\r\n').events[0].id).toBe(1);
  });
});


it("preserves conflict status for the editor without losing the server message",async()=>{
  const original=globalThis.fetch;
  globalThis.fetch=async()=>new Response(JSON.stringify({detail:"Section changed"}),{status:409,headers:{"Content-Type":"application/json"}});
  try { await expect(api("/admin/content/test","test-key","POST",{})).rejects.toMatchObject({name:"ApiError",status:409,message:"Section changed"}); }
  finally {globalThis.fetch=original;}
});

it("honors Retry-After across endpoints and resumes when the cooldown expires",async()=>{
 const original=globalThis.fetch;vi.useFakeTimers();
 const fetch=vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({detail:"Rate limit exceeded"}),{status:429,headers:{"Retry-After":"60"}})).mockResolvedValue(new Response(JSON.stringify({ok:true}),{status:200}));
 globalThis.fetch=fetch;
 try{
  await expect(api("/websites","cooldown-test-key")).rejects.toMatchObject({status:429});
  await expect(api("/workflows","cooldown-test-key")).rejects.toMatchObject({status:429});
  expect(fetch).toHaveBeenCalledTimes(1);
  vi.advanceTimersByTime(60001);
  await expect(api("/workflows","cooldown-test-key")).resolves.toEqual({ok:true});
  expect(fetch).toHaveBeenCalledTimes(2);
 }finally{globalThis.fetch=original;vi.useRealTimers();}
});


it("deduplicates concurrent reads but isolates credentials, headers and mutations", async () => {
  const original = globalThis.fetch;
  const fetch = vi.fn(async () => new Response(JSON.stringify({ok:true})));
  globalThis.fetch = fetch;
  try {
    const first = api("/dedup", "owner-a");
    const second = api("/dedup", "owner-a");
    expect(first).toBe(second);
    await Promise.all([first, second, api("/dedup", "owner-b"), api("/dedup", "owner-a", "GET", undefined, {"X-Test":"different"})]);
    expect(fetch).toHaveBeenCalledTimes(3);
    await api("/dedup", "owner-a");
    expect(fetch).toHaveBeenCalledTimes(4);
    await Promise.all([api("/dedup", "owner-a", "POST", {}), api("/dedup", "owner-a", "POST", {})]);
    expect(fetch).toHaveBeenCalledTimes(6);
  } finally { globalThis.fetch = original; }
});

it("releases failed reads so retries can recover", async () => {
  const original = globalThis.fetch;
  const fetch = vi.fn().mockRejectedValueOnce(new Error("offline"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ok:true})));
  globalThis.fetch = fetch;
  try {
    const first = api("/retry-dedup", "owner-a");
    const second = api("/retry-dedup", "owner-a");
    await expect(first).rejects.toThrow("offline");
    await expect(second).rejects.toThrow("offline");
    await expect(api("/retry-dedup", "owner-a")).resolves.toEqual({ok:true});
    expect(fetch).toHaveBeenCalledTimes(2);
  } finally { globalThis.fetch = original; }
});


it("notifies cache listeners only after successful mutations", async () => {
  const original = globalThis.fetch;
  const listener = vi.fn(async () => undefined);
  const unsubscribe = onApiMutation(listener);
  globalThis.fetch = vi.fn().mockResolvedValueOnce(new Response("{}"))
    .mockResolvedValueOnce(new Response("{}", {status:500}))
    .mockResolvedValueOnce(new Response("{}"));
  try {
    await api("/workflows", "mutation-owner", "POST", {});
    expect(listener).toHaveBeenCalledWith("/workflows", "mutation-owner");
    await expect(api("/workflows", "mutation-owner", "POST", {})).rejects.toThrow();
    await api("/workflows", "mutation-owner");
    expect(listener).toHaveBeenCalledTimes(1);
  } finally { unsubscribe(); globalThis.fetch = original; }
});


it("cancels only the obsolete consumer, then aborts transport after its last consumer leaves", async () => {
  vi.useFakeTimers();
  const original = globalThis.fetch;
  let transport!: AbortSignal;
  globalThis.fetch = vi.fn((_url, options) => {
    transport = options!.signal!;
    return new Promise<Response>((_resolve, reject) => transport.addEventListener("abort", () => reject(new DOMException("cancelled", "AbortError"))));
  });
  const first = new AbortController(), second = new AbortController();
  try {
    const one = api("/shared-cancel", "owner", "GET", undefined, undefined, first.signal);
    const two = api("/shared-cancel", "owner", "GET", undefined, undefined, second.signal);
    first.abort(); await expect(one).rejects.toHaveProperty("name", "AbortError");
    await vi.advanceTimersByTimeAsync(20); expect(transport.aborted).toBe(false);
    const rejected = expect(two).rejects.toHaveProperty("name", "AbortError");
    second.abort(); await rejected;
    await vi.advanceTimersByTimeAsync(20); expect(transport.aborted).toBe(true);
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);
  } finally {globalThis.fetch = original; vi.useRealTimers();}
});

it("does not issue an already-aborted request and keeps query parameters isolated", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = vi.fn(async () => new Response("{}"));
  try {
    const controller = new AbortController(); controller.abort();
    await expect(api("/items?offset=0", "owner", "GET", undefined, undefined, controller.signal)).rejects.toHaveProperty("name", "AbortError");
    await Promise.all([api("/items?offset=0", "owner"), api("/items?offset=25", "owner")]);
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  } finally {globalThis.fetch = original;}
});

it("parses SSE data lines with optional spacing and rejects oversized frames", () => {
  expect(parseEvents('data:{"id":1,\ndata: "message":"ok"}\n\n').events[0].message).toBe("ok");
  expect(() => parseEvents("x".repeat(2_000_001))).toThrow("capacity");
  expect(() => parseEvents('data: {"id":-1}\n\n')).toThrow("cursor");
});
