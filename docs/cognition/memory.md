# Intelligent long-term memory scaffold

Status: contracts, filtering and an opt-in process-local reference store; not wired to the agent.

## Boundaries
- Keep existing agent memory unchanged. The future adapter wraps the existing workspace and website scope; historical facts never replace fresh verification.
- Add PostgreSQL migrations and a SQLite-compatible fallback only in a subsequent implementation PR. Consider optional pgvector and a local embedding provider; do not make either a startup dependency.
- Separate episodic, semantic, procedural, spatial, temporal and reflective records. Working memory remains with the current task.
- Proposed retrieval: authorized candidate lookup, semantic/lexical ranking, scope and expiration validation, bounded injection as historical hints.
- Require provenance and evidence IDs. Consolidation must preserve source references, handle contradictions and support deletion/retention; avoid retaining secrets, credentials or raw session state.
- Embedding and store protocols are interfaces, not concrete implementations. Scope validation is defense in depth, not authentication.

## Next implementation
Implement authenticated storage adapters and migrations, retention/deletion, embedding versioning, retrieval evaluation, and opt-in runner integration. Test isolation, stale evidence, unsupported providers and existing memory compatibility. No cross-workspace sharing.

## Additional reference implementation

`ResearchMemoryStore` implements scoped lookup, deterministic lexical matching, expiration, idempotent inserts, conflicting-identity rejection and bounded capacity for caller-supplied redacted research summaries. This is not a persistent or authenticated store. Callers must enforce authorization and verify provenance. See `test_cognition_memory_retention.py`. Design reference: https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/langgraph/store/base/__init__.py.
