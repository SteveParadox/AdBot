import { useEffect, useRef } from "react";
import { parseEvents, type Event } from "./api";

// Pause connections with the tab, preserve the cursor, and back off on failures.
export function useEventStream(path: string, token: string, enabled: boolean,
  onEvents: (events: Event[]) => void) {
  const callback = useRef(onEvents);
  callback.current = onEvents;
  useEffect(() => enabled && token ? startEventStream(path, token, events => callback.current(events)) : undefined,
    [path, token, enabled]);
}

export function startEventStream(path: string, token: string, onEvents: (events: Event[]) => void) {
  let stopped = false, cursor: number | undefined, timer: ReturnType<typeof setTimeout>;
  let controller: AbortController | undefined;
  let delay = 1500, generation = 0;
  async function connect() {
    if (stopped || document.hidden) return;
    const current = ++generation;
    controller = new AbortController();
    try {
      const response = await fetch("/api" + path, {
        headers: { Authorization: "Bearer " + token,
          ...(cursor === undefined ? {} : { "Last-Event-ID": String(cursor) }) },
        signal: controller.signal,
      });
      if ([401, 403, 404].includes(response.status)) return;
      if (response.status === 429) {
        const retry = response.headers.get("Retry-After");
        const wait = retry && /^\d+$/.test(retry) ? Number(retry) * 1000 : retry ? Date.parse(retry) - Date.now() : 60000;
        delay = Number.isFinite(wait) ? Math.max(1500, wait) : 60000;
      }
      if (!response.ok || !response.body) throw new Error("Stream unavailable");
      delay = 1500;
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      while (!stopped) {
        const chunk = await reader.read();
        if (chunk.done || current !== generation || stopped) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        const parsed = parseEvents(buffer);
        buffer = parsed.remaining;
        if (parsed.events.length) {
          cursor = parsed.events.at(-1)!.id;
          onEvents(parsed.events);
        }
      }
    } catch { /* Retry transient disconnects with the last received cursor. */ }
    if (!stopped && current === generation && !document.hidden) {
      timer = setTimeout(() => void connect(), delay);
      delay = Math.min(delay * 2, 60000);
    }
  }
  function visibility() {
    ++generation;
    clearTimeout(timer);
    controller?.abort();
    if (!document.hidden) void connect();
  }
  document.addEventListener("visibilitychange", visibility);
  void connect();
  return () => {
    stopped = true;
    ++generation;
    clearTimeout(timer);
    controller?.abort();
    document.removeEventListener("visibilitychange", visibility);
  };
}
