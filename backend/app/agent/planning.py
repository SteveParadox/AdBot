"""Validated task specification and bounded, evidence-driven plan state.

Model plans describe work; only the runner may advance statuses or authorize tools.
The literal user contract is immutable across planning, compaction and recovery.
"""

import hashlib
import json
import re
from typing import Literal

from pydantic import Field, model_validator

from ..schemas import Strict
from .routing import select_route


class Ambiguity(Strict):
    detail: str = Field(min_length=1, max_length=500)
    category: Literal["safe_default", "discoverable", "disclose", "clarify"]
    quote: str = Field("", max_length=500)


class Intent(Strict):
    primary_objective: str = Field(min_length=1, max_length=4000)
    secondary_objectives: list[str] = Field(default_factory=list, max_length=10)
    entities: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=32)
    optional_outcomes: list[str] = Field(default_factory=list, max_length=10)
    ambiguities: list[Ambiguity] = Field(default_factory=list, max_length=10)


class Subtask(Strict):
    id: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,31}$")
    description: str = Field(min_length=1, max_length=500)
    parent_id: str | None = None
    dependencies: list[str] = Field(default_factory=list, max_length=20)
    kind: Literal["research", "collect", "dataset", "export", "verify"]
    expected_result: str = Field(min_length=1, max_length=500)
    criteria: list[str] = Field(default_factory=list, max_length=20)
    max_attempts: int = Field(3, ge=1, le=5)
    step_budget: int = Field(20, ge=1, le=500)
    status: Literal["pending", "active", "completed", "blocked", "failed"] = "pending"
    attempts: int = Field(0, ge=0, le=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=40)
    outcome: str = Field("", max_length=500)


class TaskPlan(Strict):
    intent: Intent
    subtasks: list[Subtask] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def graph(self):
        ids = [node.id for node in self.subtasks]
        if len(ids) != len(set(ids)):
            raise ValueError("Subtask IDs must be unique")
        # Hierarchy organizes tasks; execution dependencies independently order them.
        for graph in (
            {node.id: node.dependencies for node in self.subtasks},
            {node.id: [node.parent_id] if node.parent_id else [] for node in self.subtasks},
        ):
            visiting, done = set(), set()

            def visit(key):
                if key not in graph:
                    raise ValueError("Unknown task dependency or parent")
                if key in visiting:
                    raise ValueError("Circular task dependencies or hierarchy")
                if key in done:
                    return
                visiting.add(key)
                for parent in graph[key]:
                    visit(parent)
                visiting.remove(key)
                done.add(key)

            for key in graph:
                visit(key)
        return self


def execution_intent(objective):
    """Advisory routing metadata. The original specification remains authoritative."""
    hints = (
        ("form_interaction", r"\b(?:fill|submit|register|sign up)\b"),
        ("document_retrieval", r"\b(?:download|retrieve)\b.*\b(?:file|document|pdf)\b"),
        ("comparison", r"\b(?:compare|comparison|versus)\b"),
        ("structured_extraction", r"\b(?:list|collect|extract)\b"),
        ("search", r"\b(?:search|find|look up)\b"),
        ("research", r"\b(?:research|summarize|explain|verify)\b"),
        ("navigation", r"\b(?:navigate|open|visit|go to)\b"),
    )
    strategy = next((name for name, pattern in hints if re.search(pattern, objective, re.I)), "general")
    quantifiers = re.findall(
        r"\b(?:all|every|first|latest|cheapest|highest rated|at least \d+|exactly \d+|between \d+ and \d+)\b",
        objective, re.I,
    )
    return {"category": strategy, "quantifiers": list(dict.fromkeys(word.casefold() for word in quantifiers))}


