import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
type Endpoint={id:string;status:string;successes?:number;failures?:number;latency_ms?:number|null};
type Snapshot={scope:string;instances:{instance:string;enabled:boolean;failovers:number;services:Record<string,{mode:string;strategy:string;stable:boolean}>;endpoints:Endpoint[]}[]};
export function NetworkStatus({token}: {token:string}) {
 const status=useQuery({queryKey:["network-status",token],queryFn:()=>api<Snapshot>("/admin/network",token),refetchInterval:30000,retry:false});
 return <section className="panel admin-surface network-admin"><div className="admin-intro"><span className="admin-kicker">CONNECTIVITY</span><h2>Network routing</h2><p>Live health for your approved outbound routes. Credentials stay on the server.</p></div>
 {status.isPending?<p role="status">Loading network status...</p>:status.error?<p className="admin-alert" role="alert">{status.error.message}</p>:<>
 <p className="network-scope">{status.data?.scope==="shared-heartbeats"?"Shared monitoring across instances":"Monitoring this instance"} | Refreshes every 30 seconds</p>
 {status.data?.instances.map(instance=><article className="network-instance" key={instance.instance}>
 <div className="identity-section-heading"><h3>Instance {instance.instance.slice(0,8)}</h3><span className={"automation-state "+(instance.enabled?"is-running":"is-paused")}>{instance.enabled?"Proxy routing enabled":"Direct routing"}</span></div>
 <div className="network-route-grid">{Object.entries(instance.services).map(([name,service])=><div className="network-route" key={name}><strong>{name.replace(/_/g," ")}</strong><span>{service.strategy.replace(/_/g," ")}</span><small>{service.stable?"Fixed session route":"Policy-managed route"} | {service.mode}</small></div>)}</div>
 {instance.endpoints.length?<div className="network-table-wrap"><table><thead><tr><th>Endpoint</th><th>Status</th><th>Latency</th><th>Successful</th><th>Failed</th></tr></thead><tbody>{instance.endpoints.map(e=><tr key={e.id}><td>{e.id}</td><td><span className={"automation-state "+(e.status==="open"?"is-stopped":"is-running")}>{e.status==="open"?"Circuit open":"Eligible"}</span></td><td>{e.latency_ms==null?"Awaiting measurement":`${e.latency_ms} ms`}</td><td>{e.successes||0}</td><td>{e.failures||0}</td></tr>)}</tbody></table></div>:<p className="admin-empty">No proxy endpoints configured. Outbound traffic follows the operator's direct-routing policy.</p>}
 <small className="network-footnote">{instance.failovers} failover attempts recorded</small></article>)}
 </>}
 </section>;
}
