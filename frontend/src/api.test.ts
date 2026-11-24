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
