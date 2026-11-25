# Implementation and coverage

| Capability | Adbot baseline | Research branch |
| --- | --- | --- |
| Natural-language query without a website | Site ID and seed URL required | Authenticated research query with no site ID |
| Current, technical, academic and local intent | Website-oriented planning | Rule-based routing, mode override and contextual search |
| Search provider discovery | Existing search inside the registered browser target | SearXNG, Brave, Tavily, Exa and Serper adapters |
| Query decomposition and ranking | Site navigation plan | Bounded refinements, reciprocal rank fusion, lexical relevance and domain diversity |
| Cross-domain retrieval | Explicit registered allowlist | Independent public DNS policy, robots, HTTP caching and optional Chromium rendering |
| Evidence | Website observations and extracted quotes | Per-source excerpts, metadata and product facts with hashed provenance |
| Citation and semantic verification | Agent goal verification | Typed proposals, independent model support pass and deterministic citation validation |
| Shopping | Site-specific extraction schemas | JSON-LD offers, variants, market hints, price and stock checks |
| Follow-ups | Website-scoped learned workflow patterns | Tenant-scoped conversations with previous user questions and source revalidation |
| Runtime | SQL leases, worker, Redis wakeups and site limits | Shared runtime plus per-mode public research budgets |
| Events | Job and workspace progress | Replayable research progress and durable answer segments |
| UI | Agent workspace and documentation | Responsive `/research`, clickable citations, shopping table, Stop and Retry |
| Data lifecycle | Job retention and tenant ownership | Conversation deletion, research retention and bounded caches |

## Code map

- `backend/app/research/contracts.py` defines the mode, intent and model response contracts.
- `search.py` normalizes search APIs and applies provider health, priority, usage and caching.
- `policy.py` and `retrieval.py` enforce public-only retrieval and extract main text, metadata and shopping offers.
- `evidence.py` maps quotations and structured facts, validates references and preserves retailer variants.
- `service.py` coordinates the research pipeline. `runner.py` and `api.py` integrate with the durable worker and authenticated API.
- `backend/alembic/versions/731d00000001_web_research.py` adds the research tables and job scope check. The earlier SQLite downgrade handles the reflected foreign key created during the new migration's table rebuild.
- `frontend/src/Research.tsx` and `research.css` implement the workspace. Existing routes expose it through navigation and the documentation system.

## Example conversation

1. Ask “Find affordable laptops for AI engineering under ₦1.5 million in Nigeria” in Shopping mode.
2. Inspect the product comparison and expand sources to see the retailer's offer, variant, currency and retrieval timestamp.
3. Ask “Which of those options is cheapest?” or “Search other Nigerian retailers”. The engine retains the preceding topic and country and can reuse recently checked sources.
4. For a material claim, switch to Fact Check and ask for more independent evidence.

An answer using Current Information, Shopping or Fact Check may be marked partial when sources are missing, reports conflict, or the checked evidence covers only part of the request.


## Evidence-driven Deep Research

Deep mode now records the original objective and up to four distinct model-planned
subquestions. Each subquestion has a stable task-local ID, targeted-query count,
coverage status (missing, partial, covered or conflicting), and supporting evidence IDs.
The original objective is retained so a narrow model-generated decomposition cannot
silently replace the user's question.

After each retrieval round, the engine selects a bounded, relevance-prioritized
evidence sample and requests a separate structured coverage assessment. It rejects
duplicate assessments, invented or unoffered evidence IDs, and conflict assessments
without evidence from two independent domain groups. Uncovered and disputed
subquestions drive subsequent search queries; previously attempted queries are not
repeated. Source counts alone cannot stop deep research. Early completion requires
coverage of every subquestion and evidence from at least two domain groups.
Existing round, page, provider, browser, token and time limits remain in force,
with two model calls reserved for synthesis and verification where possible.

The final task result persists `research_plan` and `coverage_rounds` with existing
evidence and claims. Each plan row includes `used_in_answer`, which indicates that
at least one evidence ID from a covered subquestion appears in a verified claim.
The research workspace displays this coverage and missing or conflicting topics.
If a subquestion remains uncovered or its evidence is not used in the verified
answer, the task is marked partial even when many sources were collected.
Coverage assessments are model judgments, and shared evidence is not proof that
every aspect of a subquestion appears in the final prose. This is not an
independent semantic guarantee of answer completeness.

