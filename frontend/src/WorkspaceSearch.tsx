import { useEffect, useId, useRef, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { Button } from "./ui";

export type WorkspaceDestination = { id: string; label: string; description: string; choose: () => void };

export function WorkspaceSearch({ destinations }: { destinations: WorkspaceDestination[] }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const [query, setQuery] = useState("");
  const titleId = useId();
  const matches = destinations.filter(item => `${item.label} ${item.description}`.toLowerCase().includes(query.trim().toLowerCase()));
  useEffect(() => {
    function shortcut(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!dialog.current?.open) dialog.current?.showModal();
      }
    }
    document.addEventListener("keydown", shortcut);
    return () => document.removeEventListener("keydown", shortcut);
  }, []);
  function close() { dialog.current?.close(); }
  return <>
    <Button ref={trigger} variant="outline" className="workspace-search-trigger" aria-label="Search workspace" onClick={() => dialog.current?.showModal()}>
      <Search size={16} /><span>Search workspace</span><kbd>Ctrl K</kbd>
    </Button>
    <dialog ref={dialog} className="workspace-search-dialog" aria-labelledby={titleId}
      onClose={() => { setQuery(""); trigger.current?.focus(); }}
      onClick={event => { if (event.target === event.currentTarget) { const bounds = event.currentTarget.getBoundingClientRect(); if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) close(); } }}
      onKeyDown={event => {
        if (!["ArrowDown", "ArrowUp"].includes(event.key)) return;
        const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("[data-search-result]")];
        if (!buttons.length) return;
        event.preventDefault();
        const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
        const next = current < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1) : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
        buttons[next].focus();
      }}>
      <div className="workspace-search-heading"><div><span className="eyebrow">QUICK NAVIGATION</span><h2 id={titleId}>Where would you like to go?</h2></div><Button variant="ghost" aria-label="Close workspace search" onClick={close}><X size={18}/></Button></div>
      <label className="workspace-search-input"><Search size={19}/><input autoFocus type="search" aria-label="Find a page or action" placeholder="Search pages and actions..." value={query} onChange={event => setQuery(event.target.value)}/></label>
      <div className="workspace-search-results">
        {matches.map(item => <button data-search-result key={item.id} onClick={() => { close(); item.choose(); }}><span><strong>{item.label}</strong><small>{item.description}</small></span><ArrowUpRight size={17}/></button>)}
        {!matches.length && <p className="workspace-search-empty">No matches. Try websites, jobs, or extraction.</p>}
      </div>
      <div className="workspace-search-footer"><span>Arrow keys to explore / Enter to open</span><span>Esc to close</span></div>
    </dialog>
  </>;
}
