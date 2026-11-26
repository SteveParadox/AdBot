import time
import asyncio
import json
import re
from asyncio import Lock
from dataclasses import asdict
from urllib.parse import urlsplit

from playwright.async_api import Error as BrowserError

from sqlalchemy import func, select

from ..browser import BrowserCrashed, Runner
from ..config import settings
from ..concurrency import database_call
from ..db import AgentStep, AgentTask, emit, transaction
from ..jobs import owned_job
from .contracts import Decision, Verification
from .controller import Controller
from .directory import DirectoryCollection, directory_link, directory_result, matching_collection
from .routing import (ExecutionRoute, RouteAssessment, assessed_entity, collection_kinds, exhaustive_request, inventory_route,
                      select_route, task_text_only, words)
from .memory import action_key, decrypt_session, encrypt_session, relevant_memories, semantic_action_key
from .model import ModelDeadlineExceeded, ModelBudgetExceeded, ModelClient, ModelContextExceeded, ModelError, ModelProvidersUnavailable
from .structure import add_capture, classification_request
from .discovery import (
    MAX_SEARCH_ATTEMPTS, automatic_capture, compact_page, frontier_candidate, navigation_candidate, relevant_group_signatures,
    search_attempt_key, search_candidate, search_control, search_query_allowed, task_token_allowance, unchanged_scrolls, update_frontier,
)
from .research import (
    capture_evidence, comparison_dimensions, comparison_entities, coverage, destination_key, guard_navigation, ranked_chunks,
    terms,
)


