"""Opt-in test fixture. Bind to loopback; never deploy publicly."""

import asyncio

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse

app = FastAPI()


@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return "User-agent: *\nDisallow: /private\n"


@app.get("/", response_class=HTMLResponse)
def index():
    return """<!doctype html><title>AdBot fixture</title><h1>Monitoring fixture</h1>
    <a href='/about'>About</a><a href='/about#duplicate'>Duplicate</a>
    <a href='/missing'>Deliberate 404</a><a href='/private'>Robots denied</a>
    <a href='/redirect'>Redirect</a><a href='http://169.254.169.254/'>Blocked metadata</a>
    <button data-adbot-safe='true' id='toggle' onclick="document.getElementById('result').textContent='Clicked'">Toggle</button>
    <p id='result'>Ready</p><div style='height:2000px'>Scroll test</div>"""


@app.get("/about", response_class=HTMLResponse)
def about():
    return "<title>About fixture</title><h1>About</h1><a href='/'>Home</a><a href='/deep'>Deep</a>"


@app.get("/deep", response_class=HTMLResponse)
def deep():
    return "<title>Deep page</title><h1>Depth limit fixture</h1>"


@app.get("/private")
def private():
    return {"should_never_be_visited": True}


@app.get("/redirect")
def redirect():
    return RedirectResponse("/about")


@app.get("/unsafe-redirect")
def unsafe_redirect():
    return RedirectResponse("http://169.254.169.254/latest/meta-data/")


@app.get("/slow", response_class=HTMLResponse)
async def slow():
    await asyncio.sleep(5)
    return "<title>Slow</title>"


@app.get("/rate-limited")
def limited():
    return PlainTextResponse("Back off", status_code=429, headers={"Retry-After": "1"})


@app.get("/agent/news", response_class=HTMLResponse)
def agent_news(layout: int = 0):
    links = [
        "<a href='/agent/article/orion'>Orion AI launch update</a>",
        "<a href='/agent/article/weather'>Weekend weather report</a>",
    ]
    if layout % 2:
        links.reverse()
    return "<title>Technology Desk</title><main><h1>Technology Desk</h1>" + " ".join(links) + "</main>"


@app.get("/agent/article/orion", response_class=HTMLResponse)
def agent_article():
    return """<title>Orion AI release notes</title><main><article><h1>Orion AI release notes</h1>
    <p>Orion AI will launch in November 2026.</p><p>The preview supports project search and cited answers.</p>
    <a href='/agent/news'>News desk</a><a href='/agent/manual.txt'>Download release notes</a></article></main>
    <script>document.cookie='fixture_session=demo-cookie; path=/; SameSite=Lax'</script>"""


@app.get("/agent/article/weather", response_class=HTMLResponse)
def weather_article():
    return "<main><h1>Weekend weather</h1><p>Clear skies are expected on Sunday.</p></main>"


@app.get("/agent/search", response_class=HTMLResponse)
def agent_search(q: str = ""):
    return (
        """<main><h1>Documentation search</h1><form method='get' role='search'>
    <label>Search documentation<input type='search' name='q'></label><button>Search</button></form>"""
        + (
            "<section><h2>Search results</h2><a href='/agent/article/orion'>Orion AI release notes</a></section>"
            if q
            else ""
        )
        + "</main>"
    )


@app.get("/agent/dynamic", response_class=HTMLResponse)
def agent_dynamic():
    return """<main><h1>Loading the technology desk</h1><div id='results'></div></main><script>
    setTimeout(()=>document.querySelector('#results').innerHTML="<a href='/agent/article/orion'>Orion AI launch update</a>",300);
    </script>"""


@app.get("/agent/catalog", response_class=HTMLResponse)
def agent_catalog():
    return "<main><h1>Product catalog</h1><a href='/agent/product/orion'>Orion AI workstation</a><a href='/agent/product/desk'>Office desk</a></main>"


@app.get("/agent/product/orion", response_class=HTMLResponse)
def agent_product():
    return "<main><h1>Orion AI workstation</h1><p>The Orion AI workstation costs 899 dollars.</p></main>"


@app.get("/agent/product/desk", response_class=HTMLResponse)
def desk_product():
    return "<main><h1>Office desk</h1><p>The desk costs 199 dollars.</p></main>"


@app.get("/agent/form", response_class=HTMLResponse)
def agent_form(name: str = ""):
    from html import escape

    if not name:
        return """<main><h1>Demo registration</h1><form method='get'><label>Name<input name='name'></label><button>Continue</button></form></main>"""
    return (
        "<main><h1>Review demo registration</h1><form method='post' action='/agent/form-result'><label>Name<input name='name' value='"
        + escape(name, quote=True)
        + "'></label><button>Submit registration</button></form></main>"
    )


@app.post("/agent/form-result", response_class=HTMLResponse)
async def agent_form_result(request: Request):
    from html import escape
    from urllib.parse import parse_qs

    data = parse_qs((await request.body()).decode())
    return (
        "<main><h1>Confirmation</h1><p>Registration received for " + escape(data.get("name", [""])[0]) + ".</p></main>"
    )


@app.get("/agent/manual.txt", response_class=PlainTextResponse)
def manual():
    return "Orion AI will launch in November 2026."
