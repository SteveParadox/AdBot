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
