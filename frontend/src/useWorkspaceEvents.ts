import { holdInitialQueries } from "./queryBarrier";
import { useEffect } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { onApiMutation } from "./api";
import { invalidateFresh, mutationKeys, setRealtimeState } from "./queryClient";
import { subscribeEventStream } from "./useEventStream";
import { createWorkspaceEventHandler } from "./workspaceEvents";

export function useWorkspaceEvents(token: string) {
  const client = useQueryClient();
  useEffect(() => {
    if (!token) return;
    const handler = createWorkspaceEventHandler(client, token);
    const barrier = holdInitialQueries(token);
    let opened = false, initialGap = false;
    let disposed = false, channel: BroadcastChannel | undefined;
    // Coordinate modification notices only. No credentials or resource contents cross tabs.
    if (typeof BroadcastChannel !== "undefined" && crypto.subtle) void crypto.subtle.digest("SHA-256", new TextEncoder().encode(token)).then(hash => {
      if (disposed) return;
      channel = new BroadcastChannel("adbot-changes-" + Array.from(new Uint8Array(hash), byte => byte.toString(16).padStart(2, "0")).join(""));
      channel.onmessage = event => {
        if (typeof event.data?.path === "string" && event.data.path.length < 240) {
          if (typeof event.data.requestId === "string") handler.acknowledge(event.data.requestId);
          for (const key of mutationKeys(event.data.path, token, client)) void invalidateFresh(client, key);
        }
      };
    });
    const unsubscribeMutations = onApiMutation(async (path, ownerToken, requestId) => {
      if (ownerToken !== token || disposed) return;
      if (requestId) handler.acknowledge(requestId);
      channel?.postMessage({path, requestId});
      await Promise.all(mutationKeys(path, token, client).map(key => invalidateFresh(client, key)));
    });
    const unsubscribeStream = subscribeEventStream("/events", token, events => {
      handler.receive(events.map(event => {
        if (initialGap && event.event_type === "sync") {
          initialGap = false;
          return {...event, details: {...event.details, reconcile: true, snapshot_gap: true}};
        }
        return event;
      }));
    }, state => {
      if (state === "open") {opened = true; barrier.release();}
      if (state === "backoff" || state === "exhausted") {if (!opened) initialGap = true; barrier.release();}
      setRealtimeState(client, state);
      if (state === "unauthorized") window.dispatchEvent(new CustomEvent("adbot:auth-expired"));
    });
    return () => {disposed = true; barrier.dispose(); handler.dispose(); channel?.close(); unsubscribeMutations(); unsubscribeStream();};
  }, [client, token]);
}
