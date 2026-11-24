import { useEffect, useRef } from "react";
import { parseEvents, type Event } from "./api";
import { count } from "./traffic";

export type StreamState = "connecting" | "open" | "backoff" | "hidden" | "unauthorized" | "exhausted" | "closed";
type Listener = (events: Event[]) => void;
const shared = new Map<string, {listeners: Set<Listener>; states: Set<(state: StreamState) => void>; state: StreamState; stop: () => void; disposal?: ReturnType<typeof setTimeout>}>();

export function subscribeEventStream(path: string, token: string, listener: Listener, stateListener?: (state: StreamState) => void) {
  const key = JSON.stringify([path, token]);
  let entry = shared.get(key);
  if (!entry) {
    entry = {listeners: new Set(), states: new Set(), state: "connecting", stop: () => undefined};
    shared.set(key, entry);
    const current = entry;
    // Delay startup until after Strict Mode's setup/cleanup/setup cycle.
    const startup = setTimeout(() => {
      current.stop = startEventStream(path, token,
        events => { for (const callback of current.listeners) callback(events); },
        state => {current.state = state; for (const callback of current.states) callback(state);});
    }, 0);
    entry.stop = () => clearTimeout(startup);
  }
  clearTimeout(entry.disposal);
  entry.listeners.add(listener);
  if (stateListener) {entry.states.add(stateListener); stateListener(entry.state);}
  return () => {
    entry!.listeners.delete(listener);
    if (stateListener) entry!.states.delete(stateListener);
    if (!entry!.listeners.size) entry!.disposal = setTimeout(() => {
      entry!.stop(); shared.delete(key);
    }, 100);
  };
}

export function useEventStream(path: string, token: string, enabled: boolean, onEvents: Listener) {
  const callback = useRef(onEvents);
  callback.current = onEvents;
  useEffect(() => enabled && token ? subscribeEventStream(path, token, events => callback.current(events)) : undefined,
    [path, token, enabled]);
}

export function startEventStream(path: string, token: string, onEvents: Listener,
  onState: (state: StreamState) => void = () => undefined) {
  let stopped = false, unauthorized = false, cursor: number | undefined, changeCursor = 0;
  const seen = new Set<number>();
  let serverEpoch: string | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined, watchdog: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined, failures = 0, generation = 0;
  function setState(state: StreamState) { onState(state); }
  async function connect() {
    if (stopped || unauthorized || document.hidden) return;
    const current = ++generation;
    controller = new AbortController();
    const connection = controller;
    const connectedAt = Date.now();
    let readWatchdog: ReturnType<typeof setTimeout> | undefined;
    function armWatchdog(milliseconds: number) {
      clearTimeout(readWatchdog);
      readWatchdog = setTimeout(() => connection.abort(), milliseconds);
      watchdog = readWatchdog;
    }
    let retryAfter = 0;
    count("stream_opens"); count("active_streams");
    setState("connecting");
    armWatchdog(15000);
    try {
      const response = await fetch("/api" + path, {
        headers: {Authorization: "Bearer " + token,
          ...(cursor === undefined ? {} : {"Last-Event-ID": String(cursor)}),
          ...(changeCursor ? {"X-Resource-Cursor": String(changeCursor)} : {})},
        signal: connection.signal,
      });
      if (current !== generation || stopped) return;
      if ([401, 403].includes(response.status)) {unauthorized = true; setState("unauthorized"); return;}
      if ([404, 422].includes(response.status)) {setState("exhausted"); return;}
      if (response.status === 429) {
        const retry = response.headers.get("Retry-After");
        const wait = retry && /^\d+$/.test(retry) ? Number(retry) * 1000 : retry ? Date.parse(retry) - Date.now() : 60000;
        retryAfter = Number.isFinite(wait) ? Math.max(1000, wait) : 60000;
      }
      if (!response.ok || !response.body) throw new Error("Stream unavailable");
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "";
      while (!stopped && current === generation) {
        armWatchdog(45000);
        const chunk = await reader.read();
        if (chunk.done || current !== generation || stopped) break;
        setState("open");
        buffer += decoder.decode(chunk.value, {stream: true});
        const parsed = parseEvents(buffer);
        buffer = parsed.remaining;
        const accepted: Event[] = [];
        for (const event of parsed.events) {
          if (event.event_type === "sync") {
            if (event.server_epoch) {
              if (serverEpoch && event.server_epoch !== serverEpoch) event.details = {...event.details, reconcile: true, snapshot_gap: true};
              serverEpoch = event.server_epoch;
            }
            if (event.details?.reset) {cursor = event.id; changeCursor = event.change_cursor || 0; seen.clear();}
            else cursor = Math.max(cursor || 0, event.id);
          } else if (event.event_type === "resources_changed") {
            if ((event.change_cursor || 0) <= changeCursor) {count("duplicate_events"); continue;}
          } else {
            if (seen.has(event.id)) {count("duplicate_events"); continue;}
            seen.add(event.id);
            if (seen.size > 2000) seen.delete(seen.values().next().value!);
            cursor = Math.max(cursor || 0, event.id);
          }
          changeCursor = Math.max(changeCursor, event.change_cursor || 0);
          accepted.push(event);
          count("events_received");
          if (event.timestamp) count("event_delivery_ms_total", Math.max(0, Date.now() - event.timestamp * 1000));
        }
        if (accepted.length) onEvents(accepted);
      }
    } catch { /* Cursor replay and bounded fallback reads recover transient failures. */ }
    finally {clearTimeout(readWatchdog); connection.abort(); count("active_streams", -1);}
    if (!stopped && current === generation && !document.hidden) {
      if (Date.now() - connectedAt > 15000) failures = 0;
      failures++;
      if (failures > 8) {setState("exhausted"); return;}
      const base = Math.min(1500 * 2 ** (failures - 1), 30000);
      const delay = Math.max(retryAfter, Math.round(base * (1 + Math.random() * 0.2)));
      setState("backoff"); count("stream_reconnects");
      timer = setTimeout(() => void connect(), delay);
    }
  }
  function resume() {
    ++generation; clearTimeout(timer); clearTimeout(watchdog); controller?.abort();
    if (document.hidden) setState("hidden");
    else {failures = 0; void connect();}
  }
  document.addEventListener("visibilitychange", resume);
  window.addEventListener("online", resume);
  window.addEventListener("adbot:refresh-stream", resume);
  if (document.hidden) setState("hidden"); else void connect();
  return () => {
    stopped = true; ++generation;
    clearTimeout(timer); clearTimeout(watchdog); controller?.abort();
    document.removeEventListener("visibilitychange", resume);
    window.removeEventListener("online", resume);
    window.removeEventListener("adbot:refresh-stream", resume);
    setState("closed");
  };
}
