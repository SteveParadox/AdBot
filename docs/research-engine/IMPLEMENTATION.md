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
per-round checkpoints. Long-form synthesis and broader evidence batching are described below. The focused regression suite is
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


## Mode-specific verified answer synthesis

Quick Search retains its single compact synthesis and verification pair.
Deep Research can use up to three synthesis/verification batches; Technical,
Fact Check and Shopping can use up to two. A profile bounds evidence rows per
batch, quote length and claim counts. The per-batch claim ceiling also adapts
to the configured model output token limit. At the default 800 output tokens,
Deep can propose up to five claims per batch (15 total when all three batches
fit); this is a ceiling, not a minimum or a performance guarantee.

Evidence is prioritized by topic relevance and planned subquestion/product
evidence IDs, interleaved across domain groups, and de-duplicated. Each batch
is sized using the existing transport's actual serialized schema, prompt and
payload cap, including a conservative verification envelope. Structured
product observations are not cut into partial JSON. Shopping assessments
are scoped to the exact evidence IDs offered in each batch.

Every proposed claim is verified against the same batch of evidence actually
presented to the model; deterministic verification never relies on omitted
text for numerical corroboration. Accepted findings survive failure of a
later batch. Exact duplicate claims are removed without automatically merging
their citations. A deterministic reducer assembles a structured Deep report
with findings, implications, recommendations, source disagreements and
explicitly labeled excerpts when appropriate. No final free-form model
rewrite can introduce new uncited claims. Model-reported limitations and
unprocessed evidence cause partial quality, and budget exhaustion is
disclosed. Existing provider quotas and durable task call/token accounting
remain authoritative; search time reserves more room for synthesis in
expanded modes.

The completed result exposes synthesis batch and evidence counters in
metrics, along with proposed/verified claims and citation coverage. Coverage
is the proportion of proposals accepted before duplicate removal, not the
fraction of the user's question answered. Independent verification is
model-based; conflicting claims across distinct batches may still require
additional research. This is bounded extractive/claim-based report assembly,
not unlimited prose generation or a global semantic contradiction proof.

No new dependency or migration is required. Focused regression tests:
`python -m pytest -q tests/test_research_synthesis.py` from the backend
directory. Test execution and live-provider/model verification remain pending.


## Public PDF and document research

The HTTP retrieval tier now accepts application/pdf and checks the actual PDF
signature before parsing. The existing public URL, DNS, robots, redirect,
credential, cache and egress rules still apply. HTML and browser subresource
byte limits are unchanged; a PDF response has an 8,000,000-byte cap.

PDF text and ruled tables are extracted by a separate Python process using
pdfplumber 0.11.10. Input and output are bounded, no document-provided actions
or attachments are executed, and the process receives a reduced environment.
Linux sets a 512 MiB virtual-address-space cap, an eight-second CPU soft
limit and nine-second hard limit; a 15-second wall-clock deadline applies
on supported asyncio subprocess platforms. At most one PDF parser runs per
Fetcher. This is resource isolation, not a full OS security sandbox.

Extraction examines the first 40 physical pages, at most 12,000 text
characters per page and 180,000 total, with at most 160 complete ruled-table
rows across the document and a 900,000-byte parser output cap. Tables retain
page, table and row positions, and observed first-row context is distinguished
from the data cells. No header meaning or missing numerical values are
invented. Malformed, encrypted and extraction-restricted PDFs fail closed.
Scanned documents without extractable text need OCR, which is not provided.

Evidence records preserve physical page numbers and normalized text line or
table-row locations. Citations are deterministically generated as source
number plus page, with a #page=N fragment on the stored source URL. The UI
validates these against the matching PDF source and examined page count.
PDF metadata reports pages examined, page count and extraction limits.
Publication dates are not inferred from PDF creation dates or file timestamps.
Incomplete extraction, missing usable PDF text, or parse failure is disclosed
as partial research. Existing plain text and HTML document support is retained.

Run the dedicated regression suite from backend:
`python -m pytest -q tests/test_research_pdf.py`.
The standalone parser was smoke-tested with the locally available pdfplumber
0.11.9 using generated PDFs (text/table extraction, 40-page truncation,
malformed and encrypted inputs). The pinned 0.11.10 environment and full
application/browser integration tests remain to be executed.


## Conversation-local research memory

At enqueue time, the server reads at most 32 completed turns in the authorized
conversation, checking both conversation and job owner. It projects only the
question, answer, product/source references and persisted memory fields.
The resolver selects up to three turns by reference, lexical relevance and
recency. Ordinal product references resolve against the original result order
(up to 20 products); source references support up to 40 sources. A named
entity must match an observed name or title; ambiguous names and invalid
ordinals are disclosed rather than resolved by guessing.

The versioned context stores effective country, freshness and supported
shopping constraints, including currency budget, RAM, VRAM, storage, GPU,
category, condition and workload. Explicit updates replace the corresponding
prior slot; removal and topic reset commands stop inheritance. A market
change drops the inherited monetary budget unless a new one is supplied.
The system separates old user constraints from prior answer text and observed
entity names. Historical answers are untrusted context, not current evidence.
Selected source URLs are checked by the same public retrieval policy and
retrieved again; ordinary caching rules still apply.