Quick Search and the other modes retain their existing planning and stopping
behavior. Deep research plans persist at task completion, not as restartable
per-round checkpoints. Long-form synthesis and broader evidence batching are
separate follow-up work. The focused regression suite is
`python -m pytest -q tests/test_research_gaps.py` from the backend directory;
execution on the full deployment and live providers remains pending.


## Bounded semantic source navigation

With `ADBOT_RESEARCH_BROWSER_ENABLED=true`, Shopping, Technical, Fact Check
and Deep modes can follow relevant links observed in public article/main
landmarks. Static HTML links use the lightweight extractor; rendered pages
reuse the existing agent's semantic DOM metadata for visible, actionable
anchors and their accessible-label fallback. The worker ranks the observed
labels and paths against the research objective. It follows at most two
links per retrieval round, one level deep, within the existing page,
browser, deadline and cancellation budgets. Unused reserved page slots
remain available to ordinary search candidates. Quick Search is unchanged.

Each observed destination is retrieved independently through the existing
credential-free HTTP/browser pipeline; its evidence is cited against its
own URL, not the parent page. Source metadata records the discovery parent
and link label. Research progress includes a navigation event and metrics
include observed link candidates and attempts.

Shopping pages lacking structured offers now qualify for browser rendering
even when their introductory text exceeds 200 characters. Browser attempts
remain opt-in, sandboxed, and capped. The existing browser process is reused
within the task and each render gets a fresh isolated context.

Navigation deliberately does not invoke the general-purpose agent action
controller, click buttons, submit forms, enter text, use authenticated sessions
or activate ads. Observed links must be same-origin; commercial-action and
sponsored markers, credential-bearing and ambiguous paths, arbitrary query
parameters and unsafe destinations are excluded. Only a single bounded
numeric pagination parameter is accepted. Every redirect and cached
destination is checked again, with existing robots, DNS, egress, content-type
and request limits preserved. This is a conservative filter, not proof that
every website implements GET without side effects. Site policies still apply.

This implementation does not support JavaScript-only pagination buttons,
interactive filters, multi-hop crawling, cross-origin link traversal, or
arbitrary browser actions. No new external dependency or database migration
is required. Focused regression cases were added to test_research.py but
execution and live-site validation are pending.


## Requirement-aware shopping and scoped product fallback

Shopping first consumes bounded retailer Product/Offer JSON-LD. When it contains
no usable priced offer, the extractor looks for explicit Product microdata,
product detail/card scopes, or a single product page identified by metadata
or product identifiers. It accepts locally scoped visible-price observations,
labeled specification rows and identity fields; ambiguous or unpriced scopes,
installments, crossed-out prices and unsupported currencies are not inferred.
Static visibility checks are conservative HTML heuristics, not a full CSS
visibility engine. Dynamic rendering remains optional and budgeted.

Each offer retains the source URL, evidence ID, extraction method, condition,
observed specifications and currency. Matching identifiers (checksum-valid
GTIN or brand and manufacturer part number), known equal condition and equal
observed configuration permit cross-retailer grouping; retailer-specific SKUs
and title similarity alone do not establish equivalent products. Offers remain
separate and comparisons count distinct retailer domains within one currency.

Ranking checks explicit supported memory, storage, GPU, category and condition
requirements, and a separately parsed monetary budget. Unestablished
specifications and cross-currency budgets remain unknown. The AI engineering
RAM/VRAM score is a transparent heuristic, not a benchmark or a guarantee.
The worker ranks offers before synthesis, includes bounded assessments linked
to supplied evidence IDs, and marks shopping results partial if no priced
offer meets the observed requirements and budget. The interface displays
requirement fit, condition, price, extraction method and comparison counts.

No new external dependencies or database migrations are needed. This change
does not add a live FX service, image loading, review-text sentiment analysis,
general-purpose semantic product matching or guaranteed checkout pricing.
The regression suite is `python -m pytest -q tests/test_research_shopping.py`
from the backend directory. Runtime verification is pending.
