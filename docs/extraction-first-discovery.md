# Extraction-first read-side discovery

The agent separates structural candidate discovery from semantic membership and final verification.

1. Inspect rendered records and links in the authorized observation.
2. For open-ended enumeration, automatically map coherent repeated records with explicit identity fields and descriptions. Existing capture and classification contracts remain mandatory. Ambiguous groups use the normal model-assisted mapping path.
3. Rank candidate links and retain short literal page excerpts rather than discarding page text.
4. Distinguish scroll movement from information gain. After two unchanged scrolls, prefer a relevant unvisited authorized link when one exists.
5. Keep the original model, task, deadline and browser permission checks. Ordinary links can use a policy-checked direct navigation fast path after live target verification. Form actions remain disabled unless authorized.
6. Reserve bounded tokens for finalization, adapt decision output budgets on budget rejection, and retain the full local response schema validation.

The strict directory coverage rules are unchanged: a relevant page or candidate is not proof of exhaustive coverage. Research and directory fallback share the compact observation and exploration helpers; their existing evidence and coverage mechanisms remain authoritative.

## Verification

Run from the backend development environment:
`pytest -q tests/test_extraction_first_discovery.py tests/test_category_enumeration.py tests/test_directory_strategy.py tests/test_research_pipeline.py tests/test_provider_handoff.py tests/test_model_response_contract.py`.

Replay the reported listing task and unrelated authorized-site fixtures. Compare qualified records, source evidence, model calls, tokens, unchanged-scroll count and provider errors. Live provider behavior and semantic relevance require actual replay; the lexical ranking is only a candidate heuristic, not an entailment judgment. No provider-specific schema relaxation is introduced.
