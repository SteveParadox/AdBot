import { QueryClient, type QueryKey } from "@tanstack/react-query";
import { ApiError } from "./api";

export function createQueryClient() {
  const client = new QueryClient({ defaultOptions: { queries: {
    staleTime: Infinity,
    refetchInterval: false,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: false,
    retry: (attempt, error) => attempt < 1 && (!(error instanceof ApiError) || error.status >= 500),
  } } });
  for (const key of ["jobs", "recent-jobs", "automation", "schedules"]) {
    client.setQueryDefaults([key], { staleTime: 15000, refetchInterval: 30000 });
  }
  client.setQueryDefaults(["agent-metrics"], { staleTime: 15000, refetchInterval: 15000 });
  client.setQueryDefaults(["overview"], { staleTime: 30000, refetchInterval: 60000 });
  return client;
}

// Mutation paths map to affected cache prefixes; detail keys retain their ID.
export function mutationKeys(path: string): readonly (readonly string[])[] {
  const [root, id, action] = path.split("?")[0].split("/").filter(Boolean);
  if (root === "websites") return [["websites"], ["workflows"], ["schedules"], ["jobs"], ["recent-jobs"], ["overview"], ["extraction"], ["agent-datasets"], ["agent-tasks"]];
  if (root === "workflows") return [["workflows"]];
  if (root === "schedules") return [["schedules"], ["overview"]];
  if (root === "jobs") return [["jobs"], ["recent-jobs"], ["overview"], ["automation"], ["agent-tasks"], ["agent-metrics"], ...["job", "pages", "logs", "agent-task", "agent-steps"].map(key => [key, id])];
  if (root === "agent" && id === "tasks" && action === "preview") return [];
  if (root === "agent" && id === "tasks") return [["agent-tasks"], ["agent-metrics"], ["recent-jobs"], ["jobs"], ["overview"], ...(action ? [["agent-task", action], ["agent-steps", action]] : [])];
  if (root === "agent" && id === "memories") return [["agent-memories"]];
  if (root === "extraction") return [["extraction"], ["agent-datasets"], ["jobs"], ["recent-jobs"], ["websites"], ["schedules"]];
  if (root === "admin" && id === "content") return [["content"], ["admin-content"]];
  if (root === "admin" && id === "automation") return [["automation"], ["jobs"], ["recent-jobs"]];
  if (root === "admin" && id === "user-agents") return [["user-agents"]];
  return [];
}

export async function invalidateFresh(client: QueryClient, queryKey: QueryKey) {
  // An in-flight snapshot may predate the event/write. Join it, then fetch again
  // so deduplication cannot swallow the final status update.
  const fetching = client.getQueryCache().findAll({queryKey}).some(query => query.state.fetchStatus === "fetching");
  await client.invalidateQueries({queryKey}, {cancelRefetch:false});
  if (fetching) await client.invalidateQueries({queryKey}, {cancelRefetch:false});
}
