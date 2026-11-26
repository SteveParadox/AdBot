# Research pipeline verification

The recorded comparison job `77e2c61d-f57c-4f39-82fd-0e1d684943bf` used 42,804 tokens in approximately 195 seconds. It reached the comparison article on its second action and accumulated zero evidence. The subsequent steps include repeated clicks and scrolls, blocked repeated actions, and two failures during request compaction.

## Corrections

- Research reads visible DOM blocks on the initial page and after successful browser actions. It ranks the blocks against the task and preserves exact rendered excerpts, their source URLs and step IDs in the existing durable job evidence store. Decision context carries only bounded excerpts and controls.
- Research checkpoints require evidence. Subject and criterion coverage guide navigation and feed separate verification checks. A subject check requires a citation associated with that subject. Qualified partial results return supported excerpts and identify missing criteria.
- Destination history and evidence progress detect repeated research actions independently of visual changes. The runner reuses the observation captured after an action. Research visits skip crawl-wide link discovery and automatic scrolling, and use DOM readiness in place of network idle while respecting any configured wait selector.
- Provider preflight estimates the full serialized request, including schema, provider framing and image allowance, and reserves output separately. It rebuilds the request for known context limits or a detected provider rejection. An irreducible context failure stops decision retries. Exact verification criteria and cited evidence remain in verification requests.

## Measurements

| Check | Result |
| --- | --- |
| Two-source browser comparison with simulated model responses | Completed with two durable source excerpts and one model decision in 2.19 seconds |
| Missing-source browser comparison | Blocked a repeat visit and published one verified excerpt with missing criteria in 2.48 seconds |
| Mock provider context rejection | Retried on the same provider with estimated input reduced from 13,164 to 5,597 tokens and 800 tokens reserved for output |
| Targeted regression suite | 102 backend tests passed, followed by six focused checks and three final browser and entity-coverage checks |
| Dashboard | 70 frontend tests passed and the production build succeeded |

Fixture timings measure local browser and worker execution with simulated model responses. Provider estimates include request overhead and are estimates rather than measured billing tokens.

## Authorized live replay

Intermediate replays exposed two additional defects. Model decisions tried to use unavailable or completed phases, and a blocked destination could create a single-step recovery phase that required evidence before permitting another navigation. Research now keeps the original phase and uses the existing job and recovery limits. Previously observed destinations are removed from the model's actionable links when they have yielded no new evidence.

The final replay, `cbcc18c5-589b-4962-a60a-c02cfead98eb`, completed the original Notion AI and Obsidian comparison in **24.38 seconds with 7,040 tokens across two provider calls**. It persisted three article excerpts and published two that supported the comparison and both subjects. The worker recorded a click, navigation and verification. Compared with the failed baseline, this run used about 84% fewer tokens and took about 87% less time. These figures describe a single authorized replay through an isolated local worker and the configured live providers.