def specification(objective, criteria, options, domains):
    # Keep exact fragments: these are user requirements, not inferred facts.
    clauses = [part.strip() for part in re.split(r"(?<=[.;\n])\s+|\s+(?:and then|then)\s+", objective) if part.strip()]
    constraints = [
        match.group(0).strip()
        for match in re.finditer(
            r"\b(?:exclude|except|without|never|do not|must not|don['’]t|mustn['’]t|only|unless|if)\b[^.;\n]*",
            objective,
            re.I,
        )
    ]
    if len(clauses) > 32 or len(constraints) > 32:
        raise ValueError("Split objectives exceeding 32 instruction/constraint clauses into separate tasks")
    formats = re.findall(r"\b(csv|json)\b", objective, re.I)
    requested = options.get("output_format") or (
        formats[-1].lower()
        if formats and re.search(r"\b(export|save|download|output)\b", objective, re.I)
        else "answer"
    )
    ambiguities = []
    selected = options.get("output_format")
    mentioned = {s.lower() for s in formats}
    if (
        selected
        and mentioned
        and selected not in mentioned
        and re.search(r"\b(export|save|download|output)\b", objective, re.I)
    ):
        ambiguities.append(
            {
                "detail": "Selected output format conflicts with the literal artifact request; align the objective and format before completion.",
                "category": "clarify",
                "quote": objective[:500],
            }
        )
    if not selected and not formats and re.search(r"\bexport\b", objective, re.I):
        requested = "json"
        ambiguities.append(
            {
                "detail": "No export format specified; JSON is the disclosed default. An owned dataset is required.",
                "category": "disclose",
                "quote": objective[:500],
            }
        )
    if len({s.lower() for s in formats}) > 1 and not options.get("output_format"):
        ambiguities.append(
            {
                "detail": "Multiple output formats requested; select one artifact format explicitly.",
                "category": "clarify",
                "quote": objective[:500],
            }
        )
    return {
        "objective": objective,
        "execution_intent": execution_intent(objective),
        "instruction_clauses": clauses[:32],
        "constraints": constraints[:32],
        "success_criteria": list(criteria),
        "allowed_domains": list(domains),
        "permissions": {
            "form_input": bool(options.get("allow_form_input")),
            "downloads": bool(options.get("allow_downloads")),
        },
        "output_format": requested,
        "ambiguities": ambiguities,
        "dataset_query": options.get("dataset_query"),
        "source_hash": hashlib.sha256(
            json.dumps(
                [
                    objective,
                    criteria,
                    domains,
                    options.get("allow_form_input"),
                    options.get("allow_downloads"),
                    requested,
                ] + ([options["dataset_query"]] if options.get("dataset_query") is not None else []),
                sort_keys=True,
            ).encode()
        ).hexdigest(),
    }


def needs_model_plan(spec):
    return len(spec["success_criteria"]) > 1 or bool(
        re.search(r"\b(export|exclude|compare|sort|unless|if|then|latest|first|top)\b", spec["objective"], re.I)
    )


def initial_plan(spec, max_steps=500, dataset=False):
    nodes = [
        Subtask(
            id="research",
            description="Inspect authorized pages and discover relevant routes",
            kind="research",
            expected_result="A current authorized browser observation",
            step_budget=max_steps,
        ),
        Subtask(
            id="collect",
            description="Collect evidence for every supplied outcome and constraint",
            kind="collect",
            dependencies=["research"],
            expected_result="Exact observed source evidence",
            criteria=spec["success_criteria"],
            step_budget=max_steps,
        ),
    ]
    prior = "collect"
    if spec["output_format"] in {"csv", "json"}:
        nodes.append(
            Subtask(
                id="dataset",
                description="Extract and validate structured records",
                kind="dataset",
                dependencies=[prior],
                expected_result="Valid records in the selected dataset",
                step_budget=max_steps,
            )
        )
        nodes.append(
            Subtask(
                id="export",
                description="Create the requested dataset artifact",
                kind="export",
                dependencies=["dataset"],
                expected_result="An existing export file with verified records",
                step_budget=max_steps,
            )
        )
        prior = "export"
    nodes.append(
        Subtask(
            id="verify",
            description="Verify all required outcomes and constraints against evidence",
            kind="verify",
            dependencies=[prior],
            expected_result="Every required criterion is supported",
            criteria=spec["success_criteria"],
            step_budget=max_steps,
        )
    )
    intent = Intent(
        primary_objective=spec["objective"], constraints=spec["constraints"], ambiguities=spec["ambiguities"]
    )
    state = {
        "specification": spec,
        "plan": TaskPlan(intent=intent, subtasks=nodes).model_dump(),
        "generation": 1,
        "replans": [],
        "active_subtask": None,
        "warnings": [],
        "action_counts": {},
        "stagnant": 0,
        "previous_progress": None,
    }
    route = select_route(spec["objective"], spec, dataset)
    state["route"] = route.name
    if route.entity:
        state["plan"]["intent"]["entities"] = [route.entity.removeprefix("semantic:")]
    if route.name != "general":
        state["plan"]["subtasks"][0]["description"] = route.guidance
    if spec["output_format"] in {"csv", "json"} and not dataset:
        state["warnings"].append(
            "Export requires a configured, owned extraction dataset. Read-only research may continue."
        )
    return state


