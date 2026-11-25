"""Bounded DOM context supplementing Playwright's maintained ARIA snapshots.

This does not implement accessible-name computation: native aria_snapshot and
role locators supply that. DOM labels below are disclosed fallback metadata.
"""

CONTROL_SELECTOR = (
    "a[href],button,input:not([type=hidden]),textarea,select,summary,dialog,table,output,[contenteditable=true],"
    "[role],[tabindex],[aria-live]"
)

METADATA = r"""e => {
 const text = v => String(v||'').trim().replace(/\s+/g,' ').slice(0,200);
 const refs = a => (e.getAttribute(a)||'').split(/\s+/).filter(Boolean);
 const labels = [...(e.labels||[])].map(l=>text(l.textContent));
 const type=(e.type||'').toLowerCase(),tag=e.tagName.toLowerCase();
 const fallback_name=text(refs('aria-labelledby').map(id=>e.ownerDocument.getElementById(id)?.textContent||'').join(' ')||e.getAttribute('aria-label')||labels.join(' ')||e.getAttribute('alt')||e.innerText||e.getAttribute('placeholder')||(type==='submit'?e.value:'')||e.title);
 const role=e.getAttribute('role')?.split(/\s+/)[0]||({a:e.hasAttribute('href')?'link':'generic',button:'button',textarea:'textbox',select:e.multiple||e.size>1?'listbox':'combobox',summary:'button',dialog:'dialog'}[tag])||(tag==='input'?({checkbox:'checkbox',radio:'radio',number:'spinbutton',range:'slider',search:'searchbox',button:'button',submit:'button',reset:'button'}[type]||'textbox'):e.isContentEditable?'textbox':'generic');
 const r=e.getBoundingClientRect(),s=getComputedStyle(e);
 const visible=!!(r.width&&r.height)&&s.visibility!=='hidden'&&s.display!=='none'&&!e.closest('[hidden],[aria-hidden=true]');
 const bool=a=> e.hasAttribute(a)?e.getAttribute(a)==='true':null;
 const form=e.form||e.closest('form');
 const landmark=e.closest('dialog,[role=dialog],[role=alertdialog],form,section[aria-label],section[aria-labelledby],[role=region],article,nav,main');
 const heading=landmark?.querySelector('h1,h2,h3,h4,[role=heading]');
 const context=landmark?{tag:landmark.tagName.toLowerCase(),id:landmark.id||null,role:landmark.getAttribute('role')||({form:'form',dialog:'dialog',nav:'navigation',main:'main',article:'article'}[landmark.tagName.toLowerCase()])||'region',name:text((landmark.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>document.getElementById(id)?.textContent||'').join(' ')||landmark.getAttribute('aria-label')),heading:text(heading?.textContent)}:null;
 const modals=[...document.querySelectorAll('dialog[open],[role=dialog][aria-modal=true],[role=alertdialog][aria-modal=true]')].filter(d=>d.getClientRects().length&&getComputedStyle(d).visibility!=='hidden'&&(d.tagName!=='DIALOG'||d.matches(':modal')||d.getAttribute('aria-modal')==='true'));
 // Native top-layer order can differ from DOM order. Focus identifies the
 // active modal; ambiguous focus loss with multiple dialogs fails closed.
 const modal=[...modals].reverse().find(d=>d.contains(document.activeElement))||(modals.length===1?modals[0]:null);
 const modalBlocked=modals.length>0&&(!modal||!modal.contains(e));
 const sensitive=['password','file','hidden'].includes(type)||((['input','textarea','select'].includes(tag)||e.isContentEditable)&&(/password|credit.?card|card.?number|cvc|cvv|api.?key|access.?token|secret/i.test([fallback_name,e.name,e.autocomplete].join(' '))||/^cc-/.test(e.autocomplete||'')));
 const disabled=!!e.matches(':disabled')||!!e.closest('[aria-disabled=true],[inert]');
 const readonly=!!e.readOnly||e.getAttribute('aria-readonly')==='true';
 const value=sensitive?'[redacted]':text(e.value??e.getAttribute('aria-valuenow')??(e.isContentEditable?e.textContent:''));
 return {role,name:fallback_name,accessible_name:fallback_name,text:['status','alert','dialog','alertdialog','tabpanel','progressbar'].includes(role)||e.hasAttribute('aria-live')?text(e.innerText):'',description:text(refs('aria-describedby').map(id=>document.getElementById(id)?.textContent||'').join(' ')||e.getAttribute('aria-description')),labels,placeholder:text(e.getAttribute('placeholder')),tag,type,visible,disabled,enabled:!disabled,readonly,sensitive,
 focusable:(e.tabIndex>=0||e.hasAttribute('tabindex')||e.isContentEditable)&&!disabled,tabbable:e.tabIndex>=0&&!disabled,focused:document.activeElement===e,expanded:bool('aria-expanded'),pressed:e.getAttribute('aria-pressed'),checked:e.hasAttribute('aria-checked')?e.getAttribute('aria-checked'):['checkbox','radio'].includes(type)?e.checked:null,selected:e.hasAttribute('aria-selected')?bool('aria-selected'):tag==='option'?e.selected:null,
 required:!!e.required||e.getAttribute('aria-required')==='true',invalid:e.getAttribute('aria-invalid')==='true'||!!(e.willValidate&&!e.validity.valid),validation_message:sensitive?'':text(e.validationMessage),value,
 controls:refs('aria-controls'),labelledby:refs('aria-labelledby'),describedby:refs('aria-describedby'),active_descendant:e.getAttribute('aria-activedescendant'),busy:bool('aria-busy'),live:e.getAttribute('aria-live')||(['status','alert'].includes(role)?role:null),
 href:tag==='a'?e.href:null,rel:tag==='a'?(e.getAttribute('rel')||''):'',dom_id:e.id||null,test_id:e.getAttribute('data-testid'),context,
 form:form?{method:(form.method||'get').toUpperCase(),action:form.action||location.href,search:!!(form.querySelector('input[type=search]')||form.getAttribute('role')==='search'),name:text(form.getAttribute('aria-label')||form.name),invalid_count:[...form.elements].filter(x=>x.willValidate&&!x.validity.valid).length}:null,
 safe:e.dataset.adbotSafe==='true',in_view:r.top<innerHeight&&r.bottom>0&&r.left<innerWidth&&r.right>0,
 blocked_by_modal:modalBlocked,
 actionable:visible&&!disabled&&!sensitive&&!modalBlocked&&(e.matches('a[href],button,input,textarea,select,summary,[contenteditable=true],[tabindex]')||['button','link','checkbox','radio','switch','menuitem','menuitemcheckbox','menuitemradio','option','tab','combobox','listbox','slider','spinbutton','treeitem','gridcell'].includes(role)),
 bounds:{x:Math.round(r.x),y:Math.round(r.y),width:Math.round(r.width),height:Math.round(r.height)},
 options:tag==='select'?[...e.options].slice(0,40).map(o=>({label:text(o.label),value:sensitive?'[redacted]':text(o.value),selected:o.selected,disabled:o.disabled||!!o.closest('optgroup[disabled]')})):[]};
}"""

DOM = r"""() => {
 const metadata=METADATA_FUNCTION;
 const scope=document.querySelector('main,article,[role=main]')||document.body;
 const all=[...document.querySelectorAll(CONTROL_QUERY)].slice(0,2000);
 const elements=all.map((e,index)=>({...metadata(e),index}));
 const sensitive_values=[...document.querySelectorAll('input,textarea')].filter(e=>e.type!=='hidden'&&metadata(e).sensitive).map(e=>e.value).filter(Boolean);
 return {source_url:location.href,title:document.title,text:(scope.innerText||'').slice(0,12000),viewport_text:(scope.innerText||'').slice(0,6000),
 headings:[...document.querySelectorAll('h1,h2,h3,[role=heading]')].slice(0,30).map(e=>e.textContent.slice(0,200)),elements,
 candidate_limit:all.length===2000,sensitive_values,
 scroll:{y:Math.round(scrollY),height:document.documentElement.scrollHeight,viewport:innerHeight,at_end:scrollY+innerHeight>=document.documentElement.scrollHeight-5}};
}""".replace("METADATA_FUNCTION", METADATA).replace("CONTROL_QUERY", __import__("json").dumps(CONTROL_SELECTOR))
