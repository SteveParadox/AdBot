import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { queryApi, api } from "./api";
import { Button, Field } from "./ui";
type Profile={id:string;name:string;value:string;description:string;category:string;enabled:boolean;created_at:number;updated_at:number;clients?:string[]};
type Policy={weights?:Record<string,number>;fallback?:string;enabled?:boolean;updated_at?:number;value?:string|null;profile?:string|null;rotation?:string;profiles?:string[];interval_seconds?:number};
type Config={revision:number;global_value:string|null;profiles:Profile[];services:Record<string,Policy>;default:string;max_length:number;fixed:Record<string,string>;registered_services:string[];rotatable_services:string[];updated_at:number|null};
function CsvInput({values,onChange}:{values:string[];onChange:(values:string[])=>void}){
 const serialized=values.join(",");const [text,setText]=useState(serialized);
 useEffect(()=>setText(serialized),[serialized]);
 return <input value={text} onChange={e=>{setText(e.target.value);onChange(e.target.value.split(",").map(v=>v.trim()).filter(Boolean));}}/>;
}
export function UserAgentAdmin({token}:{token:string}) {
 const query=useQuery({queryKey:["user-agents",token],queryFn:({signal}) =>queryApi<Config>("/admin/user-agents",token, signal),refetchInterval:false,refetchOnWindowFocus:false,staleTime:Infinity,retry:false});
 const [draft,setDraft]=useState<Config|null>(null); const [error,setError]=useState(""); const [notice,setNotice]=useState(""); const [busy,setBusy]=useState(false);
 const [weightText,setWeightText]=useState<Record<string,string>>({});
 useEffect(()=>{if(query.data){setDraft(structuredClone(query.data));setWeightText({});}},[query.data]);
 const profile=(id:string,change:Partial<Profile>)=>setDraft(d=>d?{...d,profiles:d.profiles.map(p=>p.id===id?{...p,...change}:p)}:d);
 const service=(name:string,change:Partial<Policy>)=>setDraft(d=>d?{...d,services:{...d.services,[name]:{...(d.services[name]||{}),...change}}}:d);
 async function save(){if(!draft)return;setBusy(true);setError("");setNotice("");try{const services={...draft.services};for(const [name,text] of Object.entries(weightText)){const weights:unknown=JSON.parse(text);if(!weights||typeof weights!=="object"||Array.isArray(weights)||Object.values(weights).some(v=>typeof v!=="number"||!Number.isFinite(v)||v<=0||v>1000))throw new Error("Weights must be a JSON object with positive numbers up to 1000");services[name]={...services[name],weights:weights as Record<string,number>};}await api("/admin/user-agents",token,"POST",{revision:draft.revision,global_value:draft.global_value,profiles:draft.profiles,services});await query.refetch();setNotice("User-Agent configuration saved");}catch(e){setError((e as Error).message);}finally{setBusy(false);}}
 if(query.isPending)return <p role="status">Loading User-Agent settings...</p>;
 if(query.error)return <p role="alert">{query.error.message}</p>;
 if(!draft)return null;
 return <section className="panel admin-surface identity-admin"><div className="admin-intro"><span className="admin-kicker">NETWORK IDENTITY</span><h2>User-Agent management</h2><p>Manage the identities your approved integrations use.</p></div>
 <p>One identity per logical request or browser context. Committed revisions reach new sessions through the revision watcher and periodic refresh. Rotation requires operator permission.</p>
 <Field label="Global User-Agent"><input maxLength={draft.max_length} value={draft.global_value??""} placeholder={draft.default} onChange={e=>setDraft({...draft,global_value:e.target.value||null})}/></Field>
 <p className="identity-preview">Global preview: <code>{draft.global_value||draft.default}</code></p><Button onClick={()=>setDraft({...draft,global_value:null})}>Restore global default</Button>
 <p>{draft.profiles.length} profiles; revision {draft.revision}; last update {draft.updated_at?new Date(draft.updated_at*1000).toLocaleString():"Not saved"}</p>
 <div className="identity-section-heading"><h3>Reusable profiles</h3><span>{draft.profiles.length} profiles</span></div><div className="identity-card-grid">{draft.profiles.map(p=><fieldset className="identity-card" key={p.id}><legend>{p.name}</legend><span className="identity-profile-id">{p.id==="app-default"?"Protected default":p.id}</span>
 <Field label="Profile name"><input value={p.name} onChange={e=>profile(p.id,{name:e.target.value})}/></Field>
 <Field label="Profile User-Agent"><input maxLength={draft.max_length} disabled={p.id==="app-default"} value={p.value} onChange={e=>profile(p.id,{value:e.target.value})}/></Field>
 <Field label="Compatible clients (comma separated)"><CsvInput values={p.clients||["chromium","firefox","webkit","httpx"]} onChange={clients=>profile(p.id,{clients})}/></Field>
 <Field label="Profile description"><input value={p.description} onChange={e=>profile(p.id,{description:e.target.value})}/></Field>
 <Field label="Usage category"><input value={p.category} onChange={e=>profile(p.id,{category:e.target.value})}/></Field>
 <label><input type="checkbox" disabled={p.id==="app-default"} checked={p.enabled} onChange={e=>profile(p.id,{enabled:e.target.checked})}/>Enabled</label>
 <p>Assigned: {Object.entries(draft.services).filter(([,s])=>s.profile===p.id||s.profiles?.includes(p.id)).map(([n])=>n).join(", ")||"Unused"}</p>
 <Button onClick={()=>setDraft({...draft,profiles:[...draft.profiles,{...p,id:crypto.randomUUID(),name:p.name+" copy",created_at:0,updated_at:0}]})}>Duplicate profile</Button>
 <Button disabled={p.id==="app-default"||Object.values(draft.services).some(s=>s.profile===p.id||s.profiles?.includes(p.id))} onClick={()=>setDraft({...draft,profiles:draft.profiles.filter(x=>x.id!==p.id)})}>Delete profile</Button>
 </fieldset>)}</div>
 <Button onClick={()=>setDraft({...draft,profiles:[...draft.profiles,{id:crypto.randomUUID(),name:"New profile",value:draft.default,description:"",category:"custom",enabled:true,created_at:0,updated_at:0}]})}>Create profile</Button>
 <div className="identity-section-heading"><h3>Service policies</h3><span>Override the global identity per integration</span></div><div className="identity-card-grid">{draft.registered_services.map(name=>{const s=draft.services[name]||{};const fixed=draft.fixed[name];return <fieldset className="identity-card service-policy-card" key={name}><legend>{name}{fixed?" (operator fixed)":""}</legend>
 <label><input type="checkbox" disabled={!!fixed} checked={s.enabled!==false} onChange={e=>service(name,{enabled:e.target.checked})}/>Enable {name} override</label>
 <Field label={name+" custom User-Agent"}><input disabled={!!fixed} value={s.value??""} onChange={e=>service(name,{value:e.target.value||null})}/></Field>
 <Field label={name+" profile"}><select disabled={!!fixed} value={s.profile??""} onChange={e=>service(name,{profile:e.target.value||null})}><option value="">Use global</option>{draft.profiles.map(p=><option key={p.id} value={p.id}>{p.name}{p.enabled?"":" (disabled: uses fallback)"}</option>)}</select></Field>
 <Field label={name+" rotation"}><select disabled={!!fixed||name!=="browser"||!draft.rotatable_services.includes(name)} value={s.rotation||"none"} onChange={e=>service(name,{rotation:e.target.value,value:null,profile:null})}>{["none","manual","round_robin","random","weighted","sticky","compatibility","scheduled","proxy_endpoint"].map(r=><option key={r}>{r}</option>)}</select></Field>
 {s.rotation&&s.rotation!=="none"&&s.rotation!=="manual"&&<><Field label="Rotation profile IDs (comma separated)"><CsvInput values={s.profiles||[]} onChange={profiles=>service(name,{profiles})}/></Field><Field label="Profile weights JSON"><input value={weightText[name]??JSON.stringify(s.weights||{})} onChange={e=>setWeightText({...weightText,[name]:e.target.value})}/></Field><Field label="Rotation interval seconds"><input type="number" min={30} value={s.interval_seconds||300} onChange={e=>service(name,{interval_seconds:+e.target.value})}/></Field></>}
 <Field label={name+" incompatible profile fallback"}><select disabled={!!fixed} value={s.fallback||"global"} onChange={e=>service(name,{fallback:e.target.value})}><option value="global">Global/default</option><option value="fail">Fail closed</option></select></Field>
 <p className="identity-preview">Preview: <code>{fixed||(s.enabled===false?(draft.global_value||draft.default):s.value)||draft.profiles.find(p=>p.id===s.profile&&p.enabled)?.value||draft.global_value||draft.default}</code>{s.rotation&&s.rotation!=="none"&&s.rotation!=="manual"?" (rotates at new context boundaries)":""}</p>
 </fieldset>})}</div>
 <div className="identity-save-bar"><Button disabled={busy} onClick={()=>void save()}>Save User-Agent settings</Button><Button disabled={busy} onClick={()=>void query.refetch()}>Reload saved settings</Button><span>Revision {draft.revision} | Changes apply to new sessions</span></div>
 {error&&<p role="alert">{error}</p>}{notice&&<p role="status">{notice}</p>}
 </section>;
}
