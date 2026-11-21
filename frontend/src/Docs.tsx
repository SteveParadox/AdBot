import { useEffect, useState } from "react";
import { BookOpen, Radar, Search } from "lucide-react";
import { docs, findDoc } from "./docsContent";
import "./docs.css";

export default function Docs({ path = window.location.pathname }: { path?: string }) {
  const [search, setSearch] = useState("");
  const page = findDoc(path);
  const index = docs.findIndex(item => item.slug === page?.slug);
  const query = search.trim().toLocaleLowerCase();
  const results = docs.filter(item => [item.title, item.description, ...item.sections.flatMap(section => [section.title, ...section.paragraphs, ...section.steps])].join(" ").toLocaleLowerCase().includes(query));
  useEffect(() => { document.title = `${page?.title ?? "Guide not found"} | AdBot Docs`; }, [page]);
  return <div className="docs-shell">
    <a className="docs-skip" href="#docs-main">Skip to documentation</a>
    <header className="docs-header"><a className="docs-brand" href="/docs"><Radar size={24}/>AdBot <span>Docs</span></a><a href="/">Open workspace</a></header>
    <div className="docs-layout">
      <aside className="docs-sidebar">
        <label className="docs-search"><Search size={18}/><span className="sr-only">Search documentation</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search all guides…"/></label>
        {query && <p className="docs-result-count" role="status">{results.length} matching {results.length === 1 ? "guide" : "guides"}</p>}
        <nav aria-label="Documentation navigation">{[...new Set(docs.map(item => item.group))].map(group => {
          const items = results.filter(item => item.group === group);
          return items.length > 0 && <div className="docs-nav-group" key={group}><h2>{group}</h2>{items.map(item => <a key={item.slug} href={`/docs/${item.slug}`} aria-current={page?.slug === item.slug ? "page" : undefined}>{item.title}</a>)}</div>;
        })}</nav>
        {results.length === 0 && <p>No guides found. Try “jobs”, “exports” or “API key”.</p>}
      </aside>
      <main id="docs-main" className="docs-article" tabIndex={-1}>
        {page ? <>
          <p className="docs-eyebrow"><BookOpen size={16}/>{page.group}</p><h1>{page.title}</h1><p className="docs-description">{page.description}</p>
          <nav className="docs-toc" aria-label="On this page"><strong>On this page</strong>{page.sections.map(section => <a key={section.id} href={`#${section.id}`}>{section.title}</a>)}</nav>
          {page.slug === "introduction" && <div className="docs-cards">{docs.filter(item => ["quick-start", "ai-agent", "data-extraction", "troubleshooting"].includes(item.slug)).map(item => <a key={item.slug} href={`/docs/${item.slug}`}><strong>{item.title}</strong><span>{item.description}</span></a>)}</div>}
          {page.sections.map(section => <section key={section.id} aria-labelledby={section.id}><h2 id={section.id}><a href={`#${section.id}`}>{section.title}</a></h2>{section.paragraphs.map((paragraph, i) => <p key={i}>{paragraph}</p>)}{section.steps.length > 0 && <ol>{section.steps.map((step, i) => <li key={i}>{step}</li>)}</ol>}</section>)}
          <nav className="docs-pagination" aria-label="Adjacent guides">{index > 0 ? <a href={`/docs/${docs[index - 1].slug}`}><small>Previous guide</small>{docs[index - 1].title}</a> : <span/>}{index < docs.length - 1 && <a href={`/docs/${docs[index + 1].slug}`}><small>Next guide</small>{docs[index + 1].title}</a>}</nav>
        </> : <><h1>Guide not found</h1><p>This documentation page does not exist.</p><a href="/docs">Browse all documentation</a></>}
        <footer className="docs-footer">Need installation commands or technical details? <a href="https://github.com/SteveParadox/AdBot/blob/main/README.md">Repository README</a> · <a href="https://github.com/SteveParadox/AdBot/tree/main/docs">Technical documentation</a></footer>
      </main>
    </div>
  </div>;
}
