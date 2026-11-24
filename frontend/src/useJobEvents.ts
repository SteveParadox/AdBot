import { useQuery, useQueryClient } from "@tanstack/react-query";
import { queryApi, type Collection, type Event } from "./api";
import { mergeEvents } from "./workspaceEvents";
export { mergeEvents } from "./workspaceEvents";

// Detail views consume the session stream's Query cache, never a second socket.
export function useJobEvents(id: string, token: string, _status: string | undefined, _keys: string[], limit: number) {
  const client = useQueryClient();
  const history = useQuery({queryKey: ["logs", id, token], queryFn: async ({signal}) => {
    const data = await queryApi<Collection<Event>>(`/jobs/${id}/logs?limit=200&tail=true`, token, signal);
    const existing = client.getQueryData<Collection<Event>>(["logs", id, token]);
    return {...data, items: mergeEvents(data.items, existing?.items || [], 200)};
  }});
  return (history.data?.items || []).slice(-limit);
}
