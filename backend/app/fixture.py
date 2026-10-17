"""Opt-in test fixture. Bind to loopback; never deploy publicly."""

import asyncio

from fastapi import FastAPI
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