def accept_model_plan(state, draft, max_steps):
    if not isinstance(draft, TaskPlan):
        raise ValueError("Planner returned the wrong structured contract")
    spec = state["specification"]
    if draft.intent.primary_objective != spec["objective"]:
        raise ValueError("Planner changed the original objective")
    if any(value not in draft.intent.constraints for value in spec["constraints"]):
        raise ValueError("Planner dropped an explicit constraint")
    kinds = {node.kind for node in draft.subtasks}
    needed = {"research", "collect", "verify"} | (
        {"dataset", "export"} if spec["output_format"] in {"csv", "json"} else set()
    )
    if not needed <= kinds:
        raise ValueError("Plan omits required execution phases")
    for node in draft.subtasks:
        if node.status != "pending" or node.attempts or node.evidence_ids or node.outcome:
            raise ValueError("A model cannot invent completed work or evidence")
        if node.step_budget > max_steps:
            raise ValueError("Subtask budget exceeds task ceiling")
        if node.kind == "export" and not any(n.id in node.dependencies and n.kind == "dataset" for n in draft.subtasks):
            raise ValueError("Exports depend on extracted data")
    nodes = {node.id: node for node in draft.subtasks}

    def ancestors(node):
        return set(node.dependencies).union(*(ancestors(nodes[key]) for key in node.dependencies))

    for node in draft.subtasks:
        required = (
            {"research"}
            if node.kind == "collect"
            else {"collect"}
            if node.kind == "dataset"
            else needed - {"verify"}
            if node.kind == "verify"
            else set()
        )
        if not required <= {nodes[key].kind for key in ancestors(node)}:
            raise ValueError("Plan phases must follow their required dependencies")
    state["plan"] = draft.model_dump()


def ready(state):
    nodes = state["plan"]["subtasks"]
    done = {n["id"] for n in nodes if n["status"] == "completed"}
    return [n for n in nodes if n["status"] in {"pending", "active"} and set(n["dependencies"]) <= done]


def evaluate(state, observation, evidence, dataset_count=0, artifact=False, verified=False,
             *, collection_complete=None, source_verified=None):
    for node in state["plan"]["subtasks"]:
        if node["status"] in {"failed", "blocked"}:
            continue
        if not set(node["dependencies"]) <= {n["id"] for n in state["plan"]["subtasks"] if n["status"] == "completed"}:
            continue
        satisfied = (
            node["kind"] == "research"
            and observation.get("url", "").startswith(("http://", "https://"))
            and source_verified is not False
            or node["kind"] == "collect"
            and (bool(evidence) if collection_complete is None else collection_complete)
            or node["kind"] == "dataset"
            and dataset_count > 0
            or node["kind"] == "export"
            and artifact
            or node["kind"] == "verify"
            and verified
        )
        if satisfied:
            node["status"] = "completed"
            node["evidence_ids"] = [e["id"] for e in evidence][:40]
            node["outcome"] = (
                "Verified completion"
                if node["kind"] == "verify"
                else "Observed checkpoint; final semantic verification is still required"
            )
    available = ready(state)
    state["active_subtask"] = available[0]["id"] if available else None
    if available:
        available[0]["status"] = "active"


def guard(state, decision, observation):
    nodes = ready(state)
    if decision.subtask_id and decision.subtask_id not in {n["id"] for n in nodes}:
        raise ValueError("Requested subtask has unfinished dependencies or is no longer active")
    active = next((n for n in nodes if n["id"] == decision.subtask_id), nodes[0] if nodes else None)
    if active and active["attempts"] >= active["step_budget"]:
        raise ValueError("Active subtask step budget exhausted")
    restrictions = " ".join(state["specification"]["constraints"]).lower()
    target = next(
        (
            e
            for e in observation.get("elements", [])
            if decision.target and e["element_id"] == decision.target.element_id
        ),
        {},
    )
    activation = decision.decision == "CLICK" or (
        decision.decision == "PRESS_KEY" and decision.key in {"Enter", "Space"}
    )
    prohibition = r"\b(?:do not|never|must not|don['’]t|mustn['’]t)\s+"
    if re.search(prohibition + r"(?:submit|send|buy|purchase|apply|delete)\b", restrictions):
        if activation and not target.get("href"):
            raise PermissionError("Explicit task prohibition blocks this interaction")
    if decision.decision == "DOWNLOAD" and re.search(prohibition + r"download\b", restrictions):
        raise PermissionError("Explicit task prohibition blocks downloads")
    ambiguities = state["specification"]["ambiguities"] + state["plan"]["intent"]["ambiguities"]
    if any(a["category"] == "clarify" for a in ambiguities):
        if activation and not target.get("href") or decision.decision in {"EXPORT_DATASET", "COMPLETE"}:
            raise PermissionError("Critical task ambiguity requires clarification before this action")
    if (
        decision.decision in {"TYPE", "SEARCH", "SET_CHECKED", "SELECT_OPTION"}
        and not state["specification"]["permissions"]["form_input"]
    ):
        raise PermissionError("Task does not authorize form input")
    if decision.decision == "DOWNLOAD" and not state["specification"]["permissions"]["downloads"]:
        raise PermissionError("Task does not authorize downloads")
    if active:
        active["attempts"] += 1
    state["active_subtask"] = active["id"] if active else None
    return active