class AgentRunner(Runner):
    def __init__(self, job_id, token):
        super().__init__(job_id, token)
        self.model = ModelClient()
        self.model.on_provider_event = self.report_provider_failure
        self.classification_account_lock = Lock()
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            task = session.get(AgentTask, self.id)
            self.options = task.options
            self.deadline = job.started_at + self.cfg["max_duration_seconds"]
            self.objective, self.mode = task.objective, task.mode
            self.memory = {
                "visited_urls": [],
                "evidence": [],
                "failures": [],
                "answers": [],
                "recent_actions": [],
                **(task.memory or {}),
            }
            self.restored_session = (
                decrypt_session(task.encrypted_session) if self.options["session_persistence"] else None
            )
            self.hints = (
                relevant_memories(session, job.owner, job.website_id, self.objective)
                if self.options["memory_enabled"]
                else []
            )

    def context_options(self):
        headers = {"X-AdBot-Automation": "true", "X-AdBot-Session": self.id}
        return {
            "accept_downloads": False,
            "extra_http_headers": headers,
            **({"storage_state": self.restored_session} if self.restored_session else {}),
        }

    def proxy_method_allowed(self, method, url):
        return self.controller.allow_proxy_method(method, url) if hasattr(self, "controller") else False

    def handle_popup(self, popup, initial):
        # Controller owns popup handling and explicit tab creation for agent jobs.
        pass

    def response_for(self, page):
        if not hasattr(self, "controller"):
            return super().response_for(page)
        return next((tab.get("last_response") for tab in self.controller.tabs.values() if tab["page"] == page), None)

    async def handle_dialog(self, dialog):
        # Controller attaches one handler to every agent tab, including the first.
        pass

    def account(self, prompt, completion, latency, reserve, reservation=None, *, session=None):
        if session is None:
            with transaction() as current:
                return self.account(prompt, completion, latency, reserve, reservation, session=current)
        owned_job(session, self.id, self.token)
        task = session.get(AgentTask, self.id)
        if reserve:
            provider_index = (reservation or {}).get("provider_index", 0)
            maximum = self.options["max_tokens"]
            spent = task.prompt_tokens + task.completion_tokens
            available, held, final = task_token_allowance(
                maximum, spent, fallback_reserve=settings().agent_fallback_tokens,
                primary=provider_index == 0 and len(settings().model_providers()) > 1,
                purpose=(reservation or {}).get("purpose"),
                handoff=bool(getattr(getattr(self, "model", None), "fallback_active", False)
                             or getattr(self, "fallback_notified", 0)),
            )
            if prompt + completion > available:
                raise ModelBudgetExceeded(
                    f"Model token budget exhausted before request: {prompt} estimated input + {completion} reserved output, "
                    f"{max(0, maximum - spent)} remaining, {held} held for fallback, {final} held for finalization",
                    available_tokens=available,
                )
            if getattr(self, "fallback_notified", 0) != provider_index:
                cfg = settings()
                provider = cfg.ai_provider_order.split(",")[provider_index].strip() if cfg.ai_provider_order else "local"
                emit(
                    session,
                    self.id,
                    "model_fallback",
                    f"Using {provider} for this task",
                    provider=provider,
                    model=settings().model_providers()[provider_index][2],
                )
                self.fallback_notified = provider_index
            task.model_calls += 1
            task.prompt_tokens += prompt
            task.completion_tokens += completion
            return (prompt, completion)
        task.prompt_tokens += prompt - reservation[0]
        task.completion_tokens += completion - reservation[1]
        task.model_latency_ms += latency

    async def provider_notice(self, kind, message, **details):
        def save_notice():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                emit(session, self.id, kind, message, **details)
        await database_call(save_notice)

    async def report_provider_failure(self, event):
        await self.provider_notice(
            "model_provider_unavailable",
            f"{event['provider']}: {event['reason']}",
            **event,
        )

    async def ask_model(self, kind, payload, schema, observation=None, *, wait_for_provider=True, client=None):
        image = (
            settings().artifact_dir / observation["screenshot_path"]
            if observation and self.options["visual_reasoning"]
            else None
        )
        async def account_async(*args):
            if len(args) >= 5 and args[3] and isinstance(args[4], dict):
                args = (*args[:4], {**args[4], "purpose": kind})
            if client is not None:
                async with self.classification_account_lock:
                    return await database_call(self.account, *args)
            return await database_call(self.account, *args)

        while True:
            remaining = self.deadline - time.time() - 5
            if remaining <= 0:
                raise ModelDeadlineExceeded("Task time budget exhausted before model request")
            if hasattr(self, "gate"):
                try:
                    async with asyncio.timeout(remaining):
                        await self.gate.wait()
                except TimeoutError:
                    raise ModelDeadlineExceeded("Task time budget exhausted while paused before model request") from None
                remaining = self.deadline - time.time() - 5
                if remaining <= 0:
                    raise ModelDeadlineExceeded("Task time budget exhausted while paused before model request")
            try:
                return await (client or self.model).request(kind, payload, schema, account_async, image, timeout_cap_seconds=remaining)
            except ModelProvidersUnavailable as exc:
                if not wait_for_provider or exc.retry_after is None:
                    raise
                remaining = self.deadline - time.time() - 5
                if exc.retry_after >= remaining:
                    raise ModelDeadlineExceeded("Model providers cannot recover within the remaining task time budget") from exc
                await self.provider_notice(
                    "model_waiting",
                    f"Model providers temporarily unavailable; retrying in {exc.retry_after:.1f}s",
                    retry_after=exc.retry_after,
                    providers=exc.failures,
                )
                # This is inference recovery before dispatch, not a browser action.
                # Preserve the same payload, schema, observation and action budget.
                await asyncio.sleep(exc.retry_after)

    async def checkpoint(self, controller):
        self.memory["tabs"] = [
            {"tab_id": key, "url": tab["page"].url, "purpose": tab["purpose"], "history": tab["history"][-30:]}
            for key, tab in controller.tabs.items()
        ]
        self.memory["active_tab"] = controller.active
        # Keep working memory bounded. Durable per-step observations remain in SQL.
        self.memory["recent_actions"] = self.memory["recent_actions"][-12:]
        self.memory["failures"] = self.memory["failures"][-30:]
        self.memory["answers"] = self.memory["answers"][-10:]
        state = await controller.context.storage_state() if self.options["session_persistence"] else None
        saved_memory = json.loads(json.dumps(self.memory))
        def save_checkpoint():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                task = session.get(AgentTask, self.id)
                task.memory = saved_memory
                if state is not None:
                    task.encrypted_session = encrypt_session(state)

        await database_call(save_checkpoint)

    async def review(self, step_id, decision, controller, observation):
        if not controller.needs_review(decision, self.mode):
            return False

        def request_review():
            with transaction() as session:
                job = owned_job(session, self.id, self.token)
                session.get(AgentTask, self.id).pending_step_id = step_id
                session.get(AgentStep, step_id).status = "waiting_user"
                job.status = "waiting_user"
                emit(session, self.id, "review_requested",
                     decision.text if decision.decision == "ASK_USER" else "Review proposed browser action",
                     step_id=step_id, decision=decision.model_dump())

        def read_review():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                step = session.get(AgentStep, step_id)
                return step.approved, step.user_answer

        def clear_review():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                session.get(AgentTask, self.id).pending_step_id = None

        await database_call(request_review)
        while True:
            await self.gate.wait()
            approved, answer = await database_call(read_review)
            if approved is not None:
                break
            await asyncio.sleep(0.25)
        await database_call(clear_review)
        if answer:
            self.memory["answers"].append(answer)
        if not approved:
            raise ValueError("User declined the proposed action")
        current = await controller.observe()
        if current["fingerprint"] != observation["fingerprint"]:
            raise ValueError("Page changed while awaiting review; replanning required")
        return True

    async def extract(self, decision, observation, step_id):
        text = decision.text.strip()
        requested = (decision.source_quote or text).strip()
        if not requested:
            raise ValueError("Provide source text for the evidence")
        formatted = re.compile(r"\s+".join(re.escape(word) for word in requested.split()), re.IGNORECASE)
        query = {word[:6] for word in terms(text) if len(word) > 2}
        best = (0.0, None)

        def match(source, identifier):
            nonlocal best
            if not source.get("url", "").startswith(("http://", "https://")):
                return None
            candidates = [source.get("text", ""), source.get("viewport_text", ""), source.get("quote", "")]
            candidates.extend(chunk["quote"] for chunk in source.get("research_chunks", []))
            for value in candidates:
                if requested in (value or ""):
                    return source["url"], identifier, requested
                if not value:
                    continue
                if hit := formatted.search(value):
                    return source["url"], identifier, hit.group()
                if decision.source_quote or len(query) < 2:
                    continue
                for excerpt in re.split(r"(?<=[.!?])\s+|(?:\r?\n){2,}", value):
                    excerpt = excerpt.strip()[:700]
                    overlap = query & {word[:6] for word in terms(excerpt)}
                    score = len(overlap) / len(query)
                    if len(overlap) >= 2 and score >= 0.4 and score > best[0]:
                        best = score, (source["url"], identifier, excerpt)
            return None

        found = match(observation, step_id)
        if not found:
            found = next((hit for item in reversed(self.memory["evidence"])
                          if (hit := match(item, item["step_id"]))), None)
        if not found:
            def historical_source():
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    rows = session.execute(
                        select(AgentStep.id, AgentStep.observation).where(AgentStep.job_id == self.id, AgentStep.id != step_id)
                        .order_by(AgentStep.number.desc()).execution_options(yield_per=10)
                    )
                    for identifier, earlier in rows:
                        if hit := match(earlier or {}, identifier):
                            return hit
                return None
            found = await database_call(historical_source)
        found = found or best[1]
        if not found:
            raise ValueError("Source text was not found in this task's authorized observations")
        url, source_step_id, quote = found
        existing = next((e for e in self.memory["evidence"] if e["url"] == url and e["quote"] == quote), None)
        if existing:
            return {**existing, "already_collected": True,
                    **({"summary": text} if text != quote else {})}
        if len(self.memory["evidence"]) >= 40:
            raise ValueError("Evidence budget exhausted")
        item = {"id": f"evidence-{step_id}", "url": url, "quote": quote, "step_id": source_step_id}
        if text != quote:
            item["summary"] = text
        self.memory["evidence"].append(item)
        return item

    async def complete(self, decision):
        from .planning import evaluate

        evidence = {e["id"]: e for e in self.memory["evidence"]}
        if any(key not in evidence for claim in decision.claims for key in claim.evidence_ids):
            raise ValueError("Completion cites missing or unobserved evidence")
        artifact_context = await database_call(self.artifact_verification_context)
        structured = self.memory.get("structured_capture")
        enumeration = getattr(self, "enumeration_mode", False)
        if enumeration and not structured:
            raise ValueError("Listing requires captured records with evidence of category membership")
        criteria = self.verification_criteria()
        research = getattr(self, "research_mode", False)
        if research:
            criteria = self.research_criteria()
        objective_criteria = list(criteria)
        claim_checks = {}
        if research:
            from .research import repair_exact_citations, claim_verification_criteria

            repair_exact_citations(decision.claims, evidence)
            claim_checks = claim_verification_criteria(decision.claims, evidence)
            criteria = [*criteria, *claim_checks]
        capture_criterion = "The captured records come from a relevant source and their observed fields satisfy the requested entity and constraints."
        coverage_criterion = "The quoted count is the full relevant inventory and all requested records have been covered."
        if (not structured and not self.snapshot.get("extraction") and task_text_only(self.objective, self.options)
                and exhaustive_request(self.objective)):
            raise ValueError("Exhaustive inventory completion requires coverage from an observed collection")
        if structured:
            criteria = list(dict.fromkeys([*criteria, capture_criterion]))
            if structured["exhaustive"]:
                if structured["expected_count"] != len(structured["records"]):
                    raise ValueError("Exhaustive coverage of the relevant record group could not be verified")
                criteria = [*criteria, coverage_criterion]
            if structured.get("restrict_to_objective"):
                await self.classify_structured(structured)
            if enumeration and not any(row.get("classification") == "match" for row in structured["records"].values()):
                # An unrelated group does not invalidate the whole source.
                self.reject_enumeration_source(structured, reject_url=False)
                await self.checkpoint(self.controller)
                raise ValueError("This source yielded no qualifying records. Explore a different observed source.")
        qualified = self.enumeration_records(structured) if enumeration else {}
        if len(criteria) > 60:
            raise ValueError("Too many verification checks; consolidate related claims without dropping required criteria")
        verification = await self.ask_model(
            "verify",
            {
                "objective": self.objective,
                "success_criteria": criteria,
                "claims": [c.model_dump() for c in decision.claims],
                "evidence": (self.verification_evidence(evidence, decision.claims) if research else list(evidence.values())),
                "artifact": artifact_context,
                **({"instructions": "Check the original objective and each claim against its cited excerpts. "
                                    "Copy each supplied criterion exactly. For Claim criteria use only the IDs "
                                    "attached to that claim; mark unmet if they do not support the entire claim. "
                                    "Do not confuse supported individual claims with full objective coverage. "
                                    "If sources materially disagree about a required fact, report the disagreement "
                                    "and leave that criterion unverified unless the answer explicitly accounts for it."}
                   if research else {}),
                **({"instructions": "Verify each supplied candidate from its observed fields and classification evidence. "
                                    "A detail page may directly document a qualifying record. A request with no explicit count "
                                    "or exhaustive requirement can be answered with the qualifying records found. Assess the tool's "
                                    "own function and preserve any scope or category constraints in the original objective. "
                                    "For accumulated records, cite every capture evidence ID that supports the accepted records. "
                                    "Do not assume one source represents a complete or exhaustive catalog."}
                   if enumeration else {}),
                **({"captured_records": {
                    **structured, "records": qualified,
                } if enumeration else structured} if structured else {}),
            },
            Verification,
        )
        checks = verification.checks
        verification_ids = set(evidence) if not research else {
            row["id"] for row in self.verification_evidence(evidence, decision.claims)
        }
        from .research import verification_failures

        problems = verification_failures(verification, criteria, verification_ids, claim_checks)
        if research:
            problems.extend("Insufficient subject coverage: " + check.criterion[:160]
                            for check in checks if check.criterion not in claim_checks
                            and not self.research_check_supported(check, verification_ids))
        valid = not problems
        if structured:
            proof_ids = {identifier for identifier in evidence if identifier.startswith("capture-")}
            valid = valid and all(
                proof_ids.intersection(c.evidence_ids) for c in checks if c.criterion in {capture_criterion, coverage_criterion}
            )
        if enumeration:
            capture_check = next((check for check in checks if check.criterion == capture_criterion), None)
            required_proofs = {f"capture-{row['step_id']}" for row in qualified.values()}
            if not capture_check or not required_proofs <= set(capture_check.evidence_ids):
                problems.append("Not every qualifying record has a cited capture source")
                valid = False
        if not valid:
            if research:
                from .research import citation_candidates

                self.keep_research_partial(verification, objective_criteria, verification_ids)
                self.memory["verification_feedback"] = {
                    "problems": problems[:12],
                    "claims": citation_candidates(decision.claims, evidence),
                    "instruction": "Repair citations using actual source excerpts or gather missing authorized evidence. "
                                   "Do not repeat an unchanged completion or weaken the objective.",
                }
                await self.checkpoint(self.controller)
            if enumeration:
                if capture_check and capture_check.met and capture_check.evidence_ids and set(capture_check.evidence_ids) <= verification_ids:
                    cited = set(capture_check.evidence_ids)
                    verified_records = [row for row in qualified.values() if f"capture-{row['step_id']}" in cited]
                    if verified_records:
                        from .structure import merge_qualified_records
                        old = self.memory.get("research_partial", {})
                        merged = merge_qualified_records(old.get("structured_records", []), verified_records)
                        retained = {f"capture-{row['step_id']}" for row in merged.values()}
                        self.memory["research_partial"] = {
                            "partial": True, "claims": [], "structured_records": list(merged.values()),
                            "evidence": [row for key, row in evidence.items() if key in retained],
                            "verification": {"complete": False, "explanation": "These records qualified. The listing was not fully verified.",
                                             "missing_criteria": [criterion for criterion in criteria if criterion != capture_criterion]},
                        }
                self.memory["verification_feedback"] = {
                    "problems": problems[:12],
                    "instruction": "Continue discovery using a different observed record group or authorized source. "
                                   "Previously verified records are retained; do not recapture the rejected group.",
                }
                self.reject_enumeration_source(structured, reject_url=False)
                await self.checkpoint(self.controller)
            raise ValueError("Goal verification incomplete: " + (
                "; ".join(problems)[:380] if problems else "Required structured evidence was not verified"
            ))
        self.memory.pop("verification_feedback", None)
        if research and claim_checks:
            # Publish only citations independently confirmed for each paraphrase.
            by_criterion = {check.criterion: check for check in checks}
            for index, claim in enumerate(decision.claims, 1):
                criterion = f"Claim {index}: {claim.text}"
                if criterion in claim_checks:
                    claim.evidence_ids = list(dict.fromkeys(by_criterion[criterion].evidence_ids))
        supported_ids = {identifier for check in checks for identifier in check.evidence_ids}
        checkpoint_evidence = ([row for row in evidence.values() if row["id"] in supported_ids]
                               if research else self.memory["evidence"])
        planning = self.memory.get("planning")
        if planning:
            if planning["specification"]["output_format"] in {"csv", "json"}:
                def validate_artifact():
                    with transaction() as session:
                        from ..db import DatasetExport

                        artifact = session.get(DatasetExport, self.id)
                        if (
                            not artifact
                            or not artifact.filename
                            or artifact.rows < 1
                            or not (settings().artifact_dir / "exports" / artifact.filename).is_file()
                        ):
                            raise ValueError("Requested export has not been produced and verified")

                await database_call(validate_artifact)
            evaluate(
                planning,
                {"url": self.controller.page.url},
                checkpoint_evidence,
                dataset_count=await database_call(self.dataset_count),
                artifact=bool(self.memory.get("export_artifact")),
                verified=True,
                source_verified=True if enumeration else None,
                collection_complete=True if enumeration else None,
            )
            if any(n["status"] != "completed" for n in planning["plan"]["subtasks"]):
                raise ValueError("Required plan subtasks have not completed")
        result = {
            "claims": [c.model_dump() for c in decision.claims],
            "evidence": list(evidence.values()),
            "verification": verification.model_dump(),
            "model": settings().ai_model,
            "models_used": sorted(self.model.models_used),
            "planning": self.memory.get("planning"),
            "artifact": self.memory.get("export_artifact"),
        }
        if research:
            result["claims"] = [claim.model_dump() for claim in decision.claims if set(claim.evidence_ids) <= supported_ids]
            if not result["claims"]:
                result["claims"] = [{"text": evidence[identifier]["quote"], "evidence_ids": [identifier]}
                                    for identifier in evidence if identifier in supported_ids]
        if structured:
            result["structured_records"] = list(qualified.values()) if enumeration else [
                record for record in structured["records"].values()
                if record.get("classification", "match") == "match"
            ]
        if enumeration:
            result["claims"] = []
        # Publication belongs to worker finalization, after the final checkpoint
        # and browser cleanup succeed. Verification alone is not completion.
        return result

    async def classify_structured(self, capture):
        from .classification import AssessmentBatch, validate_assessments

        cfg = settings()
        pending = [row for row in capture["records"].values() if not row.get("classification")]
        size = min(40, cfg.agent_classification_batch_rows, max(1, (cfg.ai_max_request_chars - 3500) // 3000))
        for offset in range(0, len(pending), size):
            count = (self.memory.get("enumeration_classification_calls", 0)
                     if getattr(self, "enumeration_mode", False) else capture.get("classification_calls", 0))
            if count >= cfg.agent_classification_max_calls:
                raise ValueError("Structured classification reached its configured call budget")
            rows = pending[offset:offset + size]
            payload = classification_request(self.objective, rows)
            capture["classification_calls"] = capture.get("classification_calls", 0) + 1
            if getattr(self, "enumeration_mode", False):
                self.memory["enumeration_classification_calls"] = count + 1
            result = await self.ask_model("classify", payload, AssessmentBatch, wait_for_provider=False)
            validate_assessments(payload, result)
            for assessment in result.records:
                row = rows[assessment.id - 1]
                row["classification"] = assessment.classification
                if assessment.evidence:
                    quote = payload["records"][assessment.id - 1]["excerpts"][assessment.evidence - 1]
                    if (getattr(self, "enumeration_mode", False) and assessment.classification == "match"
                            and len(set(words(quote)) - set(words(row["identity"]))) < 3):
                        row["classification"] = "unknown"
                    else:
                        row["classification_evidence"] = quote
            await self.checkpoint(self.controller)
        if ((not getattr(self, "enumeration_mode", False) or capture["exhaustive"])
                and any(row["classification"] == "unknown" for row in capture["records"].values())):
            raise ValueError("Some records could not be classified against the requested entity")

    def capture_records(self, decision, observation, controller, step_id):
        capture = decision.capture
        exhaustive = exhaustive_request(self.objective)
        if getattr(self, "enumeration_mode", False):
            capture = capture.model_copy(update={"exhaustive": exhaustive, "total_quote": capture.total_quote if exhaustive else None})
        group = controller.observer.structural_groups.get(capture.group)
        if group is None or not any(summary["id"] == capture.group for summary in observation.get("record_groups", [])):
            raise ValueError("The selected record group was not offered in this observation")
        if getattr(self, "enumeration_mode", False) and (observation.get("http_status") or 0) >= 400:
            raise ValueError("A failed response cannot establish a qualifying collection")
        if getattr(self, "enumeration_mode", False):
            from .structure import rejected_group

            if rejected_group(observation["url"], group, self.memory.get("rejected_collection_scopes", [])):
                raise ValueError("This observed collection was rejected. Choose a different source or record group.")
        if len(self.memory["evidence"]) >= 40:
            raise ValueError("Evidence budget exhausted")
        self.policy.check(observation["url"])
        cfg = settings()
        state = add_capture(
            self.memory.get("structured_capture", {}), group, capture, observation, step_id,
            max_rows=cfg.agent_collection_max_rows, max_bytes=cfg.agent_collection_max_bytes,
            exhaustive=exhaustive,
            enumeration=getattr(self, "enumeration_mode", False),
        )
        record_evidence = {
            "id": f"capture-{step_id}", "url": observation["url"], "step_id": step_id,
            "quote": "\n".join((group["label"], *group["context"], *(
                " | ".join(segment["value"] for segment in row["segments"]) for row in group["records"]
            )))[:4000],
        }
        self.memory["structured_capture"] = state
        self.memory["planning"]["route"] = "structured_discovery"
        self.memory["evidence"].append(record_evidence)
        return {"records": len(state["records"]), "expected_count": state["expected_count"], **record_evidence}

    async def restore_tabs(self, controller):
        previous_tabs = self.memory.get("tabs", [])
        if previous_tabs:
            first = previous_tabs[0]
            await controller.navigate(first["url"])
            controller.tabs["t1"]["purpose"] = first["purpose"]
            controller.tabs["t1"]["history"] = first.get("history") or [first["url"]]
            restored = {first["tab_id"]: "t1"}
            for tab in previous_tabs[1 : settings().agent_max_tabs]:
                d = Decision(
                    observation="Restore durable URL",
                    decision="OPEN_TAB",
                    url=tab["url"],
                    reason=tab["purpose"],
                    confidence=1,
                    expected_result="Restore tab",
                )
                await controller.act(d, self.options)
                controller.tabs[controller.active]["history"] = tab.get("history") or [tab["url"]]
                restored[tab["tab_id"]] = controller.active
            active = restored.get(self.memory.get("active_tab"), "t1")
            await controller.act(Decision(
                observation="Restore durable active tab", decision="SWITCH_TAB", tab_id=active,
                reason="Resume the previously active tab", confidence=1, expected_result="Restore tab focus",
            ), self.options)
        else:
            await controller.navigate(self.snapshot["base_url"])

    async def execution_route(self):
        cached = self.memory.get("execution_route")
        if cached:
            return ExecutionRoute(**cached)
        has_dataset = bool(self.snapshot.get("extraction"))
        route = select_route(self.objective, self.options, has_dataset)
        if (not route.entity and route.name in {"general", "research"} and not has_dataset
                and task_text_only(self.objective, self.options) and exhaustive_request(self.objective)
                and settings().ai_provider != "disabled"):
            try:
                assessment = await self.ask_model("route", {
                    "objective": self.objective,
                    "instructions": "Identify a simple exhaustive inventory request. Copy the exact literal phrase "
                                    "naming the entity, without modifiers for additional operations or constraints. "
                                    "Return false for requests involving comparison, actions, filters, sorting, or multiple goals.",
                }, RouteAssessment, wait_for_provider=False)
                entity = assessed_entity(self.objective, assessment)
                if entity:
                    route = inventory_route(entity)
            except (ModelError, ModelBudgetExceeded):
                pass
        self.memory["execution_route"] = asdict(route)
        return route

    async def finish_directory(self, directory, controller, observation, step_id, number, terminal):
        from .planning import evaluate

        with controller.engine.phase("verification"):
            if directory.state.get("source_relevance"):
                await self.classify_directory(directory, controller)
            if directory.state.get("terminal"):
                terminal = directory.blocker() or ""
            result = directory_result(directory.state, terminal or None)
            complete = result["verification"]["complete"]
            explanation = result["verification"]["explanation"]
            preview = observation["screenshot_path"]
            preview_time = min(2, self.deadline - time.time() - 1)
            if not preview and preview_time > 0 and controller.page.url == observation["url"]:
                try:
                    async with asyncio.timeout(preview_time):
                        preview = await self.screenshot(controller.page)
                except (BrowserError, OSError, TimeoutError):
                    pass
            plan = self.memory["planning"]
            evaluate(plan, observation, result["evidence"], verified=complete,
                     source_verified=result["verification"]["dimensions"]["source_relevance"],
                     collection_complete=result["verification"]["dimensions"]["directory_coverage"]
                     and result["verification"]["dimensions"]["extraction_complete"])
            if not complete:
                for node in plan["plan"]["subtasks"]:
                    if node["kind"] == "verify":
                        node.update(status="blocked", outcome=explanation)
                plan["active_subtask"] = None
            plan["last_observation"] = {
                "url": observation["url"], "fingerprint": observation["fingerprint"],
                "step": number, "active_subtask": plan["active_subtask"],
            }
            await self.checkpoint(controller)

        decision = {
            "decision": "VERIFY_COLLECTION", "reason": explanation,
            "observation": "Requested record type, directory coverage and classified evidence",
            "expected_result": "Verified coverage and supporting sources for the requested inventory",
        }
        def persist_verification():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                step = session.get(AgentStep, step_id)
                step.status = "succeeded" if complete else "failed"
                step.decision = decision
                step.outcome = {
                    "directory": {key: value for key, value in result["directory"].items() if key != "records"},
                    "verification": result["verification"], "error": None if complete else explanation,
                    "trace": controller.engine.trace.copy(),
                }
                if preview and not step.observation.get("screenshot_path"):
                    step.observation = {**step.observation, "screenshot_path": preview}
                    emit(session, self.id, "agent_preview_captured", "Last browser capture saved",
                         step_id=step_id, url=observation["url"], screenshot_path=preview)
                emit(session, self.id, "agent_verification", explanation, step_id=step_id,
                     complete=complete, dimensions=result["verification"]["dimensions"])
        await database_call(persist_verification)
        if not complete:
            raise RuntimeError(explanation)
        self.verified_result = result

    async def classify_directory(self, directory, controller):
        from .classification import AssessmentBatch, apply_assessments, assessment_payload, classification_groups

        config = settings()
        state = directory.state
        if config.ai_provider == "disabled" or not config.agent_classification_max_calls:
            return
        store = directory.save_classification

        async def assess(groups, expanded):
            rows = [group[0] for group in groups]
            payload = assessment_payload(directory.entity, rows, expanded=expanded)
            client = ModelClient()
            client.on_provider_event = self.model.on_provider_event
            client.active_provider_index = self.model.active_provider_index
            client.fallback_active = self.model.fallback_active
            result = await self.ask_model("classify", payload, AssessmentBatch, wait_for_provider=False, client=client)
            grounded = [dict(row) for row in rows]
            apply_assessments(grounded, payload, result)
            return grounded, client

        for expanded in (False, True):
            candidates = []
            for group in classification_groups(state["records"].values()):
                cached = next((row for row in group if row["classification"] != "unknown"), None)
                unresolved = [row for row in group if row["classification"] == "unknown"]
                if cached:
                    for row in unresolved:
                        store(row, cached)
                elif unresolved:
                    candidates.append(unresolved)
            batch_size = min(
                config.agent_classification_batch_rows,
                max(1, (config.ai_max_request_chars - 3000) // (1500 if expanded else 950)),
                max(1, (config.ai_max_output_tokens - 96) // 75),
            )
            batches = [candidates[offset:offset + batch_size] for offset in range(0, len(candidates), batch_size)]
            concurrency = config.agent_classification_concurrency
            for offset in range(0, len(batches), concurrency):
                remaining = config.agent_classification_max_calls - state.get("classification_calls", 0)
                if remaining <= 0 or self.deadline - time.time() <= 8:
                    return
                wave = batches[offset:offset + min(concurrency, remaining)]
                state["classification_calls"] = state.get("classification_calls", 0) + len(wave)
                answers = await asyncio.gather(*(assess(batch, expanded) for batch in wave), return_exceptions=True)
                usable = False
                for batch, answer in zip(wave, answers, strict=True):
                    if isinstance(answer, (ModelError, ModelBudgetExceeded)):
                        continue
                    if isinstance(answer, BaseException):
                        raise answer
                    usable = True
                    grounded, client = answer
                    self.model.models_used.update(client.models_used)
                    self.model.active_provider_index = client.active_provider_index
                    self.model.fallback_active = client.fallback_active
                    for group, verdict in zip(batch, grounded, strict=True):
                        if verdict["classification"] != "unknown":
                            for row in group:
                                store(row, verdict)
                await self.checkpoint(controller)
                if not usable:
                    return

    async def execute_page(self, page, context):
        try:
            await self.execute_steps(page, context)
        except (RuntimeError, ValueError) as exc:
            if (getattr(self, "research_mode", False) and self.memory["evidence"]
                    and not self.memory.get("research_partial") and not isinstance(exc, BrowserCrashed)
                    and self.deadline - time.time() > 8):
                await self.verify_research_partial()
            raise

    async def execute_steps(self, page, context):
        controller = Controller(self, context, page, self.memory)
        self.controller = controller
        await context.unroute("**/*")
        await context.route("**/*", controller.route)
        route = await self.execution_route()
        research = route.name in {"comparison", "research"} and not route.entity and not self.snapshot.get("extraction")
        self.research_mode = research
        enumeration = route.name == "enumeration"
        self.enumeration_mode = enumeration
        await self.restore_tabs(controller)
        observe_options = {**({"research": True} if research else {})}
        cfg = settings()
        directory = DirectoryCollection(route.entity, self.memory.setdefault("directory", {}),
                                        max_rows=cfg.agent_collection_max_rows, max_bytes=cfg.agent_collection_max_bytes) if route.entity else None
        collection_mode = route.entity
        use_structure = not self.snapshot.get("extraction") and cfg.ai_provider != "disabled"
        structure_options = {"structure": "enumeration" if enumeration else True} if use_structure else {}
        def read_start():
            with transaction() as session:
                start = session.scalar(
                    select(func.coalesce(func.max(AgentStep.number), 0)).where(AgentStep.job_id == self.id)
                )
            return start

        start = await database_call(read_start)
        stagnant, last_fingerprint, consecutive_failures = 0, None, 0
        next_observation = None
        for number in range(start + 1, self.options["max_steps"] + 1):
            await self.gate.wait()
            controller.engine.trace = []
            controller.engine.dispatch_started = False
            use_directory = directory is not None and not self.memory.get("structured_capture")
            with controller.engine.phase("inspection"):
                observation = next_observation
                reused_observation = observation is not None
                next_observation = None
                if observation is None:
                    observation = (await controller.observe(directory=collection_mode) if use_directory else
                                   await controller.observe(**observe_options, **structure_options))
            await self.prepare_plan(observation, deterministic=enumeration or directory is not None or (
                research and len(comparison_entities(self.objective)) >= 2
            ))
            permissions = self.memory["planning"]["specification"]["permissions"]
            read_search = bool(self.mode == "autonomous" and (research or enumeration or use_directory)
                               and permissions.get("read_search"))
            approved_posts = permissions.get("approved_post_search", []) if read_search else []
            if research and not reused_observation:
                self.rank_research(observation)
            if observation["url"] not in self.memory["visited_urls"]:
                self.memory["visited_urls"].append(observation["url"])
            if enumeration or use_directory:
                visited = self.memory.setdefault("research_destinations", {})
                visited[destination_key(observation["url"])] = (
                    len(self.memory["evidence"]) + (len(directory.state["records"]) if use_directory else 0)
                )
                if len(visited) > 100:
                    visited.pop(next(iter(visited)))
            if research or enumeration or use_directory:
                self.remember_discovery(observation)
            def record_observation():
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    step = AgentStep(job_id=self.id, number=number, observation=observation)
                    session.add(step)
                    session.flush()
                    step_id = step.id
                    emit(
                        session,
                        self.id,
                        "agent_observed",
                        "Page observed",
                        step_id=step_id,
                        url=observation["url"],
                        screenshot_path=observation["screenshot_path"],
                    )
                return step_id

            step_id = await database_call(record_observation)
            if research and not reused_observation:
                await self.save_research_observation(observation, step_id, controller)
            decision = None
            deterministic = False
            scoped_search = False
            semantic_key = None
            prevented = False
            rejected_source = False
            len_before = len(self.memory["evidence"])
            try:
                with controller.engine.phase("decision"):
                    terminal = None
                    if use_directory:
                        batch = observation.get("directory")
                        rejected_source = bool(
                            batch and batch.get("kind") not in {None, "results", "entries", "items"}
                            and collection_kinds(directory.entity) and not matching_collection(directory.entity, batch)
                        )
                        decision, terminal = directory.advance(observation, step_id, self.policy)
                        deterministic = decision is not None or terminal is not None
                        if directory.state["pages"]:
                            await self.checkpoint(controller)
                    if research:
                        decision = self.research_decision(observation)
                    if enumeration:
                        decision = self.enumeration_decision(observation, controller.observer.structural_groups)
                    if terminal is None and decision is None:
                        if use_directory:
                            # Retain bounded candidate excerpts from the read-only
                            # directory scan while obtaining full actionable controls.
                            candidate_batch = observation.get("directory")
                            observation = await controller.observe(**({"structure": True} if use_structure else {}))
                            if candidate_batch:
                                observation["directory_candidates"] = {
                                    "label": candidate_batch.get("label"), "kind": candidate_batch.get("kind"),
                                    "total": candidate_batch.get("total"),
                                    "rows": [{k: row.get(k) for k in ("name", "category", "href", "quote")}
                                             for row in candidate_batch.get("rows", [])[:6]],
                                    "note": "Unverified candidates; capture matching observed records before further navigation.",
                                }
                            self.remember_discovery(observation)
                            def update_observation():
                                with transaction() as session:
                                    owned_job(session, self.id, self.token)
                                    session.get(AgentStep, step_id).observation = observation
                            await database_call(update_observation)
                        if (research or enumeration or use_directory) and not self.options["allow_form_input"]:
                            groups = self.available_groups(observation) if enumeration else []
                            if not groups and read_search:
                                decision = search_candidate(observation, self.objective, self.policy,
                                                            self.memory.get("search_attempts", []), approved_posts)
                            if decision is None and not groups and unchanged_scrolls(observation, self.memory["recent_actions"]) >= 2:
                                decision = self.discovery_alternative(observation)
                        plan = self.planning_context()
                        if decision is None:
                            decision = await self.ask_model(
                                "decide",
                                {
                                    "objective": self.objective,
                                    "success_criteria": self.options["success_criteria"],
                                    "current_page": self.research_model_page(observation) if research or enumeration or use_directory else observation,
                                    "session_memory": self.context_memory(observation, plan),
                                    "execution_route": {"name": route.name, "guidance": route.guidance},
                                    "historical_hints": self.hints,
                                    "steps_remaining": self.options["max_steps"] - number,
                                    "form_input_enabled": self.options["allow_form_input"],
                                    "read_search_enabled": read_search,
                                    "approved_post_search": approved_posts,
                                    "task_plan": plan,
                                    **({"discovery": self.discovery_context(observation)}
                                       if research or enumeration or use_directory else {}),
                                    **({"rejected_collection_sources": self.memory.get("rejected_collection_sources", [])[-8:],
                                        "rejected_collection_scopes": self.memory.get("rejected_collection_scopes", [])[-8:],
                                        "verified_partial_record_count": len(self.memory.get("research_partial", {}).get("structured_records", []))}
                                       if enumeration else {}),
                                    **({"captured_record_count": len(self.memory["structured_capture"]["records"]),
                                        "expected_record_count": self.memory["structured_capture"]["expected_count"]}
                                       if "structured_capture" in self.memory else {}),
                                },
                                Decision,
                                observation,
                            )
                if terminal is not None:
                    await self.finish_directory(directory, controller, observation, step_id, number, terminal)
                    return
                if decision.decision == "OBSERVE" and self.memory["recent_actions"]:
                    previous = self.memory["recent_actions"][-1]
                    if previous["action"] == "OBSERVE" and not previous.get("outcome", {}).get("page_changed", False):
                        raise ValueError(
                            "OBSERVE already returned unchanged content; navigate an observed link, interact with a relevant control, or report the blockage"
                        )
                if enumeration and self.mode == "autonomous" and not self.options["allow_form_input"] and (
                    decision.decision == "NAVIGATE" or (
                        decision.decision == "CLICK" and decision.input_method == "auto" and not decision.expected_text
                        and decision.target and any(
                            e["element_id"] == decision.target.element_id and e.get("href") and not e.get("form")
                            and e.get("role") == "link" for e in observation.get("elements", [])
                        )
                    )
                ):
                    target_url = decision.url if decision.decision == "NAVIGATE" else next(
                        (e.get("href") for e in observation["elements"]
                         if decision.target and e["element_id"] == decision.target.element_id), None)
                    if target_url:
                        # A policy-denied action is not silently substituted.
                        allowed_url = self.policy.check(target_url)
                        target_key = destination_key(allowed_url)
                        history = self.memory.get("research_destinations", {})
                        if (target_key == destination_key(observation["url"])
                                or target_key in self.memory.get("rejected_collection_sources", [])
                                or history.get(target_key) == len(self.memory["evidence"])):
                            alternative = (search_candidate(observation, self.objective, self.policy,
                                                           self.memory.get("search_attempts", []), approved_posts) if read_search else None)
                            alternative = alternative or self.discovery_alternative(observation)
                            if alternative:
                                decision = alternative
                            else:
                                raise ValueError("No unexplored relevant destination is available; inspect another observed record group or search")
                        elif read_search and not self.memory.get("structured_capture") and not self.options["allow_form_input"]:
                            # The page has been assessed and a navigation action was
                            # selected; a search is a more direct discovery path.
                            decision = search_candidate(observation, self.objective, self.policy,
                                                        self.memory.get("search_attempts", []), approved_posts) or decision
                # Retain the common planning permission guard below.
                decision_data = decision.model_dump()
                key = action_key(decision_data)
                if enumeration:
                    if decision.decision in {"NAVIGATE", "OPEN_TAB"} and decision.url in self.memory.get("rejected_collection_sources", []):
                        raise ValueError("The proposed source was already rejected. Choose another observed collection.")
                    link = decision.url if decision.decision in {"NAVIGATE", "OPEN_TAB"} else None
                    if decision.decision == "CLICK":
                        link = next((element.get("href") for element in observation["elements"]
                                     if element["element_id"] == decision.target.element_id), None)
                    if decision.decision == "GO_BACK":
                        history = controller.tabs[controller.active]["history"]
                        link = history[-2] if len(history) >= 2 else None
                    if link:
                        if destination_key(link) in self.memory.get("rejected_collection_sources", []):
                            raise ValueError("The proposed source was already rejected. Choose another observed collection.")
                        if decision.decision == "GO_BACK":
                            edge = [destination_key(observation["url"]), destination_key(link)]
                            if edge in self.memory.get("enumeration_return_edges", []):
                                raise ValueError("This discovery return route was already attempted.")
                        else:
                            guard_navigation(self.memory.get("research_destinations", {}), link, observation["url"],
                                             len(self.memory["evidence"]))
                    if decision.decision in {"SCROLL", "SCROLL_BACK"}:
                        from .structure import scroll_blocked

                        if scroll_blocked(decision.decision, decision.direction, observation, self.memory["recent_actions"]):
                            raise ValueError("Scrolling made no progress or reached the document boundary. "
                                             "Capture observed records or choose another authorized source.")
                if research or (use_directory and not deterministic):
                    target = decision.url if decision.decision in {"NAVIGATE", "OPEN_TAB"} else None
                    if decision.decision == "CLICK":
                        target = next((e.get("href") for e in observation["elements"]
                                       if e["element_id"] == decision.target.element_id), None)
                    if decision.decision == "GO_BACK":
                        history = controller.tabs[controller.active]["history"]
                        target = history[-2] if len(history) >= 2 else None
                    if target:
                        guard_navigation(self.memory.get("research_destinations", {}), target, observation["url"],
                                         len(self.memory["evidence"]) + (len(directory.state["records"]) if use_directory else 0))
                if not deterministic:
                    semantic_key = semantic_action_key(decision_data, observation)
                    entries = self.memory.get("semantic_attempts", {})
                    if semantic_key is not None and entries.get(semantic_key, 0) >= 2:
                        prevented = True
                        self.memory["prevented_repetitions"] = self.memory.get("prevented_repetitions", 0) + 1
                        raise ValueError("Blocked a repeated action with no new evidence; choose a different observed route")
                from .planning import guard

                if (research or enumeration or use_directory) and (
                    decision.decision in {"NAVIGATE", "GO_BACK", "OPEN_TAB", "OBSERVE", "SCROLL",
                                          "EXTRACT", "SUMMARIZE", "CAPTURE_RECORDS", "COMPLETE", "FAIL"}
                    or (read_search and decision.decision == "SEARCH")
                    or (decision.decision == "CLICK" and decision.target and any(
                        e.get("element_id") == decision.target.element_id and e.get("href") and not e.get("form")
                        for e in observation.get("elements", [])
                    ))
                ):
                    # The runtime owns phase transitions. An otherwise safe research
                    # action remains useful when a model echoes a completed phase.
                    decision.subtask_id = None
                guard(self.memory["planning"], decision, observation)
                if read_search and decision.decision == "SEARCH":
                    element = next((e for e in observation["elements"] if e["element_id"] == decision.target.element_id), {})
                    scoped_search = (search_control(element, approved_posts)
                                     and search_query_allowed(self.objective, decision.text))
                if scoped_search:
                    attempt = search_attempt_key(element, decision.text, observation["url"])
                    attempts = self.memory.setdefault("search_attempts", [])
                    if attempt in attempts:
                        raise ValueError("This search query was already attempted; use the observed results or a different search")
                    if len(attempts) >= MAX_SEARCH_ATTEMPTS:
                        raise ValueError("Read-only search attempt limit reached; inspect the observed sources")
                    attempts.append(attempt)
                    await self.checkpoint(controller)
                if any(
                    f["action_key"] == key and f["fingerprint"] == observation["fingerprint"]
                    for f in self.memory["failures"]
                ):
                    raise ValueError("Repeated failed action on unchanged page; choose a different approach")
                def record_decision():
                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        step = session.get(AgentStep, step_id)
                        step.decision = decision.model_dump()
                        emit(
                            session,
                            self.id,
                            "agent_decision",
                            decision.reason,
                            step_id=step_id,
                            decision=decision.model_dump(),
                        )

                await database_call(record_decision)
                approved = await self.review(step_id, decision, controller, observation)
                await self.gate.wait()
                # Mark in-flight before any interaction, for ambiguity detection.
                def mark_executing():
                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        session.get(AgentStep, step_id).status = "executing"

                await database_call(mark_executing)
                if decision.decision == "EXTRACT_DATASET":
                    if not self.snapshot.get("extraction"):
                        raise ValueError("Configure an owned extraction dataset before structured capture")
                    from ..extraction.service import extract_page

                    await extract_page(self, controller.page)
                    outcome = {"records": await database_call(self.dataset_count)}
                elif decision.decision == "EXPORT_DATASET":
                    outcome = await self.export_dataset()
                elif decision.decision == "FAIL":
                    raise RuntimeError("Agent reported task blocked: " + decision.text)
                elif decision.decision == "COMPLETE":
                    if directory and (directory.state["pages"] or not self.memory.get("structured_capture")):
                        raise ValueError("Exhaustive completion requires verified coverage of the requested collection")
                    outcome = await self.complete(decision)
                elif decision.decision == "CAPTURE_RECORDS":
                    if rejected_source:
                        raise ValueError("The observed source type conflicts with the requested collection")
                    outcome = self.capture_records(decision, observation, controller, step_id)
                elif decision.decision == "EXTRACT":
                    outcome = await self.extract(decision, observation, step_id)
                elif decision.decision == "SUMMARIZE":
                    available = {e["id"] for e in self.memory["evidence"]}
                    if not decision.claims or any(k not in available for c in decision.claims for k in c.evidence_ids):
                        raise ValueError("Summary requires claims citing collected evidence")
                    self.memory["summary"] = [c.model_dump() for c in decision.claims]
                    outcome = {"summary": self.memory["summary"]}
                else:
                    read_link = (research or enumeration) and self.mode == "autonomous" and not self.options["allow_form_input"] and (
                        decision.decision == "CLICK" and decision.target and any(
                            element.get("element_id") == decision.target.element_id
                            and element.get("role") == "link" and element.get("href") and not element.get("form")
                            for element in observation.get("elements", [])
                        )
                    )
                    if scoped_search:
                        outcome = await controller.act(decision, {**self.options, "allow_read_search": True,
                                                                  "approved_post_search": approved_posts},
                                                       approved, read_only=True)
                    elif read_link:
                        outcome = await controller.act(decision, self.options, approved, read_only=True, prefer_navigation=True)
                    else:
                        outcome = (await controller.act(decision, self.options, approved, read_only=True)
                                   if deterministic else await controller.act(decision, self.options, approved))
                # COMPLETE has no browser side effect; the current observation
                # already grounds its evidence. Do not add a fallible browser read.
                no_browser_action = decision.decision in {"COMPLETE", "CAPTURE_RECORDS", "EXTRACT", "SUMMARIZE"}
                after = (observation if no_browser_action or deterministic else await controller.observe(
                    **observe_options, **(structure_options if research or enumeration else {}),
                ))
                if research and not no_browser_action:
                    self.rank_research(after)
                    await self.save_research_observation(after, step_id, controller, persist=False)
                    next_observation = after
                elif enumeration and not no_browser_action:
                    next_observation = after
                if (
                    self.snapshot.get("extraction")
                    and decision.decision != "EXTRACT_DATASET"
                    and after["fingerprint"] != observation["fingerprint"]
                ):
                    from ..extraction.service import extract_page

                    await extract_page(self, controller.page, required=False)
                from .planning import evaluate

                if decision.decision != "COMPLETE":
                    evaluate(
                        self.memory["planning"],
                        after,
                        self.memory["evidence"],
                        await database_call(self.dataset_count),
                        bool(self.memory.get("export_artifact")),
                        collection_complete=False if enumeration or (directory and not self.memory.get("structured_capture")) else None,
                        source_verified=False if enumeration else bool(directory.state.get("source_relevance")) if directory and not self.memory.get("structured_capture") else None,
                    )
                active_id = self.memory["planning"]["active_subtask"]
                self.memory["planning"]["last_observation"] = {
                    "url": after["url"],
                    "fingerprint": after["fingerprint"],
                    "step": number,
                    "active_subtask": active_id,
                }
                outcome["trace"] = controller.engine.trace.copy()
                outcome["traffic_kind"] = "automated"
                if enumeration:
                    outcome["record_groups_changed"] = after.get("record_groups") != observation.get("record_groups")
                    if decision.decision in {"SCROLL", "SCROLL_BACK"}:
                        outcome["scroll_before"] = observation.get("scroll", {})
                        outcome["scroll_after"] = after.get("scroll", {})
                        outcome["scroll_direction"] = "up" if decision.decision == "SCROLL_BACK" else decision.direction
                outcome["after_url"] = controller.page.url if deterministic else after["url"]
                outcome["url_changed"] = outcome["after_url"] != observation["url"]
                if enumeration and decision.decision == "GO_BACK" and outcome["url_changed"]:
                    edges = self.memory.setdefault("enumeration_return_edges", [])
                    edges.append([destination_key(observation["url"]), destination_key(outcome["after_url"])])
                    del edges[:-100]
                interaction = outcome.get("interaction") or {}
                outcome["content_changed"] = (interaction.get("content_changed") if deterministic else
                                              after["text"] != observation["text"])
                if research or enumeration or use_directory:
                    before_groups = set(self.memory.get("discovery_group_signatures", []))
                    self.remember_discovery(after)
                    new_groups = set(self.memory.get("discovery_group_signatures", [])) - before_groups
                    outcome["new_relevant_groups"] = len(new_groups)
                    outcome["information_progress"] = bool(len(self.memory["evidence"]) > len_before or new_groups)
                    outcome["discovery"] = self.discovery_context(observation)
                outcome["page_changed"] = bool(outcome["url_changed"] or outcome["content_changed"] or
                                               after["fingerprint"] != observation["fingerprint"])
                if isinstance(outcome.get("interaction"), dict):
                    for key, observed_page in (("focus_before", observation), ("focus_after", after)):
                        focused = next((e for e in observed_page.get("elements", []) if e.get("focused")), None)
                        if focused:
                            outcome["interaction"][key] = {
                                **outcome["interaction"].get(key, {}),
                                "name": focused["name"],
                                "role": focused["role"],
                                "element_id": focused["element_id"],
                            }
                outcome = controller.observer.sanitize(outcome)
                self.memory["recent_actions"].append(
                    {
                        "action": decision.decision,
                        "reason": decision.reason,
                        "outcome": outcome if decision.decision != "COMPLETE" else "Verified result",
                    }
                )
                if len(self.memory["evidence"]) > len_before:
                    self.memory.pop("semantic_attempts", None)
                elif semantic_key is not None:
                    self.record_semantic_attempt(semantic_key)
                await self.checkpoint(controller)
                def record_success():
                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        step = session.get(AgentStep, step_id)
                        step.status, step.outcome = "succeeded", outcome
                        emit(
                            session,
                            self.id,
                            "agent_action_completed",
                            f"{decision.decision} observed",
                            interaction=outcome.get("interaction"),
                            trace=outcome["trace"],
                            traffic_kind="automated",
                            step_id=step_id,
                            url=outcome["after_url"],
                            screenshot_path=after["screenshot_path"],
                            page_changed=outcome["page_changed"],
                            url_changed=outcome["url_changed"],
                            content_changed=outcome["content_changed"],
                        )

                await database_call(record_success)
                consecutive_failures = 0
                if decision.decision == "COMPLETE":
                    self.verified_result = outcome
                    return
                if deterministic:
                    continue
                from .planning import track_progress

                if not research:
                    track_progress(self.memory["planning"], decision, after, len(self.memory["evidence"]))
                progress = (
                    None if research else after["fingerprint"],
                    len(self.memory["evidence"]),
                    0 if research else len(self.memory.get("summary", [])),
                    len(self.memory["answers"]),
                )
                stagnant = stagnant + 1 if progress == last_fingerprint else 0
                last_fingerprint = progress
                if stagnant >= 5:
                    raise RuntimeError("Agent stopped after repeated actions without observable progress")
            except (ModelContextExceeded, ModelDeadlineExceeded, ModelProvidersUnavailable):
                raise
            except (ValueError, PermissionError, ModelError, BrowserError, BrowserCrashed) as exc:
                decision_data = locals().get("decision")
                key = (
                    action_key(decision_data.model_dump()) if isinstance(decision_data, Decision) else f"model:{number}"
                )
                self.memory["failures"].append(
                    {
                        "action_key": key,
                        "fingerprint": observation["fingerprint"],
                        "error": controller.observer.safe_text(str(exc))[:500],
                    }
                )
                if semantic_key is not None and not prevented:
                    self.record_semantic_attempt(semantic_key)
                from .planning import classify_failure, replan

                # A scoped read-only SEARCH never receives a write grant.
                # Preserve uncertainty handling for ordinary inputs/submissions.
                ambiguous_write = bool(
                    controller.engine.dispatch_started
                    and decision
                    and decision.decision in {"CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"}
                    and not scoped_search
                )
                original_error = controller.observer.safe_text(str(exc))[:500]
                if ambiguous_write:
                    exc = PermissionError(
                        "Input may have modified external state; inspect the failed action before starting another task"
                    )
                safe_error = controller.observer.safe_text(str(exc))
                safe_reason = (
                    PermissionError(safe_error) if isinstance(exc, PermissionError) else ValueError(safe_error)
                )
                # Persist ambiguity before any browser read or cookie checkpoint:
                # either can fail when the dispatch destroyed the page.
                if ambiguous_write:
                    category = "uncertain_submission"
                elif research or enumeration or use_directory:
                    # A one-step synthetic research checkpoint can deadlock a
                    # multi-hop source search. The current phase and job bounds
                    # already limit recovery.
                    category = classify_failure(safe_reason)
                else:
                    category = replan(self.memory["planning"], safe_reason, observation)
                def record_failure():
                    with transaction() as session:
                        owned_job(session, self.id, self.token)
                        task = session.get(AgentTask, self.id)
                        task.pending_step_id = None
                        step = session.get(AgentStep, step_id)
                        if isinstance(decision_data, Decision) and not step.decision:
                            step.decision = controller.observer.sanitize(decision_data.model_dump())
                        step.status, step.outcome = (
                            "failed",
                            {
                                "error": safe_error[:500],
                                "cause": original_error,
                                "replanning": not ambiguous_write,
                                "failure_classification": category,
                                **({"discovery": controller.observer.sanitize(self.discovery_context(observation))}
                                   if enumeration or research or use_directory else {}),
                                "uncertain_submission": ambiguous_write,
                                "trace": controller.observer.sanitize(controller.engine.trace.copy()),
                                "traffic_kind": "automated",
                            },
                        )
                        emit(session, self.id, "agent_action_failed" if ambiguous_write else "agent_replanning",
                             safe_error[:500], step_id=step_id)

                await database_call(record_failure)
                if ambiguous_write:
                    raise RuntimeError(str(exc)) from exc
                try:
                    if not (research or enumeration or use_directory):
                        with controller.engine.phase("recovery"):
                            await controller.observe()
                except (BrowserError, BrowserCrashed) as recovery_error:
                    raise BrowserCrashed("Agent browser unavailable during recovery") from recovery_error
                await self.checkpoint(controller)
                if category == "terminal":
                    raise RuntimeError(str(exc)) from exc
                consecutive_failures += 1
                if consecutive_failures >= settings().agent_max_retries:
                    if enumeration:
                        raise RuntimeError("Insufficient qualifying source evidence after bounded discovery; inspect mapping diagnostics and failed actions") from exc
                    raise RuntimeError("Agent recovery budget exhausted; inspect failed steps") from exc
        raise RuntimeError("Agent step budget exhausted before verified completion")

    def rank_research(self, observation):
        planning = self.memory["planning"]
        entities = comparison_entities(self.objective, planning["plan"]["intent"].get("entities", []))
        criteria = self.verification_criteria()
        observation["research_chunks"] = ranked_chunks(
            observation.get("research_chunks", []), self.objective, observation.get("title", ""), entities, criteria,
        )[:12]

    def available_groups(self, observation):
        from .structure import rejected_group

        return [group for group in observation.get("record_groups", [])
                if not rejected_group(observation["url"], group, self.memory.get("rejected_collection_scopes", []))]

    def remember_discovery(self, observation):
        self.memory["discovery_frontier"] = update_frontier(
            self.memory.get("discovery_frontier", {}), observation, self.objective, self.policy, self.discovery_exclusions()
        )
        previous = self.memory.get("discovery_group_signatures", [])
        self.memory["discovery_group_signatures"] = list(dict.fromkeys(
            [*previous, *sorted(relevant_group_signatures(observation, self.objective))]
        ))[-100:]

    def discovery_alternative(self, observation):
        return frontier_candidate(self.memory.get("discovery_frontier", {}), observation, self.policy,
                                  self.discovery_exclusions())

    def discovery_context(self, observation):
        return {
            **observation.get("discovery", {}),
            "unexplored_sources": list(self.memory.get("discovery_frontier", {}).values())[:5],
            "unexplored_count": len(self.memory.get("discovery_frontier", {})),
            "evidence_count": len(self.memory["evidence"]),
            "search_attempts": len(self.memory.get("search_attempts", [])),
            "instruction": "Assess record groups first. If automatic mapping is uncertain, map observed fields "
                           "using CAPTURE_RECORDS or extract exact source text. If unsuitable, prefer site search "
                           "or an unexplored source. A new URL is not qualifying evidence.",
        }

    def discovery_exclusions(self):
        return {destination_key(url) for url in self.memory.get("visited_urls", [])} | set(
            self.memory.get("rejected_collection_sources", [])
        )

    def enumeration_decision(self, observation, structural_groups=None):
        capture = self.memory.get("structured_capture")
        if capture and not capture.get("exhaustive"):
            evidence = next((row for row in reversed(self.memory["evidence"]) if row["id"].startswith("capture-")), None)
            if evidence and self.memory.get("enumeration_verified_capture") != evidence["id"]:
                self.memory["enumeration_verified_capture"] = evidence["id"]
                return Decision(observation="Candidate records are available for qualification", decision="COMPLETE",
                                reason="Classify the captured records and verify the listing", confidence=1,
                                expected_result="A list of qualifying records",
                                claims=[{"text": "Observed candidate records", "evidence_ids": [evidence["id"]]}])
        if capture:
            return None
        if structural_groups and not exhaustive_request(self.objective):
            diagnostics = observation.setdefault("discovery", {})
            candidate = automatic_capture(
                observation, structural_groups, self.objective,
                rejected=self.memory.get("rejected_collection_scopes", []),
                diagnostics=diagnostics,
                max_rows=min(48, max(0, settings().agent_classification_max_calls -
                                      self.memory.get("enumeration_classification_calls", 0)) *
                             min(40, settings().agent_classification_batch_rows,
                                 max(1, (settings().ai_max_request_chars - 3500) // 3000))),
            )
            if candidate is not None:
                return candidate
        entity = "semantic:" + " ".join(words(self.objective))
        recognized = bool(collection_kinds(entity))
        destinations = set()
        direct = set()
        subject = {word[:6] for word in words(self.objective) if word not in {"list", "and", "for", "of", "the"}}
        if not any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
            from .structure import rejected_group

            groups = [group for group in observation.get("record_groups", [])
                      if not rejected_group(observation["url"], group, self.memory.get("rejected_collection_scopes", []))]
            repeated = any(group["kind"] != "detail" and group.get("observed_count", 0) >= 2
                           for group in groups)
            for group in groups:
                if (group["kind"] == "detail" and not repeated
                        and len(subject & {word[:6] for word in words(group["label"])}) >= 2):
                    return Decision(
                        observation="A visible detail record has a relevant heading", decision="CAPTURE_RECORDS",
                        reason="Capture the record for category qualification", confidence=1,
                        expected_result="An observed title and its own description",
                        capture={"group": group["id"], "fields": [{"name": "Name", "position": 1},
                                                                 {"name": "Description", "position": 2}], "identity": 1},
                    )
        if structural_groups is not None and self.available_groups(observation):
            observation.setdefault("discovery", {})["strategy"] = "model_assisted"
            return None
        if structural_groups is not None and not self.options.get("allow_form_input"):
            if self.memory.get("planning", {}).get("specification", {}).get("permissions", {}).get("read_search"):
                return None
            catalog = navigation_candidate(
                observation, self.objective, self.policy, excluded=self.discovery_exclusions(),
                minimum=8, catalog_only=True,
            )
            if catalog is not None:
                return catalog
        for element in observation.get("elements", []):
            href = element.get("href")
            if not href or not element.get("actionable") or element.get("blocked_by_modal"):
                continue
            label = {word[:6] for word in words(element.get("name", ""))
                     if word not in {"open", "browse", "view", "explore", "the", "all"}}
            specific = len(label) >= 2 and label <= subject
            if not specific and not (recognized and directory_link(element, entity)):
                continue
            try:
                target = self.policy.check(href)
            except ValueError:
                continue
            if (destination_key(target) not in {destination_key(url) for url in self.memory.get("visited_urls", [])}
                    and destination_key(target) not in self.memory.get("rejected_collection_sources", [])):
                (direct if specific else destinations).add(target)
        destinations = direct or destinations
        if len(destinations) == 1:
            return Decision(observation="Observed link potentially relevant to the requested records", decision="NAVIGATE",
                            url=destinations.pop(), reason="Inspect the authorized destination and establish its purpose",
                            confidence=0.8, expected_result="Candidate records or further discovery links")
        return None

    def reject_enumeration_source(self, collection, *, reject_url=True):
        # Release active scope but retain independently verified partial results.
        if reject_url:
            rejected = self.memory.setdefault("rejected_collection_sources", [])
            url = destination_key(collection["source_url"])
            if url not in rejected:
                rejected.append(url)
            del rejected[:-100]
        groups = self.memory.setdefault("rejected_collection_scopes", [])
        for scope in collection.get("observed_scopes") or [[collection["source_url"], collection["scope"][2]]]:
            if scope not in groups:
                groups.append(scope)
        del groups[:-100]
        self.memory.pop("structured_capture", None)
        self.memory.pop("enumeration_verified_capture", None)
        retained = {row["id"] for row in self.memory.get("research_partial", {}).get("evidence", [])}
        self.memory["evidence"] = [row for row in self.memory["evidence"]
                                   if not row["id"].startswith("capture-") or row["id"] in retained]

    def enumeration_records(self, collection):
        from .structure import merge_qualified_records

        previous = [] if collection.get("exhaustive") else self.memory.get("research_partial", {}).get("structured_records", [])
        records = merge_qualified_records(previous, collection["records"].values())
        cfg = settings()
        if len(records) > cfg.agent_collection_max_rows or len(json.dumps(records, ensure_ascii=False).encode()) > cfg.agent_collection_max_bytes:
            raise ValueError("Accumulated verified collection exceeds its resource budget")
        return records

    def research_decision(self, observation):
        entities = comparison_entities(self.objective, self.memory["planning"]["plan"]["intent"].get("entities", []))
        if len(entities) < 2 or any(dialog.get("visible") for dialog in observation.get("dialogs", [])):
            return None
        evidence = self.memory["evidence"]
        dimensions = comparison_dimensions(self.objective)
        matrix = coverage(evidence, entities, dimensions)
        if all(matrix["entities"].values()) and all(matrix["criteria"].values()):
            offered = self.verification_evidence({row["id"]: row for row in evidence})
            fingerprint = [row["id"] for row in offered]
            if fingerprint != self.memory.get("research_verified_candidates"):
                self.memory["research_verified_candidates"] = fingerprint
                return Decision(
                    observation="Rendered excerpts cover each comparison subject",
                    decision="COMPLETE", reason="Verify the captured comparison evidence", confidence=1,
                    expected_result="A source-backed result or identified evidence gaps",
                    claims=[{"text": row["quote"], "evidence_ids": [row["id"]]} for row in offered],
                )
        destinations = {}
        indexes = {}
        for element in observation.get("elements", []):
            url = element.get("href")
            if not url or not element.get("actionable") or element.get("blocked_by_modal"):
                continue
            label = terms(element.get("name", "") + " " + urlsplit(url).path.replace("-", " "))
            direct = all(terms(entity) <= label for entity in entities)
            comparison_index = element.get("name", "").casefold().strip() in {"compare", "comparison", "comparisons"}
            if not direct and not comparison_index:
                continue
            try:
                url = self.policy.check(url)
                guard_navigation(self.memory.get("research_destinations", {}), url, observation["url"], len(evidence))
            except ValueError:
                continue
            (destinations if direct else indexes)[destination_key(url)] = url
        choices = destinations or (indexes if not any(matrix["entities"].values()) else {})
        if len(choices) == 1:
            return Decision(observation="Observed comparison destination", decision="NAVIGATE",
                            url=next(iter(choices.values())), reason="Open the relevant comparison source",
                            confidence=1, expected_result="Rendered evidence for the requested subjects")
        return None

    def research_model_page(self, observation):
        history = self.memory.get("research_destinations", {})
        count = len(self.memory["evidence"])
        def available_control(element):
            if not element.get("href"):
                return True
            try:
                key = destination_key(element["href"])
            except ValueError:
                return False
            return (history.get(key) != count and key not in self.memory.get("rejected_collection_sources", []))

        available = [element for element in observation["elements"] if available_control(element)]
        groups = observation.get("record_groups", [])
        if getattr(self, "enumeration_mode", False):
            from .structure import rejected_group

            groups = [group for group in groups
                      if not rejected_group(observation["url"], group, self.memory.get("rejected_collection_scopes", []))]
        if self.options["allow_form_input"] or self.options.get("visual_reasoning"):
            return {**observation, "elements": available, "record_groups": groups}
        return compact_page(observation, self.objective, elements=available, groups=groups,
                            actions=self.memory.get("recent_actions", []), form_input=False,
                            read_search=bool(self.memory.get("planning", {}).get("specification", {}).get("permissions", {}).get("read_search")),
                            approved_posts=self.options.get("approved_post_search", []))

    def research_criteria(self):
        entities = comparison_entities(self.objective, self.memory["planning"]["plan"]["intent"].get("entities", []))
        criteria = [*self.verification_criteria(), *(f"Compare the requested subjects on {field}"
                    for field in comparison_dimensions(self.objective))]
        # Assess each requested subject even if the original comparison is incomplete.
        return list(dict.fromkeys([*criteria, *(f"Source evidence relevant to the objective for {entity}" for entity in entities)]))

    def verification_evidence(self, evidence, claims=()):
        cited = {identifier for claim in claims for identifier in claim.evidence_ids}
        selected = [row for identifier, row in evidence.items() if identifier in cited]
        dimensions = self.memory.get("research_coverage", {})
        prioritized = list(dict.fromkeys(
            identifier for matrix in dimensions.values() for ids in matrix.values() for identifier in ids[:2]
        ))
        from .context import retrieve_evidence

        ranked = retrieve_evidence(list(evidence.values()), self.objective, {}, limit=12, exact=True)
        for identifier in [*prioritized, *[row["id"] for row in ranked], *evidence]:
            if len(selected) >= 12:
                break
            if identifier in evidence and evidence[identifier] not in selected:
                selected.append(evidence[identifier])
        return selected

    def keep_research_partial(self, verification, criteria, offered):
        supported = {}
        for criterion in criteria:
            checks = [check for check in verification.checks if check.criterion == criterion]
            if len(checks) == 1 and self.research_check_supported(checks[0], offered):
                supported[criterion] = checks[0].evidence_ids
        if not supported:
            return
        ids = {identifier for identifiers in supported.values() for identifier in identifiers}
        evidence = [row for row in self.memory["evidence"] if row["id"] in ids]
        self.memory["research_partial"] = {
            "partial": True,
            "claims": [{"text": row["quote"], "evidence_ids": [row["id"]]} for row in evidence],
            "evidence": evidence,
            "verification": {"complete": False, "explanation": "These verified excerpts cover part of the research objective.",
                             "supported_criteria": supported,
                             "missing_criteria": [criterion for criterion in criteria if criterion not in supported]},
        }

    def research_check_supported(self, check, offered):
        cited = set(check.evidence_ids)
        if not check.met or not cited or not cited <= offered:
            return False
        entities = comparison_entities(self.objective, self.memory["planning"]["plan"]["intent"].get("entities", []))
        evidence = self.memory["evidence"]
        by_entity = coverage(evidence, entities, [])["entities"]
        relevant_entities = (
            entities if check.criterion in {f"Compare the requested subjects on {field}"
                                            for field in comparison_dimensions(self.objective)}
            else [entity for entity in entities if check.criterion == f"Source evidence relevant to the objective for {entity}"]
        )
        return all(cited.intersection(by_entity[entity]) for entity in relevant_entities)

    async def verify_research_partial(self):
        evidence = self.verification_evidence({row["id"]: row for row in self.memory["evidence"]})
        criteria = self.research_criteria()
        try:
            verification = await self.ask_model("verify", {
                "objective": self.objective, "success_criteria": criteria, "evidence": evidence, "claims": [],
                "instructions": "Verify each criterion independently. Retain supported source excerpts even when other criteria are incomplete.",
            }, Verification, wait_for_provider=False)
        except (ModelError, ModelBudgetExceeded):
            return
        self.keep_research_partial(verification, criteria, {row["id"] for row in evidence})
        await self.checkpoint(self.controller)

    async def save_research_observation(self, observation, step_id, controller, *, persist=True):
        entities = comparison_entities(self.objective, self.memory["planning"]["plan"]["intent"].get("entities", []))
        criteria = [*self.verification_criteria(), *comparison_dimensions(self.objective)]
        store = self.memory["evidence"]
        if capture_evidence(observation, store, step_id, entities, criteria):
            self.memory["research_coverage"] = coverage(store, entities, criteria)
        history = self.memory.setdefault("research_destinations", {})
        history[destination_key(observation["url"])] = len(store)
        if len(history) > 100:
            history.pop(next(iter(history)))
        if persist:
            await self.checkpoint(controller)

    def record_semantic_attempt(self, key):
        entries = self.memory.setdefault("semantic_attempts", {})
        entries[key] = entries.get(key, 0) + 1
        if len(entries) > 64:
            entries.pop(next(iter(entries)))

    def context_memory(self, observation, plan):
        from .context import retrieve_evidence

        phase = next((step["description"] for step in plan.get("subtasks", [])
                      if step["id"] == plan.get("active_subtask")), "")
        return {
            "visited_urls": self.memory["visited_urls"][-30:],
            "evidence": retrieve_evidence(self.memory["evidence"], self.objective, observation, phase=phase,
                                          exact=getattr(self, "research_mode", False)),
            "failures": self.memory["failures"][-6:],
            "answers": self.memory["answers"][-3:],
            "recent_actions": self.memory["recent_actions"][-6:],
            "summary": self.memory.get("summary", []),
            **({"verification_feedback": self.memory["verification_feedback"]}
               if "verification_feedback" in self.memory else {}),
            **({"research_coverage": self.memory["research_coverage"]} if "research_coverage" in self.memory else {}),
        }

    def verification_criteria(self):
        spec = self.memory.get("planning", {}).get("specification", {})
        return list(dict.fromkeys(self.options["success_criteria"] + spec.get("constraints", [])))

    def planning_context(self):
        from .planning import context

        return context(self.memory["planning"])

    def artifact_verification_context(self):
        state = self.memory.get("planning", {})
        if state.get("specification", {}).get("output_format") not in {"csv", "json"}:
            return None
        from ..db import DatasetExport, ExtractedRecord

        # Verify the entire exported record scope, never a sample presented as all
        # records. Oversized semantic verification fails rather than omitting rows.
        self.dataset_count()
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            artifact = session.get(DatasetExport, self.id)
            source_scope = job.execution_state.get("agent_record_scope", {})
            scope = artifact.options.get("selected_record_hashes", source_scope) if artifact else source_scope
            if (
                not artifact
                or not artifact.filename
                or not scope
                or artifact.rows != len(scope)
                or artifact.options.get("source_record_hashes") != source_scope
                or not (settings().artifact_dir / "exports" / artifact.filename).is_file()
            ):
                raise ValueError("Requested export has not been produced with the verified task record scope")
            records, size = [], 0
            ids = artifact.options.get("selected_record_ids", list(scope))
            for start in range(0, len(ids), 500):
                found = {row.id: row for row in session.scalars(
                    select(ExtractedRecord)
                    .where(ExtractedRecord.id.in_(ids[start : start + 500]))
                    .order_by(ExtractedRecord.id)
                )}
                if any(key not in found for key in ids[start : start + 500]):
                    raise ValueError("Export records disappeared before semantic verification")
                for key in ids[start : start + 500]:
                    row = found[key]
                    if row.content_hash != scope[row.id]:
                        raise ValueError("Export records changed before semantic verification")
                    size += len(json.dumps(row.data, ensure_ascii=False))
                    if size > settings().ai_max_request_chars // 2:
                        raise ValueError(
                            "Complete artifact exceeds the semantic verification context budget; use a smaller task or export through the dataset interface"
                        )
                    records.append(row.data)
            if len(records) != artifact.rows:
                raise ValueError("Export records disappeared before semantic verification")
            return {
                "format": artifact.format,
                "rows": artifact.rows,
                "records": records,
                "instructions": "These are ALL exported task records. Verify requested filtering, exclusions, quantity and output requirements against these records as well as cited page evidence. Do not claim unverified artifact semantics.",
            }

    def dataset_count(self):
        if not self.snapshot.get("extraction"):
            return 0
        from ..db import ExtractedRecord

        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            scope = job.execution_state.get("agent_record_scope", {})
            ids = list(scope)
            for start in range(0, len(ids), 500):
                rows = session.scalars(
                    select(ExtractedRecord).where(
                        ExtractedRecord.dataset_id == self.snapshot["extraction"]["dataset_id"],
                        ExtractedRecord.id.in_(ids[start : start + 500]),
                        ExtractedRecord.status == "active",
                    )
                ).all()
                if len(rows) != len(ids[start : start + 500]) or any(row.content_hash != scope[row.id] for row in rows):
                    raise ValueError("Task records changed in a concurrent run; re-observe before export")
            return len(ids)

    async def prepare_plan(self, observation, *, deterministic=False):
        from .planning import specification, initial_plan, needs_model_plan, accept_model_plan, evaluate, TaskPlan

        expected = specification(
            self.objective, self.options["success_criteria"], self.options, self.snapshot["allowed_domains"]
        )
        state = self.memory.get("planning")
        if state is None:
            state = initial_plan(expected, self.options["max_steps"], bool(self.snapshot.get("extraction")))
            self.memory["planning"] = state
        if state["specification"]["source_hash"] != expected["source_hash"]:
            raise ValueError("Durable task constraints no longer match the authorized task")
        route = self.memory.get("execution_route")
        if route:
            state["route"] = "structured_discovery" if self.memory.get("structured_capture") else route["name"]
            if route.get("entity"):
                state["plan"]["intent"]["entities"] = [route["entity"].removeprefix("semantic:")]
        if getattr(self, "research_mode", False):
            state["research_evidence_required"] = True
            state["research_requirements"] = {
                "entities": comparison_entities(self.objective, state["plan"]["intent"].get("entities", [])),
                "criteria": list(dict.fromkeys([*self.verification_criteria(), *comparison_dimensions(self.objective)])),
            }
        if not state.get("initialized"):
            if not deterministic and needs_model_plan(expected):
                try:
                    draft = await self.ask_model(
                        "plan",
                        {
                            "objective": self.objective,
                            "task_specification": expected,
                            "execution_route": self.memory.get("execution_route"),
                            "current_page": {
                                "url": observation["url"],
                                "title": observation["title"],
                                "headings": observation["headings"],
                            },
                            "instructions": "Copy the primary objective exactly. Retain every explicit constraint. Propose pending subtasks with valid dependencies; never grant additional permissions or claim completed work.",
                            "seed_plan": state["plan"],
                            "semantic_controls": [
                                {k: e.get(k) for k in ("role", "name", "actionable", "context")}
                                for e in observation.get("elements", [])[:12]
                            ],
                            "active_dialogs": observation.get("dialogs", []),
                        },
                        TaskPlan,
                    )
                    accept_model_plan(state, draft, self.options["max_steps"])
                except (ModelDeadlineExceeded, ModelProvidersUnavailable):
                    raise
                except (ValueError, ModelError):
                    state["warnings"].append(
                        "Model decomposition unavailable or invalid; using disclosed conservative phases, not inferred task facts"
                    )
            state["initialized"] = True
        evaluate(
            state, observation, self.memory["evidence"], await database_call(self.dataset_count),
            bool(self.memory.get("export_artifact")),
            collection_complete=False if deterministic else None,
            source_verified=bool(self.memory.get("directory", {}).get("source_relevance")) if deterministic else None,
        )
        def persist():
            with transaction() as session:
                owned_job(session, self.id, self.token)
                session.get(AgentTask, self.id).memory = json.loads(json.dumps(self.memory))

        await database_call(persist)

    async def export_dataset(self):
        from .planning import ready

        state = self.memory["planning"]
        if not any(n["kind"] == "export" for n in ready(state)):
            raise ValueError("Export dependencies are incomplete")
        snap = self.snapshot.get("extraction")
        if not snap or await database_call(self.dataset_count) < 1:
            raise ValueError("Extract valid structured records before export")
        if state["specification"]["output_format"] not in {"csv", "json"}:
            raise ValueError("Select an explicit JSON or CSV output format")
        from ..db import DatasetExport, ExtractionRun
        from ..extraction.exporter import export
        from ..concurrency import IOExecutor
        import threading

        def persist():
            with transaction() as session:
                job = owned_job(session, self.id, self.token)
                run = session.get(ExtractionRun, self.id)
                if run and (run.truncated or run.invalid_count):
                    raise ValueError(
                        "Structured capture is partial or invalid; resolve dataset diagnostics before claiming a complete export"
                    )
                job.snapshot = {**job.snapshot, "export_schema": snap["definition"]}
                artifact = session.get(DatasetExport, self.id)
                if artifact is None:
                    session.add(
                        DatasetExport(
                            job_id=self.id,
                            dataset_id=snap["dataset_id"],
                            format=state["specification"]["output_format"],
                            options={
                                "columns": [],
                                "include_revisions": False,
                                "source_record_hashes": job.execution_state.get("agent_record_scope", {}),
                        "query": self.options.get("dataset_query"),
                            },
                            expires_at=time.time() + settings().extraction_export_ttl_seconds,
                        )
                    )
                else:
                    artifact.options = {
                        "columns": [],
                        "include_revisions": False,
                        "source_record_hashes": job.execution_state.get("agent_record_scope", {}),
                        "query": self.options.get("dataset_query"),
                    }

        await database_call(persist)
        stop = threading.Event()
        async with IOExecutor(1) as executor:
            try:
                await executor.run(export, self.id, self.token, stop)
            finally:
                stop.set()
        self.memory["export_artifact"] = {
            "job_id": self.id,
            "format": state["specification"]["output_format"],
            "download_url": f"/api/extraction/exports/{self.id}/download",
        }
        return self.memory["export_artifact"]
