"""TEST DOUBLE, not a production model: chooses from live semantic observations.

Uses lexical goal relevance; it never knows fixture URLs or a fixed action list.
Served only by tests to exercise the real JSON transport with real browsers.
"""

import json
import re

from fastapi import FastAPI, Request

app = FastAPI()
STOP = {
    "find",
    "the",
    "and",
    "this",
    "that",
    "with",
    "from",
    "source",
    "cite",
    "its",
    "for",
    "search",
    "portal",
    "then",
    "verify",
    "enter",
    "field",
    "submit",
    "demo",
    "form",
    "costs",
    "price",
    "month",
    "launch",
}


def words(text):
    return set(re.findall(r"[a-z0-9]+", text.lower())) - STOP


def decide(payload):
    goal = payload["objective"]
    memory = payload.get("session_memory", {})
    observation = payload.get("current_page", {})
    evidence = memory.get("evidence", [])

    def action(name, **parameters):
        return {
            "observation": "Inspecting the supplied live semantic page state",
            "decision": name,
            "reason": "The observed control or quote advances the user's objective",
            "confidence": 0.9,
            "expected_result": "Find and verify relevant page evidence",
            **parameters,
        }

    if payload["purpose"] == "verify":
        return {
            "complete": bool(payload["evidence"]),
            "explanation": "Fixture verifier found quoted source evidence",
            "checks": [
                {
                    "criterion": c,
                    "met": bool(payload["evidence"]),
                    "evidence_ids": [e["id"] for e in payload["evidence"]],
                }
                for c in payload["success_criteria"]
            ],
        }
    if evidence:
        return action("COMPLETE", claims=[{"text": e["quote"], "evidence_ids": [e["id"]]} for e in evidence])
    text = observation.get("text", "")
    elements = observation.get("elements", [])
    if "registration" in goal.lower():
        if "Registration received" in text:
            quote = next(line.strip() for line in text.splitlines() if "Registration received" in line)
            return action("EXTRACT", text=quote)
        typed = any(a["action"] == "TYPE" for a in memory.get("recent_actions", []))
        target = next((e for e in elements if e["name"] == "Name" and e["role"] == "textbox"), None)
        if target and not typed:
            return action("TYPE", target={"element_id": target["element_id"]}, text="Ada")
        button = next((e for e in elements if e["role"] == "button"), None)
        if button:
            return action("CLICK", target={"element_id": button["element_id"]})
    sentences = [s.strip() for s in text.splitlines() if len(s) > 20 and s.strip().endswith(".")]
    relevant = [s for s in sentences if len(words(s) & words(goal)) >= 2]
    if relevant:
        return action("EXTRACT", text=max(relevant, key=lambda s: len(words(s) & words(goal))))
    searched = any(a["action"] == "SEARCH" for a in memory.get("recent_actions", []))
    search = next((e for e in elements if e["role"] == "searchbox"), None)
    if search and not searched:
        return action("SEARCH", target={"element_id": search["element_id"]}, text="Orion AI")
    links = [e for e in elements if e["role"] == "link"]
    links.sort(key=lambda e: len(words(e["name"]) & words(goal)), reverse=True)
    if links and words(links[0]["name"]) & words(goal):
        return action("CLICK", target={"element_id": links[0]["element_id"]})
    return action("WAIT")


@app.post("/v1/chat/completions")
async def completion(request: Request):
    body = await request.json()
    content = body["messages"][-1]["content"]
    if isinstance(content, list):
        content = content[0]["text"]
    payload = json.loads(content)
    return {
        "choices": [{"message": {"content": json.dumps(decide(payload))}}],
        "usage": {"prompt_tokens": 600, "completion_tokens": 200},
    }
