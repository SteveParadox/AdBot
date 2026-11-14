import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
export function NetworkStatus({token}: {token:string}) {
  const status = useQuery({queryKey:["network-status",token],queryFn:()=>api("/admin/network",token),refetchInterval:30000,retry:false});
  return <section className="panel"><h2>Network routing</h2>
    <p>Identifiers and health counters only. Configuration and credentials are managed on the server.</p>
    {status.isPending ? <p role="status">Loading network status...</p> : status.error ? <p role="alert">{status.error.message}</p> : <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify(status.data,null,2)}</pre>}
  </section>;
}
