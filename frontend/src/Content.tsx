import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Collection } from "./api";
import { Button, Field } from "./ui";
export type ContentData = { title?: string; description?: string; image?: string; image_alt?: string; link?: string; button?: string; canonical?: string };
type Section = { key: string; draft: ContentData; status: "draft" | "published" | "archived"; position: number };
export function useContent() {
  const query = useQuery({ queryKey: ["content"], queryFn: () => api<{items: (ContentData & {key: string})[]}>("/content", ""), staleTime: 30000, refetchInterval: 30000 });
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
export function ContentBlock({data}: {data: ContentData}) {
  return <section className="panel"><h2>{data.title}</h2><p>{data.description}</p>
    {data.image && <img src={data.image} alt={data.image_alt || ""} loading="lazy" style={{width:"100%", aspectRatio:"16 / 9", maxHeight:400, objectFit:"contain"}} />}
    {data.link && <a href={data.link}>{data.button || data.title || "Read more"}</a>}
  </section>;
}
export function ContentAdmin({token}: {token: string}) {
  const client = useQueryClient();
  const query = useQuery({queryKey:["admin-content",token], queryFn:()=>api<Collection<Section>>("/admin/content?limit=200",token), retry:false});
  const [key,setKey] = useState(""); const [draft,setDraft] = useState<ContentData>({});
  const [status,setStatus] = useState<Section["status"]>("draft"); const [position,setPosition] = useState(0);
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false); const [notice,setNotice] = useState("");
  async function save(remove=false) {
    setBusy(true); setError(""); setNotice("");
    try {
      await api("/admin/content/"+encodeURIComponent(key),token,remove?"DELETE":"POST",remove?undefined:{draft,status,position});
      await client.invalidateQueries({queryKey:["content"]}); await query.refetch(); setNotice(remove?"Deleted":"Saved");
    } catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  if(query.isPending) return <p role="status">Loading content editor…</p>;
  if(query.error) return <p role="alert">{query.error.message}</p>;
  return <section className="panel"><h2>Website content</h2>
    <p>Reserved keys control existing page headings and SEO. Other keys appear as ordered promotional sections on the login page. Draft saves preserve the last publication; archive hides it.</p>
    <Field label="Select section"><select value="" onChange={e=>{const s=query.data?.items.find(s=>s.key===e.target.value); if(s){setKey(s.key);setDraft(s.draft);setStatus(s.status);setPosition(s.position);}}}>
      <option value="">New section / select existing</option>{query.data?.items.map(s=><option key={s.key}>{s.key}</option>)}
    </select></Field>
    <form onSubmit={e=>{e.preventDefault();void save();}}>
      <Field label="Section key"><input required pattern="[A-Za-z0-9 _-]{1,80}" value={key} onChange={e=>setKey(e.target.value)} /></Field>
      {(["title","description","image","image_alt","link","button","canonical"] as const).map(field=><Field label={field} key={field}><textarea value={draft[field] || ""} onChange={e=>setDraft({...draft,[field]:e.target.value})} /></Field>)}
      <Field label="Status"><select value={status} onChange={e=>setStatus(e.target.value as Section["status"])}>{["draft","published","archived"].map(s=><option key={s}>{s}</option>)}</select></Field>
      <Field label="Order"><input type="number" min={0} max={10000} value={position} onChange={e=>setPosition(+e.target.value)} /></Field>
      <Button type="submit" disabled={busy}>Save</Button><Button disabled={busy || !key} onClick={()=>void save(true)}>Delete</Button>
    </form>
    {error && <p role="alert">{error}</p>}{notice && <p role="status">{notice}</p>}
    <h3>Draft preview</h3><ContentBlock data={draft} />
    {(query.data?.total || 0)>200 && <p>Only the first 200 sections are shown. Use the paginated admin API for additional sections.</p>}
  </section>;
}
