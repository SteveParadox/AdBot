# Adbot task planning upgrade

> Update: bounded deterministic dataset queries, shared provider quotas, structured failure diagnostics and additional database offloading are now implemented. See [current reliability guide](../automation/RELIABILITY.md) for supported query grammar, configuration and remaining limits. The measurements below describe the earlier planning implementation.


## Architecture and scope

The existing FastAPI task API creates an immutable Job snapshot. SQL leases fence worker writes; the asyncio browser runner owns its context, tabs and actions. ModelClient provides structured JSON transport, conservative token reservation, deadlines and configured provider fallback. Observer combines semantic DOM, accessibility, visible text and screenshots. Controller checks live targets, domains, methods and authorization. AgentTask memory and AgentStep records provide durable execution history. The existing extraction service validates records and the exporter creates bounded, version-checked files.

The original agent had evidence-backed final verification and bounded recovery, but no explicit task specification, dependency graph or visible subtask progress. Observation element identifiers were reused across unrelated page states. Recovery after an input exception did not distinguish predispatch failure from an uncertain external write.

Changes preserve the existing queue, cancellation, priorities, 500-step ceiling, egress policy, workspace boundaries, extraction service, provider preferences and encrypted session controls. No deployment, live-provider benchmark or production data migration was performed. Earlier uncommitted concurrency/extraction changes and unrelated files remain in place.

## Implemented contracts and execution

`backend/app/agent/planning.py` adds validated Intent, Ambiguity, Subtask and TaskPlan contracts. The specification preserves the literal objective, instruction clauses, explicit constraint fragments, success criteria, domain scope and separately authorized capabilities. A source hash detects drift during checkpoint recovery. Explicit output format can disambiguate CSV/JSON. A deterministic preview is available before model execution.

Simple research tasks use conservative research → collect → verify phases without an extra model call. Complex requests receive one structured decomposition call using the actual initial page. Validation rejects changed objectives, omitted constraints, invented progress/evidence/outcomes, duplicate or unknown IDs, cycles, missing phases, dependency bypass and excessive budgets. Hierarchy and execution dependencies are independently validated. The model may describe meaningful task-specific subtasks, entities, conditional constraints, optional outcomes and ambiguities; these descriptions never grant tool permissions. An export without a named format defaults to JSON with a visible disclosure. Conflicting literal and selected formats require clarification and cannot produce a completion claim.

The runner evaluates dependencies against observed checkpoints after actions. Research requires a current page; collection requires exact source evidence; dataset work requires validated captured records; export requires an actual artifact. These checkpoints are explicitly provisional. Completion still requires separate structured verification of the supplied criteria **and explicit constraints**, valid evidence references, all required plan nodes, and an existing nonempty artifact when requested. For artifact tasks, the verifier receives the entire exported record scope alongside source evidence; a sample is never presented as verification of all records. Changed/missing records or a record set exceeding the semantic context budget cause refusal. This is a model-assisted semantic check, not a mathematical guarantee that arbitrary natural-language claims are correct.

`EXTRACT_DATASET` and `EXPORT_DATASET` reuse the established extraction and export implementations. An export requires an owned dataset configured for the target. Durable record ID/content-hash scope prevents inclusion of unrelated historical records and survives another job reobserving unchanged records. Changed, removed, partial or invalid records prevent a complete-export claim. Scoped exports are bounded to 10,000 observed records; exceeding the bound marks capture truncated. CSV formula protection, download ownership, lease fencing, cancellation, pause and existing size/TTL limits remain in force. Browser download permission controls remote downloads; producing the explicitly requested server-side dataset artifact uses the export tool.

Each failure gets a deterministic classification. Recoverable failures insert a bounded fresh-observation node ahead of the affected task, retaining completed work and original constraints. Retry counts, per-task action budgets, 20 recovery events/nodes and global limits prevent endless replanning. Authorization failures block the affected subtask. Terminal failures stop execution. Repeated actions on unchanged observations trigger stagnation recovery. Existing transport backoff handles provider retries without adding blind browser input retries.

The interaction engine records whether native input dispatch began after actionability trials. An exception after a click, type or keyboard input blocks the subtask and fails the task for inspection instead of replaying a possibly completed external write. Ordinary-link fallback remains available only after a failed click trial that dispatched no input. Existing worker crash/expired-lease protection remains in place. Successful native input alone does not establish goal completion.

## Memory and observations

Working context includes a compact active plan, recent failures/actions, current observations and evidence. The full plan, source contract, scoped record hashes, statuses and recovery history survive in existing JSON checkpoints; SQL retains full per-step observations. Historical hints remain workspace/website scoped and explicitly untrusted until rechecked. The prompt compactor now clips the actual `session_memory` field; it retains the immutable specification and refuses oversized requests rather than dropping constraints. Existing limits bound evidence, actions and history.

Element IDs include a semantic page/tab fingerprint. A target from a changed page or another tab cannot silently resolve to a new element with the same numeric index. Fingerprints ignore the derived IDs, avoiding false progress. Semantic locators and live property checks still run before dispatch.

## API and dashboard

