"""Bounded multi-batch synthesis and deterministic verified report assembly."""

from dataclasses import dataclass

from ..agent.model import ModelError, bounded_request_text
from .contracts import Mode, Summary, Verification
from .evidence import citation_markdown
from .search import terms


@dataclass(frozen=True)
class SynthesisProfile:
    batches: int
    rows: int
    quote_chars: int
    claims_per_batch: int


def profile_for(mode, output_tokens):
    # A small model gets fewer claims per response, not an oversized schema
    # response that the transport will truncate. Deep can use several calls.
    rows, batches, quote_chars, ceiling = {
        Mode.QUICK: (12, 1, 550, 8),
        Mode.DEEP: (24, 3, 1400, 8),
        Mode.TECHNICAL: (18, 2, 1000, 6),
        Mode.FACT_CHECK: (18, 2, 1000, 6),
        Mode.SHOPPING: (18, 2, 1400, 6),
    }[Mode(mode)]
    return SynthesisProfile(batches, rows, quote_chars, min(ceiling, max(1, output_tokens // 150)))


def evidence_rows(records, sources, objective, preferred, quote_chars):
    """Keep evidence IDs and exact displayed text; deduplicate copied passages."""
    words = terms(objective)
    ordered = sorted(records, key=lambda r: (
        r["id"] not in preferred, -len(words & terms(r["quote"])), r["id"],
    ))
    groups = {}
    seen = set()
    for record in ordered:
        # Do not truncate structured observations into invalid or misleading
        # fragments. Very large observations remain in the evidence panel.
        quote = record["quote"]
        if record["kind"] == "structured" and len(quote) > quote_chars:
            continue
        quote = quote[:quote_chars]
        key = quote.casefold()
        if key in seen:
            continue
        seen.add(key)
        source = sources[record["source_id"]]["independence_group"]
        groups.setdefault(source, []).append({
            "id": record["id"], "source": source, "quote": quote,
            "date": record["published_at"], "kind": record["kind"],
            **({"page": record["page"]} if record.get("page") else {}),
        })
    # Interleave domains so the first batch does not consist of a single site.
    return [rows[i] for i in range(max((len(v) for v in groups.values()), default=0))
            for rows in groups.values() if i < len(rows)]


def fits(prompt, kind, payload, schema, max_chars):
    try:
        bounded_request_text(prompt, kind, payload, schema, max_chars)
        return True
    except ModelError:
        return False


def batch_rows(rows, payload_for, prompt, max_chars, max_rows, claims_limit, verify_prompt, verify_context_for):
    """Pack one batch using actual serialized request size, including schema.

    Reserve verification space for a conservative full-sized claim response.
    """
    selected = []
    skipped = []
    for row in rows:
        if len(selected) >= max_rows:
            skipped.append(row)
            continue
        candidate = [*selected, row]
        verify_candidates = [
            {"text": "\\" * 520, "kind": "recommendation",
             "evidence": [r["id"] for r in candidate[:4]]}
            for _ in range(claims_limit)
        ]
        if (fits(prompt, "research_synthesis", {**payload_for(candidate), "evidence": candidate}, Summary, max_chars)
                and fits(verify_prompt, "research_verify",
                         {**verify_context_for(candidate), "candidates": verify_candidates, "evidence": candidate},
                         Verification, max_chars)):
            selected.append(row)
        else:
            skipped.append(row)
    return selected, skipped


def offered_evidence(rows, records):
    # Verification must validate against exactly what the model saw, not
    # against text cut off by the request budget.
    return {row["id"]: {**records[row["id"]], "quote": row["quote"]} for row in rows}


def unique_claims(claims):
    result = {}
    for claim in claims:
        key = (claim["kind"], " ".join(claim["text"].casefold().split()))
        result.setdefault(key, claim)
    return list(result.values())


def report_markdown(claims, evidence, sources, mode):
    if mode != Mode.DEEP:
        return citation_markdown(claims, evidence, sources)
    sections = (
        ("Key findings", {"fact"}),
        ("Analysis and implications", {"inference"}),
        ("Recommendations", {"recommendation"}),
        ("Disagreements between sources", {"conflict"}),
        ("Retrieved excerpts (not verified conclusions)", {"excerpt"}),
    )
    # Static headings introduce no factual claims. Every paragraph is exactly
    # an accepted claim, rendered with the original evidence-derived citations.
    return "\n\n".join(
        "## " + title + "\n\n" + citation_markdown(selected, evidence, sources)
        for title, kinds in sections
        if (selected := [claim for claim in claims if claim["kind"] in kinds])
    )