def classify_failure(exc):
    message = str(exc).lower()
    if isinstance(exc, PermissionError) or any(
        s in message for s in ("authorization", "permission", "enable form", "policy", "denied", "captcha")
    ):
        return "requires_authorization"
    if any(s in message for s in ("deadline", "budget exhausted", "lease lost", "session expired")):
        return "terminal"
    if any(s in message for s in ("timeout", "network", "connection")):
        return "transient"
    if any(s in message for s in ("detached", "changed", "stale", "not visible", "disabled")):
        return "requires_replanning"
    return "recoverable"


def replan(state, reason, observation):
    if len(state["replans"]) >= 20:
        raise RuntimeError("Plan recovery limit reached")
    active = next((n for n in state["plan"]["subtasks"] if n["id"] == state["active_subtask"]), None)
    category = classify_failure(reason)
    if active:
        retries = state.setdefault("retry_counts", {})
        retries[active["id"]] = retries.get(active["id"], 0) + 1
        active["status"] = (
            "blocked"
            if category == "requires_authorization"
            else "failed"
            if category == "terminal" or retries[active["id"]] >= active["max_attempts"]
            else "pending"
        )
        active["outcome"] = str(reason)[:500]
        if active["status"] == "pending":
            nodes = state["plan"]["subtasks"]
            if len(nodes) >= 20:
                raise RuntimeError("Plan recovery node limit reached")
            identifier = f"recover_{state['generation']}"
            while identifier in {node["id"] for node in nodes}:
                identifier += "_r"
            recovery = Subtask(
                id=identifier,
                description="Reinspect current authorized page and select an alternative observed route",
                kind="research",
                dependencies=list(active["dependencies"]),
                expected_result="Fresh observation after failure; original objective and constraints retained",
                step_budget=1,
            ).model_dump()
            nodes.insert(nodes.index(active), recovery)
            active["dependencies"] = [recovery["id"]]
            state["active_subtask"] = recovery["id"]
    state["generation"] += 1
    state["replans"].append(
        {
            "generation": state["generation"],
            "reason": str(reason)[:300],
            "classification": category,
            "subtask_id": active["id"] if active else None,
            "url": observation.get("url"),
        }
    )
    return category


def track_progress(state, decision, observation, evidence_count):
    progress = [observation["fingerprint"], evidence_count]
    state["stagnant"] = state["stagnant"] + 1 if state["previous_progress"] == progress else 0
    state["previous_progress"] = progress
    key = hashlib.sha256(
        json.dumps(
            [
                decision.decision,
                decision.target.model_dump() if decision.target else None,
                decision.url,
                decision.text,
                observation["fingerprint"],
            ],
            sort_keys=True,
        ).encode()
    ).hexdigest()
    counts = state["action_counts"]
    counts[key] = counts.get(key, 0) + 1
    if len(counts) > 100:
        del counts[next(iter(counts))]
    if counts[key] >= 3 or state["stagnant"] >= 4:
        raise ValueError("Stagnation: repeated action without new evidence; choose a different observed route")


def context(state):
    return {
        "specification": state["specification"],
        "active_subtask": state["active_subtask"],
        "subtasks": [
            {k: n[k] for k in ("id", "description", "kind", "dependencies", "status", "outcome")}
            for n in state["plan"]["subtasks"]
        ],
        "replanning": state["replans"][-3:],
    }
