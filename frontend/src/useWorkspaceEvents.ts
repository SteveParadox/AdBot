import { onApiMutation } from "./api";
import { mutationKeys, invalidateFresh } from "./queryClient";
import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useEventStream } from "./useEventStream";

export function useWorkspaceEvents(token: string) {
  const client = useQueryClient();
  useEffect(() => onApiMutation(async (path, ownerToken) => {
    if (ownerToken !== token) return;
    await Promise.all(mutationKeys(path).map(queryKey => invalidateFresh(client, queryKey)));
  }), [client, token]);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const dirty = useRef(new Set<string>());
  useEffect(() => () => { clearTimeout(timer.current); timer.current = undefined; dirty.current.clear(); }, [token]);
  useEventStream("/events", token, Boolean(token), (events) => {
    for (const event of events) {
      for (const key of ["agent-tasks", "recent-jobs", "jobs", "extraction", "agent-datasets"]) dirty.current.add(key);
      if (["completed", "failed", "cancelled", "sync"].includes(event.event_type)) dirty.current.add("agent-memories");
    }
    if (timer.current !== undefined) return;
    timer.current = setTimeout(() => {
      timer.current = undefined;
      for (const key of dirty.current) void invalidateFresh(client, [key]);
      dirty.current.clear();
    }, 2000);
  });
}
