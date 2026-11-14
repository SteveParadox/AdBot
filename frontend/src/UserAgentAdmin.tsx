import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { Button, Field } from "./ui";
type Profile={id:string;name:string;value:string;description:string;category:string;enabled:boolean;created_at:number;updated_at:number};
type Policy={enabled?:boolean;updated_at?:number;value?:string|null;profile?:string|null;rotation?:string;profiles?:string[];interval_seconds?:number};
type Config={revision:number;global_value:string|null;profiles:Profile[];services:Record<string,Policy>;default:string;max_length:number;fixed:Record<string,string>;registered_services:string[];rotatable_services:string[];updated_at:number|null};
export function UserAgentAdmin({token}:{token:string}) {
 const query=useQuery({queryKey:["user-agents",token],queryFn:()=>api<Config>("/admin/user-agents",token),refetchInterval:false,refetchOnWindowFocus:false,staleTime:Infinity,retry:false});
 const [draft,setDraft]=useState<Config|null>(null); const [error,setError]=useState(""); const [notice,setNotice]=useState(""); const [busy,setBusy]=useState(false);
 useEffect(()=>{if(query.data)setDraft(structuredClone(query.data));},[query.data]);
 const profile=(id:string,change:Partial<Profile>)=>setDraft(d=>d?{...d,profiles:d.profiles.map(p=>p.id===id?{...p,...change}:p)}:d);
 const service=(name:string,change:Partial<Policy>)=>setDraft(d=>d?{...d,services:{...d.services,[name]:{...(d.services[name]||{}),...change}}}:d);
 async function save(){if(!draft)return;setBusy(true);setError("");setNotice("");try{await api("/admin/user-agents",token,"POST",{revision:draft.revision,global_value:draft.global_value,profiles:draft.profiles,services:draft.services});await query.refetch();setNotice("User-Agent configuration saved");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 if(query.isPending)return <p role="status">Loading User-Agent settings...</p>;
 if(query.error)return <p role="alert">{query.error.message}</p>;
 if(!draft)return null;
 return <section className="panel"><h2>User-Agent management</h2>
 <p>One identity per logical request or browser context. Updates reach new requests within five seconds. Rotation requires operator permission.</p>
 <Field label="Global User-Agent"><input maxLength={draft.max_length} value={draft.global_value??""} placeholder={draft.default} onChange={e=>setDraft({...draft,global_value:e.target.value||null})}/></Field>
 <p>Global preview: <code>{draft.global_value||draft.default}</code></p><Button onClick={()=>setDraft({...draft,global_value:null})}>Restore global default</Button>
 <p>{draft.profiles.length} profiles; revision {draft.revision}; last update {draft.updated_at?new Date(draft.updated_at*1000).toLocaleString():"Not saved"}</p>
 <h3>Profiles</h3>{draft.profiles.map(p=><fieldset key={p.id}><legend>{p.name} ({p.id})</legend>
 <Field label="Profile name"><input value={p.name} onChange={e=>profile(p.id,{name:e.target.value})}/></Field>
 <Field label="Profile User-Agent"><input maxLength={draft.max_length} disabled={p.id==="app-default"} value={p.value} onChange={e=>profile(p.id,{value:e.target.value})}/></Field>
 <Field label="Profile description"><input value={p.description} onChange={e=>profile(p.id,{description:e.target.value})}/></Field>
 <Field label="Usage category"><input value={p.category} onChange={e=>profile(p.id,{category:e.target.value})}/></Field>
 <label><input type="checkbox" disabled={p.id==="app-default"} checked={p.enabled} onChange={e=>profile(p.id,{enabled:e.target.checked})}/>Enabled</label>
 <p>Assigned: {Object.entries(draft.services).filter(([,s])=>s.profile===p.id||s.profiles?.includes(p.id)).map(([n])=>n).join(", ")||"Unused"}</p>
 <Button onClick={()=>setDraft({...draft,profiles:[...draft.profiles,{...p,id:crypto.randomUUID(),name:p.name+" copy",created_at:0,updated_at:0}]})}>Duplicate profile</Button>
 <Button disabled={p.id==="app-default"||Object.values(draft.services).some(s=>s.profile===p.id||s.profiles?.includes(p.id))} onClick={()=>setDraft({...draft,profiles:draft.profiles.filter(x=>x.id!==p.id)})}>Delete profile</Button>
 </fieldset>)}
 <Button onClick={()=>setDraft({...draft,profiles:[...draft.profiles,{id:crypto.randomUUID(),name:"New profile",value:draft.default,description:"",category:"custom",enabled:true,created_at:0,updated_at:0}]})}>Create profile</Button>
 <h3>Service overrides</h3>{draft.registered_services.map(name=>{const s=draft.services[name]||{};const fixed=draft.fixed[name];return <fieldset key={name}><legend>{name}{fixed?" (operator fixed)":""}</legend>
 <label><input type="checkbox" disabled={!!fixed} checked={s.enabled!==false} onChange={e=>service(name,{enabled:e.target.checked})}/>Enable {name} override</label>
 <Field label={name+" custom User-Agent"}><input disabled={!!fixed} value={s.value??""} onChange={e=>service(name,{value:e.target.value||null})}/></Field>
 <Field label={name+" profile"}><select disabled={!!fixed} value={s.profile??""} onChange={e=>service(name,{profile:e.target.value||null})}><option value="">Use global</option>{draft.profiles.map(p=><option key={p.id} value={p.id}>{p.name}{p.enabled?"":" (disabled: uses fallback)"}</option>)}</select></Field>
 <Field label={name+" rotation"}><select disabled={!!fixed||name!=="browser"||!draft.rotatable_services.includes(name)} value={s.rotation||"none"} onChange={e=>service(name,{rotation:e.target.value,value:null,profile:null})}>{["none","round_robin","random","scheduled","proxy_endpoint"].map(r=><option key={r}>{r}</option>)}</select></Field>
 {s.rotation&&s.rotation!=="none"&&<><Field label="Rotation profile IDs (comma separated)"><input value={(s.profiles||[]).join(",")} onChange={e=>service(name,{profiles:e.target.value.split(",").map(x=>x.trim()).filter(Boolean)})}/></Field><Field label="Rotation interval seconds"><input type="number" min={30} value={s.interval_seconds||300} onChange={e=>service(name,{interval_seconds:+e.target.value})}/></Field></>}
 <p>Preview: <code>{fixed||(s.enabled===false?(draft.global_value||draft.default):s.value)||draft.profiles.find(p=>p.id===s.profile&&p.enabled)?.value||draft.global_value||draft.default}</code>{s.rotation&&s.rotation!=="none"?" (rotates at new context boundaries)":""}</p>
 </fieldset>})}
 <Button disabled={busy} onClick={()=>void save()}>Save User-Agent settings</Button><Button disabled={busy} onClick={()=>void query.refetch()}>Reload saved settings</Button>
 {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
 </section>;
}