A bounded snapshot is saved in the existing job JSON at enqueue. Retry and
lease recovery reuse the snapshot, and new jobs do not reload history at
execution time. Completed results persist versioned memory and a compact
context explanation. The UI numbers product rows and displays the resolved
references, current market, freshness, constraints and ambiguity notices.
No new storage service or database migration is required.

This is deterministic, conversation-scoped memory, not global personal
memory. It does not support unlimited history, semantic embeddings, arbitrary
natural-language coreference or every possible shopping constraint. Old
references outside the window may not resolve, and complex topic changes
or mixed references can remain ambiguous. Run the regression tests in
`tests/test_research_memory.py` and the API retry/isolation case in
`tests/test_research.py`. Runtime validation remains pending.


## Explainable ranking and source independence

Search ranking combines bounded BM25-style term weighting, weighted query
coverage, phrase proximity, reciprocal provider ranks and a penalty for
repeated registrable domains. Government/academic namespace and documentation
path signals are small relevance-gated adjustments, not verified authority.
Publisher-declared bylines, dates and sponsorship markers are observable
signals, not independently verified identities or editorial assessments.
Evidence selection also uses weighted lexical relevance and source signals.

With `ADBOT_RESEARCH_SEMANTIC_RANKING_ENABLED=true`, the first search round
in Deep, Technical or Fact Check mode can request one bounded relevance
assessment from the existing configured model. At most 12 candidates are
offered; the model rates their relationship to the objective on a 0–4 scale.
It is not asked to determine truth or credibility. All candidate indexes
must be present exactly once; invalid responses fall back to deterministic
ranking. The scores have limited influence, unrated candidates remain
neutral, explicit user-supplied URLs retain priority, and existing request,
token, call and time caps apply. Quick and Shopping do not incur the extra
model call. No new model or service dependency is required.

The task-local independence index groups registered domains and substantially
overlapping normalized article text using bounded five-word shingles. Union
operations are transitive and update the groups of already collected sources.
Short common phrases do not cluster entire documents. Exact byte duplicates
continue to use the existing retrieval deduplication. Shopping disables
document-content clustering because identical manufacturer specifications
can legitimately occur at distinct retailers. Independently, sufficiently
long identical claim excerpts cannot establish multiple corroborating
groups; structured retailer evidence is excluded from this excerpt test.
Conflict verification, gap assessment and completion use these conservative
groups. Different groups are only potentially independent, not proof of
distinct editorial ownership. No attribution of original authorship is made.

Source results expose credibility and independence_assessment objects and
the research UI displays the observed signals and possible shared origin.
Task metrics include semantic_rank_attempts, semantic_rank_successes and
shared_origin_sources. These are diagnostics, not accuracy metrics.

Focused tests: `python -m pytest -q tests/test_research_ranking.py`.
Full application and live relevance evaluation remain pending.


## Shared research caches and lease-fenced recovery

The existing Redis connection (`ADBOT_REDIS_URL`) enables a shared,
conversation-scoped query and extracted-document cache when research caching
is enabled. Keys contain hashes of the owner/conversation namespace and
request identity, including provider identity and relevant retrieval policy
configuration. Redis uses bounded JSON records (1.5 MB maximum each),
128 query slots and 64 document slots per conversation, with expiry of at
most one hour. Slot collisions become misses, never mismatched hits. No
pickle, credentials, raw PDF bytes or browser sessions are stored. Redis
failures disable the shared cache for that task and normal retrieval
continues. Without Redis, the bounded process-local caches remain available.
Robots parsing remains process-local. Configure Redis memory limits and
eviction appropriate for the entire deployment; slot limits are per thread,
not a global memory quota.

Document cache hits respect origin freshness, Age, conditional validators,
no-store/private/noarchive and supported Vary headers. Public URL and robots
checks still apply. Browser-rendered shells remain non-cacheable. Deleting
a conversation invalidates its bounded Redis namespace after SQL deletion;
an outage or late stale-worker write can leave inaccessible entries until
TTL expiry. Conversation UUIDs are never reused. Process-local entries on
other workers cannot be synchronously removed, but are scoped to that
conversation and no longer reachable through the API.

The worker checkpoints ranked candidates, completed retrieval batches,
completed research rounds, search completion, and completed synthesis
batches. Each versioned JSON snapshot is limited to 8 MiB and stored in
Job.execution_state under the existing SQL lease fence. Oversized or
unserializable snapshots leave the last valid checkpoint intact. Sources,
evidence, offers, attempted URLs, gap plan, bounded hashed content sketches,
verified synthesis progress and diagnostics are restored. The snapshot is
internal and omitted from public job responses. A changed source policy
invalidates saved progress. Usage counters are never taken from the snapshot:
ResearchTask.usage and the original job deadline remain authoritative.

On lease recovery the replacement worker skips checkpointed provider
searches, attempted pages and completed synthesis batches. Operations
interrupted before their checkpoint may be repeated only within the
remaining charged budget. A crash between retrieval and navigation can
lose transient link candidates. This is at-least-once recovery, not
exactly-once external execution. Terminal completion/failure/cancellation
clears the checkpoint. Explicit user retry creates a new research job and
budget; it does not resume a terminal checkpoint.

No additional dependencies or migrations are needed. Regression tests:
`python -m pytest -q tests/test_research_recovery.py` and
`python -m pytest -q tests/test_research.py -k research_checkpoint`.
Redis-backed multi-worker integration and crash injection remain unexecuted.
