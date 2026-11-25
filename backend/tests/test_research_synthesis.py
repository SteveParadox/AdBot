"""Regression tests for budgeted multi-batch research synthesis."""

import asyncio
import time

from app.config import settings
from app.research.contracts import Mode, Question, Summary, Verification, budget_for
from app.research.evidence import verified_claims
from app.research.service import Research
from app.research.synthesis import (batch_rows, evidence_rows, offered_evidence, profile_for,
                                    report_markdown, unique_claims)


def fixture_records(count=30):
    sources = {
        f"s{i}": {"id": f"s{i}", "independence_group": f"source-{i}.example.org",
                  "url": f"https://source-{i}.example.org/report"}
        for i in range(3)
    }
    evidence = {
        f"e{i:02}": {"id": f"e{i:02}", "source_id": f"s{i % 3}", "kind": "quote",
                    "published_at": None,
                    "quote": f"Battery study finding number {i} is supported by a recorded experiment."}
        for i in range(count)
    }
    return sources, evidence


def test_output_limits_are_mode_specific():
    small = profile_for(Mode.DEEP, 256)
    normal = profile_for(Mode.DEEP, 800)
    large = profile_for(Mode.DEEP, 4000)
    assert small.claims_per_batch == 1
    assert normal.batches == 3 and normal.claims_per_batch * normal.batches > 8
    assert large.claims_per_batch == 8
    assert profile_for(Mode.QUICK, 4000).batches == 1


def test_evidence_rows_diversify_and_do_not_cut_structured_json():
    sources, evidence = fixture_records(6)
    evidence["duplicate"] = {**evidence["e00"], "id": "duplicate"}
    evidence["oversized"] = {**evidence["e00"], "id": "oversized",
                             "kind": "structured", "quote": "x" * 2000}
    rows = evidence_rows(list(evidence.values()), sources, "Battery study", {"e00"}, 550)
    assert len(rows) == 6
    assert rows[0]["id"] == "e00"
    assert len({r["source"] for r in rows[:3]}) == 3
    assert not {"duplicate", "oversized"} & {r["id"] for r in rows}


def test_batch_packing_respects_full_schema_and_payload_budget():
    sources, evidence = fixture_records()
    rows = evidence_rows(list(evidence.values()), sources, "Battery study", set(), 550)
    payload = lambda candidate: {"question": "Battery study", "claim_limit": 4}
    context = lambda candidate: {"question": "Battery study"}
    selected, remaining = batch_rows(rows, payload, "Answer", 18000, 5, 4, "Verify", context)
    assert len(selected) == 5 and len(remaining) == 25
    assert not {r["id"] for r in selected} & {r["id"] for r in remaining}
    selected, remaining = batch_rows(rows, payload, "Answer", 100, 5, 4, "Verify", context)
    assert not selected and remaining == rows


def test_unseen_numeric_evidence_cannot_verify_claim():
    sources, evidence = fixture_records(1)
    evidence["e00"]["quote"] = "The battery improved. " + "x" * 600 + " 99 percent."
    rows = evidence_rows(list(evidence.values()), sources, "battery", set(), 550)
    proposals = Summary(claims=[{"text": "The battery improved by 99 percent.", "kind": "fact",
                                 "evidence": ["e00"]}]).claims
    checked = Verification(checks=[{"claim": 0, "status": "supported", "evidence": ["e00"]}])
    assert not verified_claims(proposals, checked, offered_evidence(rows, evidence), sources)


def test_report_assembly_uses_only_accepted_claims_and_citations():
    sources, evidence = fixture_records(2)
    claim = {"text": "Battery study finding number 0.", "kind": "fact",
             "evidence": ["e00"], "independent_sources": 1}
    second = {"text": "A possible implication needs more work.", "kind": "inference",
              "evidence": ["e01"], "independent_sources": 1}
    claims = unique_claims([claim, claim, second])
    answer = report_markdown(claims, evidence, sources, Mode.DEEP)
    assert len(claims) == 2
    assert "## Key findings" in answer and "## Analysis and implications" in answer
    assert "[1](<https://source-0.example.org/report>)" in answer
    assert "[2](<https://source-1.example.org/report>)" in answer
    assert answer.count("Battery study finding number 0.") == 1


def engine(monkeypatch, count=30):
    cfg = settings()
    monkeypatch.setattr(cfg, "ai_max_output_tokens", 800)
    monkeypatch.setattr(cfg, "ai_max_request_chars", 18000)
    gate = asyncio.Event()
    gate.set()
    events = []

    async def emit(name, message, **details):
        events.append((name, details))

    instance = Research("test-owner", Question(question="Research battery study findings", mode=Mode.DEEP),
                        Mode.DEEP, "deep_research", budget_for(Mode.DEEP),
                        time.monotonic() + 60, [], emit, gate, model=object())
    instance.sources, instance.evidence = fixture_records(count)
    return instance, events


async def test_deep_research_verifies_more_than_eight_claims(monkeypatch):
    instance, events = engine(monkeypatch)
    offered = []

    async def ask(kind, prompt, schema, data, **kwargs):
        instance.metrics["model_calls"] += 1
        if kind == "research_synthesis":
            offered.append({row["id"] for row in data["evidence"]})
            return Summary(claims=[
                {"text": row["quote"], "kind": "fact", "evidence": [row["id"]]}
                for row in data["evidence"][:4]
            ])
        assert kind == "research_verify"
        assert {row["id"] for row in data["evidence"]} == offered[-1]
        return Verification(checks=[
            {"claim": i, "status": "supported", "evidence": claim["evidence"]}
            for i, claim in enumerate(data["candidates"])
        ])

    monkeypatch.setattr(instance, "ask", ask)
    await instance.synthesize()
    assert len(instance.claims) == 12
    assert instance.metrics["synthesis_batches"] == 3
    assert instance.metrics["model_calls"] == 6
    assert instance.metrics["citation_coverage"] == 1.0
    assert len(set.union(*offered)) == sum(map(len, offered))
    assert sum(name == "verifying" for name, _ in events) == 3


async def test_failed_batch_preserves_verified_claims_and_marks_partial(monkeypatch):
    instance, _ = engine(monkeypatch, 12)
    batches = 0

    async def ask(kind, prompt, schema, data, **kwargs):
        nonlocal batches
        instance.metrics["model_calls"] += 1
        if kind == "research_synthesis":
            batches += 1
            row = data["evidence"][0]
            return Summary(claims=[{"text": row["quote"], "kind": "fact", "evidence": [row["id"]]}])
        if batches == 2:
            return None
        return Verification(checks=[{"claim": 0, "status": "supported",
                                     "evidence": data["candidates"][0]["evidence"]}])

    monkeypatch.setattr(instance, "ask", ask)
    await instance.synthesize()
    assert len(instance.claims) == 2
    assert instance.result_quality == "partial"
    assert instance.metrics["claims_verified"] == 2


async def test_no_remaining_model_pair_returns_only_labeled_excerpts(monkeypatch):
    instance, _ = engine(monkeypatch)
    instance.metrics["model_calls"] = instance.budget.calls - 1

    async def unexpected(*args, **kwargs):
        raise AssertionError("No model call pair remains")

    monkeypatch.setattr(instance, "ask", unexpected)
    await instance.synthesize()
    assert instance.result_quality == "partial"
    assert instance.claims and all(c["kind"] == "excerpt" for c in instance.claims)
    assert instance.metrics["claims_verified"] == 0
