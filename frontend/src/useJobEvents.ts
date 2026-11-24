import { invalidateFresh } from "./queryClient";
import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Collection, type Event } from "./api";
import { useEventStream } from "./useEventStream";

export function mergeEvents(previous: Event[], incoming: Event[], limit: number) {
  return [...new Map([...previous, ...incoming].map(event => [event.id, event])).values()]
    .sort((a, b) => a.id - b.id).slice(-limit);
}
const terminal = (status: string) => ["completed", "failed", "cancelled"].includes(status);

export function useJobEvents(id: string, token: string, status: string | undefined, keys: string[], limit: number) {
  const client = useQueryClient();
  const [live, setLive] = useState<Event[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const history = useQuery({ queryKey: ["logs", id, token],
    queryFn: () => api<Collection<Event>>(`/jobs/${id}/logs?limit=200&tail=true`, token) });
  useEffect(() => {
    setLive([]);
    return () => { clearTimeout(timer.current); timer.current = undefined; };
  }, [id, token]);
  function refresh() {
    timer.current = undefined;
    for (const key of keys) void invalidateFresh(client, [key, id]);
  }
  useEventStream(`/jobs/${id}/events`, token, Boolean(status) && !terminal(status!), (events) => {
    setLive(old => mergeEvents(old, events, limit));
    client.setQueryData<Collection<Event>>(["logs", id, token], old => {
      const items = mergeEvents(old?.items || [], events, 200);
      return {items, total: Math.max(old?.total || 0, items.length)};
    });
    if (events.some(event => terminal(event.event_type) || event.event_type === "dependency_failed" || event.event_type === "review_requested")) {
      clearTimeout(timer.current);
      refresh();
    } else if (timer.current === undefined) {
      timer.current = setTimeout(refresh, 2000);
    }
  });
  return mergeEvents(history.data?.items || [], live, limit);
}
