# Autonomous skill acquisition scaffold

Status: versioned declarative candidate contracts and fixture-review eligibility. No acquisition hooks, executable skills, registry persistence or automatic activation.

## Boundaries
- Begin with authorized data processing skills: extraction, normalization, deduplication, citation verification and report composition on already-authorized evidence.
- A verified task may suggest a parameterized candidate with inputs, provenance, prerequisites and completion criteria. No generated executable code, browser scripts, new network privileges or self-modifying behavior.
- Validate candidates in controlled fixtures before human review; bind validation to exact content digest, workspace and version in the future persistence implementation.
- Keep candidates, reviewed versions and retired versions separate; record approval, rollback and provenance. Skill reuse cannot override the current user objective, access scope, budget or evidence checks.
- The illustrative review gate checks version and fixture outcomes only; it is not a production approval mechanism.

## Next implementation
Add a typed schema for parameters and outputs, versioned workspace-scoped registry, content hashing, offline fixture runner, explicit review workflow and opt-in integration with existing extraction. Measure correctness and efficiency against the current implementation before activation.
