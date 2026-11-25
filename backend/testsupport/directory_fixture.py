"""Synthetic directory used by the browser regression and timing receipt."""
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

router = APIRouter()
RECORD_COUNT = 119
CATEGORIES = ["AI chatbot", "Image generator", "SEO tool", "Audio editor", "Video editor"]
EXPECTED = {f"Tool {index:03}" for index in range(1, RECORD_COUNT + 1) if index % len(CATEGORIES) == 0}
CONVERSATION_DESCRIPTION = "Visitors practice languages and ask follow-up questions in a conversation with the product."
TRANSCRIPTION_DESCRIPTION = "Converts uploaded audio recordings into time-coded transcripts."


@router.get("/execution-fixture", response_class=HTMLResponse)
def home():
    return '<main><h1>Reference website</h1><a href="/execution-fixture/tools">Tools</a></main>'


@router.get("/execution-fixture/tools", response_class=HTMLResponse)
def tools(page: Annotated[int, Query(ge=1, le=8)] = 1,
          case: Literal["normal", "cycle", "unknown", "mismatch", "recovery"] = "normal"):
    per_page = 15
    first = (page - 1) * per_page + 1
    last = min(page * per_page, RECORD_COUNT)
    numbers = list(range(first, last + 1))
    if page == 2 and case == "cycle":
        numbers = list(range(1, 16))
    elif page > 1:
        numbers.append(first - 1)
    rows = []
    for index in numbers:
        category = CATEGORIES[index % len(CATEGORIES)]
        if case == "unknown" and index == 1:
            category = "AI"
        text = "This product offers an AI chatbot for support." if category == "AI chatbot" else "A specialized product."
        if page % 2 == 0:
            rows.append(f'<div><a href="/execution-fixture/tool/{index}" aria-label="Tool {index:03}">Tool {index:03}</a>'
                        f'<div><span itemprop="category">{category}</span><div>{text}</div></div></div>')
        else:
            rows.append(f'<article><h2><a href="/execution-fixture/tool/{index}">Tool {index:03}</a></h2>'
                        f'<span itemprop="category">{category}</span><p>{text}</p></article>')
    total = RECORD_COUNT + int(case == "mismatch")
    previous = f'<a href="?page={page - 1}&amp;case={case}">Previous</a>' if page > 1 else '<button disabled>Previous</button>'
    # The primary fixture uses an actual JavaScript pager with no form submission.
    next_control = (f'<button type="button" onclick="location.href=\'?page={page + 1}\'">Next</button>'
                    if case == "normal" else f'<a href="?page={page + 1}">Next</a>')
    if case not in {"normal", "recovery"}:
        # Test variants retain their state through a browser-visible URL fragment.
        next_control = f'<a href="?page={page + 1}&amp;case={case}">Next</a>'
    if last >= RECORD_COUNT:
        next_control = '<button disabled>Next</button>'
    numbered = ""
    if case == "recovery" and page == 1:
        next_control = '<a href="?page=1">Next</a>'
        numbered = '<span aria-current="page">1</span><a href="?page=2">2</a>'
    decoration = '<aside>' + '<a href="/irrelevant">Repeated decorative link</a>' * 115 + '</aside>'
    return (
        '<main><h1>AI Tools</h1><input type="search" aria-label="Search tools">'
        '<section aria-label="Tag filter"><button type="button" id="tags" aria-expanded="false" '
        'onclick="this.setAttribute(\'aria-expanded\',\'true\'); document.querySelector(\'#choices\').hidden=false">'
        'All tags</button><div id="choices" hidden><button type="button">ai</button></div></section>'
        '<fieldset aria-label="Pricing filter"><button type="button" aria-pressed="true">All pricing</button>'
        '<button type="button">Free</button></fieldset>'
        f'<p>Showing {first}-{last} of {total} matching tools.</p>'
        f'<section id="grid" aria-busy="true"></section><template id="records">{"".join(rows)}</template>'
        f'<nav aria-label="Pagination">{previous}{next_control}{numbered}</nav>{decoration}</main>'
        "<script>setTimeout(()=>{ grid.append(records.content.cloneNode(true)); grid.setAttribute('aria-busy','false') },30)</script>"
    )


@router.get("/execution-fixture/recovery", response_class=HTMLResponse)
def recovery(page: Annotated[int, Query(ge=1, le=8)] = 1):
    return tools(page, "recovery")


@router.get("/execution-fixture/semantic", response_class=HTMLResponse)
def semantic():
    return (
        '<h1>AI products</h1><p>2 products</p><ul>'
        '<li><a href="/execution-fixture/tool/ask">Ask</a><span itemprop="category">AI</span>'
        f'<p>{CONVERSATION_DESCRIPTION}</p></li>'
        '<li><a href="/execution-fixture/tool/transcribe">Transcribe</a><span itemprop="category">AI</span>'
        f'<p>{TRANSCRIPTION_DESCRIPTION}</p></li></ul>'
    )


@router.get("/execution-fixture/table", response_class=HTMLResponse)
def table():
    return (
        '<h1>Office hours</h1><table><thead><tr><th>Day</th><th>Time</th></tr></thead>'
        '<tbody><tr><td>Monday</td><td>09:00</td></tr><tr><td>Tuesday</td><td>11:00</td></tr></tbody></table>'
    )
