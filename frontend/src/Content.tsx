import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, type Collection } from "./api";
import { UserAgentAdmin } from "./UserAgentAdmin";
import { NetworkStatus } from "./NetworkStatus";
import { Button, Field } from "./ui";
export type ContentData = { navigation_label?: string; title?: string; description?: string; image?: string; image_alt?: string; link?: string; button?: string; canonical?: string };
type Section = { revision: string; key: string; draft: ContentData; status: "draft" | "published" | "archived"; position: number };
export function useContent() {
  const query = useQuery({ queryKey: ["content"], queryFn: () => api<{items: (ContentData & {key: string})[]}>("/content", ""), staleTime: Infinity, refetchInterval: false });
  const sections = Object.fromEntries((query.data?.items || []).map(s => [s.key, s]));
  useEffect(() => {
    const seo: ContentData = sections.seo || {title: "AdBot \u00b7 Website monitoring", description: "Authorized website automation and monitoring workspace"};
    document.title = seo.title || "AdBot";
    const meta = (name: string, value: string, property = false) => {
      const attribute = property ? "property" : "name";
      let node = document.head.querySelector<HTMLMetaElement>(`meta[${attribute}="${name}"]`);
      if (!node) { node = document.createElement("meta"); node.setAttribute(attribute, name); document.head.append(node); }
      node.content = value;
    };
    meta("description", seo.description || "");
    meta("og:title", seo.title || "", true); meta("og:description", seo.description || "", true);
    meta("og:image", seo.image || "", true);
    let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (seo.canonical) {
      if (!canonical) { canonical = document.createElement("link"); canonical.rel = "canonical"; document.head.append(canonical); }
      canonical.href = seo.canonical;
    } else canonical?.remove();
  }, [query.data]);
  return { ...query, sections };
}
function safeContentURL(value?: string) {
  if (!value || /[\s\\]/.test(value)) return undefined;
  if (value.startsWith("/") && !value.startsWith("//")) return value;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? value : undefined;
  } catch { return undefined; }
}
export function ContentBlock({data}: {data: ContentData}) {
  const image = safeContentURL(data.image);
  const link = safeContentURL(data.link);
  return <section className="panel"><h2>{data.title}</h2><p>{data.description}</p>
    {image && <img src={image} alt={data.image_alt || ""} loading="lazy" style={{width:"100%", aspectRatio:"16 / 9", maxHeight:400, objectFit:"contain"}} />}
    {link && <a href={link}>{data.button || data.title || "Read more"}</a>}
  </section>;
}
export function ContentAdmin({token}: {token: string}) {
  const client = useQueryClient();
  const query = useQuery({queryKey:["admin-content",token], queryFn:()=>api<Collection<Section>>("/admin/content?limit=200",token), retry:false});
  const [revision,setRevision] = useState<string|null>(null);
  const [conflict,setConflict] = useState(false);
  const [latest,setLatest] = useState<Section|null>(null);
  const [key,setKey] = useState(""); const [draft,setDraft] = useState<ContentData>({});
  const [status,setStatus] = useState<Section["status"]>("draft"); const [position,setPosition] = useState(0);
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false); const [notice,setNotice] = useState("");
  async function save(remove=false) {
    setBusy(true); setError(""); setNotice("");
    try {
      const saved = await api<Section>("/admin/content/"+encodeURIComponent(key),token,remove?"DELETE":"POST",remove?undefined:{draft,status,position,revision},remove&&revision?{"If-Match":revision}:undefined);
      setRevision(remove?null:saved.revision); setConflict(false); setLatest(null);
      if(remove){setKey("");setDraft({});setStatus("draft");setPosition(0);}
      await client.invalidateQueries({queryKey:["content"]}); await query.refetch(); setNotice(remove?"Deleted":"Saved");
    } catch(e) {setError((e as Error).message);if(!(e instanceof ApiError) || ![409,428].includes(e.status)) return;setConflict(true);
      try { setLatest(await api<Section>("/admin/content/"+encodeURIComponent(key),token)); } catch {setLatest(null);}
    } finally {setBusy(false);}
  }
  if(query.isPending) return <p role="status">Loading content editor…</p>;
  if(query.error) return <p role="alert">{query.error.message}</p>;
  return <section className="panel content-admin admin-surface"><div className="admin-intro"><span className="admin-kicker">PUBLISHING WORKSPACE</span><h2>Website content</h2><p>Create, refine, and publish your website sections.</p></div>
    <p>Reserved keys control existing page headings and SEO. Other keys appear as ordered promotional sections on the login page. Draft saves preserve the last publication; archive hides it.</p>
    <fieldset disabled={busy}><Button onClick={()=>{setRevision(null);setConflict(false);setLatest(null);setKey("");setDraft({});setStatus("draft");setPosition(0);setError("");setNotice("");}}>New section</Button>
    <Field label="Select section"><select value="" onChange={e=>{const s=query.data?.items.find(s=>s.key===e.target.value); if(s){setRevision(s.revision);setConflict(false);setLatest(null);setKey(s.key);setDraft(s.draft);setStatus(s.status);setPosition(s.position);}}}>
      <option value="">New section / select existing</option>{query.data?.items.map(s=><option key={s.key}>{s.key}</option>)}
    </select></Field>
    <form className="content-editor-grid" onSubmit={e=>{e.preventDefault();void save();}}>
      <Field label="Section key"><input disabled={revision!==null} required pattern="[A-Za-z0-9 _-]{1,80}" value={key} onChange={e=>setKey(e.target.value)} /></Field>
      {(["navigation_label","title","description","image","image_alt","link","button","canonical"] as const).map(field=><Field label={field.replace(/_/g," ")} key={field}>{field==="description"?<textarea rows={5} aria-label={field} value={draft[field] || ""} onChange={e=>setDraft({...draft,[field]:e.target.value})}/>:<input aria-label={field} value={draft[field] || ""} onChange={e=>setDraft({...draft,[field]:e.target.value})}/>}</Field>)}
      <Field label="Status"><select value={status} onChange={e=>setStatus(e.target.value as Section["status"])}>{["draft","published","archived"].map(s=><option key={s}>{s}</option>)}</select></Field>
      <Field label="Order"><input type="number" min={0} max={10000} value={position} onChange={e=>setPosition(+e.target.value)} /></Field>
      <div className="content-form-actions"><Button type="submit" disabled={busy||conflict}>Save</Button><Button variant="outline" disabled={busy || !key || !revision || conflict} onClick={()=>void save(true)}>Delete</Button></div>
    </form></fieldset>
    {conflict && <div role="status"><p>Your draft is preserved. Compare it with the latest saved section before continuing.</p>
      {latest ? <><h3>Latest saved content</h3><ContentBlock data={latest.draft}/><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere"}}>{JSON.stringify({draft:latest.draft,status:latest.status,position:latest.position},null,2)}</pre><Button onClick={()=>{setDraft(latest.draft);setStatus(latest.status);setPosition(latest.position);setRevision(latest.revision);setConflict(false);setError("");}}>Discard my draft and load latest</Button>
      <Button onClick={()=>{setRevision(latest.revision);setConflict(false);setError("");}}>Keep my draft for manual merge</Button></> : <p>Reload the section list or choose New section after preserving your draft.</p>}
    </div>}
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <div className="content-preview"><span className="admin-kicker">LIVE DRAFT</span><h3>Preview your section</h3>{draft.title||draft.description||draft.image?<ContentBlock data={draft}/>:<p className="admin-empty">Add a title, description, or image to see your section take shape.</p>}</div>
    <details className="admin-disclosure"><summary>Identity settings and network diagnostics</summary><UserAgentAdmin token={token} /><NetworkStatus token={token} /></details>
    {(query.data?.total || 0)>200 && <p>Only the first 200 sections are shown. Use the paginated admin API for additional sections.</p>}
  </section>;
}