- `POST /api/agent/preview`: existing TaskInput shape; owner-checked deterministic specification and initial plan, no model or browser side effects.
- TaskInput adds optional `dataset_id` and `output_format` (`answer`, `json`, `csv`). Missing fields retain legacy task behavior and idempotency hashes.
- Decision adds optional `subtask_id` and the two dataset tools. Existing action validation and execution controls remain authoritative.
- Task responses add `planning` and elapsed/time/token `budget` data. Results may include an owned artifact download endpoint.
- AgentPanel adds a preview, owned target dataset selector, explicit output format, dependency/status/action-budget viewer, actual replanning history and authenticated artifact download. Editing the form invalidates an earlier preview. AgentPlan explains provisional checkpoints and separates them from final verification. Existing evidence, review controls and live action timeline remain available.

No additional database migration is needed for this upgrade; it uses existing JSON fields and the extraction tables already present in this workspace. Existing extraction migration prerequisites still apply when setting up a fresh database.

## Reproducible measurements

Run `.venv\Scripts\python.exe scripts/benchmark_agent.py` from the repository root with ports 8765/8766 available. It starts isolated local fixture servers, temporary SQLite and a real Chromium worker. The model is a deterministic semantic test double, not Groq/Qwen or a live language model. Provider secrets and the real database are not used.

| Metric | Before | After |
|---|---:|---:|
| Verified local goal completion | Yes | Yes |
| Browser steps | 3 | 3 |
| Model calls | 4 | 4 |
| Fixture-reported tokens | 3,200 | 3,200 |
| Failed actions | 0 | 0 |
| Saved dependency plan | No | Yes |
| Elapsed seconds | 6.425 | 6.671 |

Raw measurements: [BASELINE.json](BASELINE.json), [POST.json](POST.json). These report the single baseline and final-code post sample, with other verification activity present during the post run. An earlier post sample took 5.767s; the final sample took 6.671s, slightly longer than baseline. These timings establish neither acceleration nor a statistically reliable latency regression. There is no measured change in completion rate, action count or token use on this easy goal. The demonstrated improvement is durable dependency/progress tracking without another model call for this case. Complex goals intentionally add a planning request and may increase tokens/latency. No interpretation-accuracy, recovery-rate or live-model improvement percentage is claimed.

## Verification and post-implementation audit

Executed results are recorded in [VERIFICATION.md](VERIFICATION.md). Confirmed integration bugs fixed during this work include dataset-tool fallthrough, historical-record leakage in goal-specific exports, concurrent last-job reassignment losing export scope, regenerated element indexes accepting stale targets, compaction missing the session-memory field, and ambiguous-input recovery replay risk.

## Operational use and remaining limits

1. Configure an authorized website and an owned extraction schema/dataset for structured output. Select the dataset and requested format in AI Agent. Preview the literal requirements before starting; model decomposition appears once the worker observes the site.
2. Inspect dependencies, warnings. A checkpoint means observed progress; the final result requires verification. Blocked/failed tasks retain evidence, unresolved nodes and recovery history.
3. Resolve critical ambiguity before a consequential action. Conflicting artifact formats require an explicit format selection or a new clarified task. A review answer does not rewrite immutable original permissions or explicit prohibitions.
4. If a write has an uncertain outcome, inspect the external system before starting another task. Do not treat the failed task as proof that nothing happened.
5. Download artifacts with the authenticated dashboard control before the configured TTL expires. A dataset modified incompatibly during the task causes export refusal, requiring reobservation or a new isolated run.

Groq remains the configured primary provider; Qwen remains the configured local fallback. This work does not rewrite `.env`, credentials, provider preferences or production sessions.

The implementation is integrated and locally verified, with conditional readiness for authorized deployments after the existing operational gates. It is not evidence of reliable autonomous handling of every complex natural-language task. Constraint fragments are conservative lexical extraction plus a model interpretation; ambiguous/conditional language may require user input. Research/collection nodes are provisional checkpoints and do not each receive an independent model verifier. Generic schema extraction does not automatically compile arbitrary natural-language filters, ranking, top-N or sorting into a dataset query: configure appropriate selectors/normalization or inspect the output; do not assume artifact semantics beyond tested cases. Final artifact verification includes all scoped record data, bounded to half the configured model request character limit to leave room for the immutable task and evidence; larger agent artifacts cannot be reported complete and should use smaller tasks or the separate dataset export interface. Scalable semantic verification of large exports and a representative live-provider evaluation corpus remain future evaluation work. Large immutable requests can fail the existing prompt-size/token budget. Repeatedly changed shared datasets may require an isolated rerun. Same-browser actions remain serialized; the existing worker system provides concurrency across independent jobs.

No automatic engine fallback is enabled; identity/session-sensitive retries continue using the approved snapshot. Provider-wide RPM/TPM quotas, deployment-specific load/security review, and inherited synchronous database hot paths remain operational considerations from the concurrency audit. Windows/Python 3.11 subprocess finalizer and current TestClient dependency warnings are not a guarantee about production on the supported deployment runtime. Restart/redeploy decisions are left to the operator; running user services were not terminated or reconfigured.
