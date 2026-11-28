"""Versioned, bounded research progress snapshots.

Job execution_state is authoritative under the worker lease. Counters are
loaded independently from ResearchTask.usage and are never restored here.
"""
import json
from collections import Counter

from ..config import settings
from .gaps import GapPlan, Subquestion
from .contracts import Mode
from .objectives import comparison_request
from .policy import PublicPolicy
from .ranking import Independence
from .shared_cache import digest

VERSION = 4
MAX_CHECKPOINT_BYTES = 8 * 1024 * 1024
COUNTERS = ("provider_requests", "provider_failures", "provider_ms", "provider_rate_limits")


def policy_stamp():
    cfg = settings()
    return digest([VERSION, cfg.research_excluded_domains, cfg.user_agent_default,
                   cfg.research_browser_enabled])


def capture(engine):
    return {
        "version": VERSION, "policy": policy_stamp(),
        "effective_mode": engine.mode.value, "route_done": engine.route_done, "schedule_mode": engine.schedule_mode,
        "recovery_started": engine.recovery_started, "recovery_done": engine.recovery_done,
        "recovery_base_claims": engine.recovery_base_claims, "cross_source_done": engine.cross_source_done,
        "layout": engine.layout, "initial_search": engine.initial_search,
        "next_round": engine.next_round, "search_done": engine.search_done,
        "pending_ranked": engine.pending_ranked, "round_page_limit": engine.round_page_limit,
        "round_page_start": engine.round_page_start,
        "queries": engine.queries, "hits": engine.hits,
        "sources": engine.sources, "evidence": engine.evidence, "products": engine.products,
        "attempted": sorted(engine.attempted), "content_hashes": sorted(engine.content_hashes),
        "independence": {"parents": engine.independence.parents, "domains": engine.independence.domains,
                         "fingerprints": {k: sorted(v) for k, v in engine.independence.fingerprints.items()}},
        "gap_plan": engine.gap_plan.snapshot() if engine.gap_plan else None,
        "coverage_rounds": engine.coverage_rounds, "claims": engine.claims,
        "notes": engine.notes, "quality": engine.result_quality, "model_failed": engine.model_failed,
        "synthesis_state": engine.synthesis_state, "synthesis_done": engine.synthesis_done,
        "metrics": engine.metrics,
    }


def freeze(engine):
    # Round-trip to detach mutable state before handing it to the IO thread.
    try:
        raw = json.dumps(capture(engine), ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    except (ValueError, TypeError, OverflowError):
        return None
    if len(raw.encode("ascii")) > MAX_CHECKPOINT_BYTES:
        return None
    return json.loads(raw)


def restore(engine, state):
    """Restore only server-generated, matching-version/policy state.

    Reject invalid state before mutating the engine. A policy change discards
    cached progress, never the already-charged durable task usage.
    """
    if not isinstance(state, dict) or state.get("version") != VERSION or state.get("policy") != policy_stamp():
        return False
    try:
        if not 0 <= state["next_round"] <= engine.budget.rounds:
            return False
        if len(state["sources"]) > engine.budget.pages or len(state["attempted"]) > engine.budget.pages * 3:
            return False
        if any(key != source["id"] or PublicPolicy().check(source["url"]) != source["url"]
               for key, source in state["sources"].items()):
            return False
        if any(key != row["id"] or row["source_id"] not in state["sources"]
               for key, row in state["evidence"].items()):
            return False
        if any(p["evidence_id"] not in state["evidence"] for p in state["products"]):
            return False
        progress = state["synthesis_state"] or {}
        if any(row["id"] not in state["evidence"] for row in progress.get("presented", [])):
            return False
        if any(i not in state["evidence"] for c in state["claims"] + progress.get("accepted", []) + state["recovery_base_claims"] for i in c["evidence"]):
            return False
        independence = Independence()
        index = state["independence"]
        independence.parents = dict(index["parents"])
        independence.domains = dict(index["domains"])
        independence.fingerprints = {k: frozenset(v) for k, v in index["fingerprints"].items()}
        if any(len(v) > 1024 for v in independence.fingerprints.values()):
            return False
        plan = None
        if state["gap_plan"]:
            plan = GapPlan("")
            plan.questions = [Subquestion(**row) for row in state["gap_plan"]]
            if len(plan.questions) > 5 or any(i not in state["evidence"] for q in plan.questions for i in q.evidence):
                return False
        metrics = dict(state["metrics"])
        for key in COUNTERS:
            metrics[key] = Counter(metrics.get(key, {}))
        # Keep the lease-fenced usage count, including operations dispatched
        # after the last checkpoint and ambiguous transport outcomes.
        metrics["model_calls"] = engine.metrics["model_calls"]
        mode = Mode(state["effective_mode"])
        if mode == Mode.AUTO or (engine.question.mode != Mode.AUTO and mode != engine.question.mode):
            return False
        if mode != Mode.DIRECT and not engine.budget.requests:
            return False
        restored = {
            "mode": mode, "route_done": state["route_done"], "schedule_mode": state["schedule_mode"],
            "recovery_started": state["recovery_started"], "recovery_done": state["recovery_done"],
            "recovery_base_claims": state["recovery_base_claims"], "cross_source_done": state["cross_source_done"],
            "layout": state["layout"], "initial_search": state["initial_search"],
            "coverage_required": mode == Mode.DEEP or (mode == Mode.TECHNICAL and comparison_request(engine.question.question)),
            "next_round": state["next_round"], "search_done": state["search_done"],
            "pending_ranked": state["pending_ranked"], "round_page_limit": state["round_page_limit"],
            "round_page_start": state["round_page_start"], "queries": state["queries"], "hits": state["hits"],
            "sources": state["sources"], "evidence": state["evidence"], "products": state["products"],
            "attempted": set(state["attempted"]), "content_hashes": set(state["content_hashes"]),
            "independence": independence, "gap_plan": plan, "coverage_rounds": state["coverage_rounds"],
            "claims": state["claims"], "notes": state["notes"], "result_quality": state["quality"],
            "model_failed": state["model_failed"], "synthesis_state": state["synthesis_state"],
            "synthesis_done": state["synthesis_done"],
        }
    except (KeyError, TypeError, ValueError, AttributeError):
        return False
    for key, value in restored.items():
        setattr(engine, key, value)
    engine.metrics.update(metrics)
    return True
