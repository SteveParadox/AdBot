import hashlib
import json
import re
import time

from cryptography.fernet import Fernet
from sqlalchemy import select

from ..config import settings
from ..db import AgentMemory


def fingerprint(observation):
    data = {key: observation.get(key) for key in ("url", "tab_id", "text", "scroll", "form_state")}
    data["elements"] = [
        {key: value for key, value in element.items() if key != "element_id"}
        for element in observation.get("elements", [])
    ]
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def action_key(decision):
    return hashlib.sha256(
        json.dumps(
            {
                k: decision.get(k)
                for k in (
                    "decision",
                    "target",
                    "text",
                    "source_quote",
                    "url",
                    "direction",
                    "tab_id",
                    "key",
                    "input_method",
                    "expected_text",
                    "checked",
                    "option",
                    "capture",
                )
            } | ({"claims": decision.get("claims", [])} if decision.get("decision") == "COMPLETE" else {}),
            sort_keys=True,
        ).encode()
    ).hexdigest()


def semantic_action_key(decision, observation):
    """Track equivalent read-side actions despite changing element IDs or scroll offsets."""
    action = decision["decision"]
    if action not in {"CLICK", "SCROLL", "SCROLL_BACK"}:
        return None
    target_id = (decision.get("target") or {}).get("element_id")
    target = next((element for element in observation.get("elements", []) if element["element_id"] == target_id), None)
    if action == "CLICK" and (not target or target.get("form") or target.get("role") not in {"link", "button"}):
        return None
    identity = {key: target.get(key) for key in ("role", "name", "href", "expanded", "selected", "pressed")} if target else {}
    if target:
        identity["heading"] = (target.get("context") or {}).get("heading")
    material = {
        "url": observation.get("url"), "tab": observation.get("tab_id"), "action": action,
        "target": identity, "direction": decision.get("direction"),
        "headings": observation.get("headings", [])[:12],
        "text": observation.get("text", ""),
    }
    if action in {"SCROLL", "SCROLL_BACK"}:
        material["at_end"] = observation.get("scroll", {}).get("at_end")
    return hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()


def relevant_memories(session, owner, website_id, objective):
    words = set(re.findall(r"\w{3,}", objective.lower()))
    records = session.scalars(
        select(AgentMemory)
        .where(AgentMemory.owner == owner, AgentMemory.website_id == website_id, AgentMemory.expires_at > time.time())
        .order_by(AgentMemory.created_at.desc())
        .limit(100)
    ).all()
    ranked = sorted(records, key=lambda m: len(words & set(re.findall(r"\w{3,}", m.objective.lower()))), reverse=True)
    return [
        {
            "id": m.id,
            "objective": m.objective[:600],
            "content": {
                "claims": m.content.get("claims", [])[:5],
                "evidence": [dict(e, quote=e["quote"][:300]) for e in m.content.get("evidence", [])[:5]],
            },
            "warning": "Historical hints only; verify against the current page",
        }
        for m in ranked[:3]
        if words & set(re.findall(r"\w{3,}", m.objective.lower()))
    ]


def save_memory(session, job, task):
    session.add(
        AgentMemory(
            owner=job.owner,
            website_id=job.website_id,
            source_job_id=job.id,
            objective=task.objective,
            content=task.result,
            expires_at=time.time() + settings().retention_days * 86400,
        )
    )


def encrypt_session(state):
    return (
        Fernet(settings().session_encryption_key.get_secret_value().encode())
        .encrypt(json.dumps(state).encode())
        .decode()
    )


def decrypt_session(value):
    if not value:
        return None
    return json.loads(Fernet(settings().session_encryption_key.get_secret_value().encode()).decrypt(value.encode()))
