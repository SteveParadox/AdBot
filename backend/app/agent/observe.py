"""Bounded visible-text/accessibility observation and semantic control registry."""

import re
import hashlib
import json

from .memory import fingerprint

CONTROL_SELECTOR = (
    "a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],[role=menuitem]"
)
DOM = """() => {
 const scope=document.querySelector('main,article,[role=main]')||document.body;
 const all=[...document.querySelectorAll('a[href],button,input:not([type=hidden]),textarea,select,[role=button],[role=link],[role=tab],[role=menuitem]')];
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'};
 const elements=all.map((e,index)=>{
   const tag=e.tagName.toLowerCase(),type=(e.type||'').toLowerCase();
   let role=e.getAttribute('role')||({a:'link',button:'button',textarea:'textbox',select:'combobox'}[tag])||(tag==='input'?(type==='search'?'searchbox':['submit','button'].includes(type)?'button':type==='checkbox'?'checkbox':'textbox'):'');
   const labelled=(e.getAttribute('aria-labelledby')||'').split(' ').map(id=>document.getElementById(id)?.textContent||'').join(' ').trim();
   const name=(e.getAttribute('aria-label')||labelled||[...(e.labels||[])].map(l=>l.textContent).join(' ')||e.innerText||e.getAttribute('alt')||e.getAttribute('placeholder')||(type==='submit'?e.value:'')||'').trim().replace(/\\s+/g,' ').slice(0,160);
   const f=e.closest('form'),r=e.getBoundingClientRect();
   return {index,role,name,tag,type,visible:visible(e),href:tag==='a'?e.href:null,disabled:!!e.disabled||e.getAttribute('aria-disabled')==='true',focused:document.activeElement===e,expanded:e.getAttribute('aria-expanded'),
     form:f?{method:(f.method||'get').toUpperCase(),action:f.action||location.href,search:!!(f.querySelector('input[type=search]')||f.getAttribute('role')==='search')}:null,
     safe:e.dataset.adbotSafe==='true', in_view:r.top<innerHeight&&r.bottom>0};
 }).filter(e=>e.visible&&!['password','file','hidden'].includes(e.type)).slice(0,80);
 const blocks=[...scope.querySelectorAll('h1,h2,h3,p,li,pre,td,[role=alert]')].filter(visible).filter(e=>{const r=e.getBoundingClientRect();return r.top<innerHeight&&r.bottom>0}).slice(0,80).map(e=>e.innerText).join('\\n');
 return {title:document.title, text:(scope.innerText||'').slice(0,12000), viewport_text:blocks.slice(0,6000),
 headings:[...scope.querySelectorAll('h1,h2,h3')].slice(0,30).map(e=>e.innerText),elements,
 scroll:{y:Math.round(scrollY),height:document.documentElement.scrollHeight,viewport:innerHeight,at_end:scrollY+innerHeight>=document.documentElement.scrollHeight-5}};
}"""


def redact(text):
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~-]{12,}", r"\1[redacted]", text)
    return re.sub(r"(?i)((?:api[_-]?key|password|access[_-]?token|secret)\s*[:=]\s*)[^\s,;]+", r"\1[redacted]", text)


class Observer:
    def __init__(self):
        self.registry = {}

    async def observe(self, page, tab_id):
        data = await page.evaluate(DOM)
        data["url"] = page.url
        data["tab_id"] = tab_id
        data["text"] = redact(data["text"])
        data["viewport_text"] = redact(data["viewport_text"])
        fields = await page.locator("input,textarea,select").evaluate_all(
            "fields => fields.slice(0,100).map(e => ({name:e.name,type:e.type,value:['password','file'].includes(e.type)?'[secret]':String(e.value||'').slice(0,4000),checked:!!e.checked}))"
        )
        data["form_state"] = hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
        try:
            data["accessibility"] = redact((await page.locator("body").aria_snapshot(timeout=3000))[:6000])
        except Exception:
            data["accessibility"] = "Accessibility snapshot unavailable; semantic DOM remains available"
        self.registry = {}
        for i, element in enumerate(data["elements"]):
            element["element_id"] = f"e{i}"
            locator = page.get_by_role(element["role"], name=element["name"], exact=True) if element["name"] else None
            if locator is None or await locator.count() != 1:
                locator = page.locator(CONTROL_SELECTOR).nth(element["index"])
            self.registry[element["element_id"]] = (locator, element)
        data["fingerprint"] = fingerprint(data)
        return data

    def target(self, decision):
        if not decision.target or decision.target.element_id not in self.registry:
            raise ValueError("Action must reference an element from the latest observation")
        return self.registry[decision.target.element_id]
