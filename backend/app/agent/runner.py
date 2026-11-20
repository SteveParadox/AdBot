import time
import asyncio
import json

from playwright.async_api import Error as BrowserError

from sqlalchemy import func, select

from ..browser import BrowserCrashed, Runner
from ..config import settings
from ..concurrency import database_call
from ..db import AgentStep, AgentTask, emit, transaction
from ..jobs import owned_job
from .contracts import Decision, Verification
from .controller import Controller
from .memory import action_key, decrypt_session, encrypt_session, relevant_memories, save_memory
from .model import ModelDeadlineExceeded, ModelBudgetExceeded, ModelClient, ModelError


class AgentRunner(Runner):
    def __init__(self, job_id, token):
        super().__init__(job_id, token)
        self.model = ModelClient()
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

    def account(self, prompt, completion, latency, reserve, reservation=None, *, session=None):
        if session is None:
            with transaction() as current:
                return self.account(prompt, completion, latency, reserve, reservation, session=current)
        owned_job(session, self.id, self.token)
        task = session.get(AgentTask, self.id)
        if reserve:
            provider_index = (reservation or {}).get("provider_index", 0)
            task_budget = self.options["max_tokens"]
            if provider_index == 0 and settings().ai_fallback_provider != "disabled":
                task_budget = max(0, task_budget - settings().agent_fallback_tokens)
            if task.prompt_tokens + task.completion_tokens + prompt + completion > task_budget:
                raise ModelBudgetExceeded("Model token budget exhausted before request")
            if provider_index == 1 and not getattr(self, "fallback_notified", False):
                emit(
                    session,
                    self.id,
                    "model_fallback",
                    "Local model selected for this task",
                    model=settings().ai_fallback_model,
                )
                self.fallback_notified = True
            task.model_calls += 1
            task.prompt_tokens += prompt
            task.completion_tokens += completion
            return (prompt, completion)
        task.prompt_tokens += prompt - reservation[0]
        task.completion_tokens += completion - reservation[1]
        task.model_latency_ms += latency

    async def ask_model(self, kind, payload, schema, observation=None):
        image = (
            settings().artifact_dir / observation["screenshot_path"]
            if observation and self.options["visual_reasoning"]
            else None
        )
        remaining = self.deadline - time.time() - 5
        if remaining <= 0:
            raise ModelDeadlineExceeded("Task time budget exhausted before model request")
        async def account_async(*args):
            return await database_call(self.account, *args)
        return await self.model.request(kind, payload, schema, account_async, image, timeout_cap_seconds=remaining)

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

    def extract(self, decision, observation, step_id):
        quote = decision.text.strip()
        if quote not in observation["text"] and quote not in observation["viewport_text"]:
            raise ValueError("Evidence must be an exact quote from the current observation")
        if len(self.memory["evidence"]) >= 40:
            raise ValueError("Evidence budget exhausted")
        if any(e["url"] == observation["url"] and e["quote"] == quote for e in self.memory["evidence"]):
            raise ValueError("This quote was already collected; choose new evidence")
        item = {"id": f"evidence-{step_id}", "url": observation["url"], "quote": quote[:4000], "step_id": step_id}
        self.memory["evidence"].append(item)
        return item

    async def complete(self, decision):
        from .planning import evaluate

        evidence = {e["id"]: e for e in self.memory["evidence"]}
        if any(key not in evidence for claim in decision.claims for key in claim.evidence_ids):
            raise ValueError("Completion cites missing or unobserved evidence")
        artifact_context = await database_call(self.artifact_verification_context)
        verification = await self.ask_model(
            "verify",
            {
                "objective": self.objective,
                "success_criteria": self.verification_criteria(),
                "claims": [c.model_dump() for c in decision.claims],
                "evidence": list(evidence.values()),
                "artifact": artifact_context,
            },
            Verification,
        )
        checks = verification.checks
        criteria = self.verification_criteria()
        valid = (
            verification.complete and len(checks) == len(criteria) and {c.criterion for c in checks} == set(criteria)
        )
        valid = valid and all(c.met and c.evidence_ids and all(e in evidence for e in c.evidence_ids) for c in checks)
        if not valid:
            raise ValueError("Goal verification incomplete: " + verification.explanation[:400])
        planning = self.memory.get("planning")
        if planning:
            if planning["specification"]["output_format"] in {"csv", "json"}:
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
            evaluate(
                planning,
                {"url": self.controller.page.url},
                self.memory["evidence"],
                dataset_count=await database_call(self.dataset_count),
                artifact=bool(self.memory.get("export_artifact")),
                verified=True,
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
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            task = session.get(AgentTask, self.id)
            task.result = result
            if self.options["memory_enabled"]:
                save_memory(session, job, task)
            emit(
                session,
                self.id,
                "goal_verified",
                "Objective verified against collected evidence",
                claims=len(decision.claims),
            )
        return result

    async def execute_page(self, page, context):
        controller = Controller(self, context, page, self.memory)
        self.controller = controller
        await context.unroute("**/*")
        await context.route("**/*", controller.route)
        previous_tabs = self.memory.get("tabs", [])
        if previous_tabs:
            first = previous_tabs[0]
            await controller.navigate(first["url"])
            controller.tabs["t1"]["history"] = first.get("history") or [first["url"]]
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
            # Tab IDs are session-local; recovery publishes the new IDs.
        else:
            await controller.navigate(self.snapshot["base_url"])
        with transaction() as session:
            start = session.scalar(
                select(func.coalesce(func.max(AgentStep.number), 0)).where(AgentStep.job_id == self.id)
            )
        stagnant, last_fingerprint, consecutive_failures = 0, None, 0
        for number in range(start + 1, self.options["max_steps"] + 1):
            await self.gate.wait()
            controller.engine.trace = []
            controller.engine.dispatch_started = False
            with controller.engine.phase("inspection"):
                observation = await controller.observe()
            await self.prepare_plan(observation)
            if observation["url"] not in self.memory["visited_urls"]:
                self.memory["visited_urls"].append(observation["url"])
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
            decision = None
            try:
                with controller.engine.phase("decision"):
                    decision = await self.ask_model(
                        "decide",
                        {
                            "objective": self.objective,
                            "success_criteria": self.options["success_criteria"],
                            "current_page": observation,
                            "session_memory": self.context_memory(),
                            "historical_hints": self.hints,
                            "steps_remaining": self.options["max_steps"] - number,
                            "form_input_enabled": self.options["allow_form_input"],
                            "task_plan": self.planning_context(),
                        },
                        Decision,
                        observation,
                    )
                if decision.decision == "OBSERVE" and self.memory["recent_actions"]:
                    previous = self.memory["recent_actions"][-1]
                    if previous["action"] == "OBSERVE" and not previous.get("outcome", {}).get("page_changed", False):
                        raise ValueError(
                            "OBSERVE already returned unchanged content; navigate an observed link, interact with a relevant control, or report the blockage"
                        )
                key = action_key(decision.model_dump())
                from .planning import guard

                guard(self.memory["planning"], decision, observation)
                if any(
                    f["action_key"] == key and f["fingerprint"] == observation["fingerprint"]
                    for f in self.memory["failures"]
                ):
                    raise ValueError("Repeated failed action on unchanged page; choose a different approach")
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
                approved = await self.review(step_id, decision, controller, observation)
                await self.gate.wait()
                # Mark in-flight before any interaction, for ambiguity detection.
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    session.get(AgentStep, step_id).status = "executing"
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
                    outcome = await self.complete(decision)
                elif decision.decision == "EXTRACT":
                    outcome = self.extract(decision, observation, step_id)
                elif decision.decision == "SUMMARIZE":
                    available = {e["id"] for e in self.memory["evidence"]}
                    if not decision.claims or any(k not in available for c in decision.claims for k in c.evidence_ids):
                        raise ValueError("Summary requires claims citing collected evidence")
                    self.memory["summary"] = [c.model_dump() for c in decision.claims]
                    outcome = {"summary": self.memory["summary"]}
                else:
                    outcome = await controller.act(decision, self.options, approved)
                after = await controller.observe()
                if (
                    self.snapshot.get("extraction")
                    and decision.decision != "EXTRACT_DATASET"
                    and after["fingerprint"] != observation["fingerprint"]
                ):
                    from ..extraction.service import extract_page

                    await extract_page(self, controller.page, required=False)
                from .planning import evaluate

                evaluate(
                    self.memory["planning"],
                    after,
                    self.memory["evidence"],
                    await database_call(self.dataset_count),
                    bool(self.memory.get("export_artifact")),
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
                outcome["after_url"] = after["url"]
                outcome["page_changed"] = after["fingerprint"] != observation["fingerprint"]
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
                        url=after["url"],
                        screenshot_path=after["screenshot_path"],
                        page_changed=outcome["page_changed"],
                    )
                await self.checkpoint(controller)
                consecutive_failures = 0
                if decision.decision == "COMPLETE":
                    return
                from .planning import track_progress

                track_progress(self.memory["planning"], decision, after, len(self.memory["evidence"]))
                progress = (
                    after["fingerprint"],
                    len(self.memory["evidence"]),
                    len(self.memory.get("summary", [])),
                    len(self.memory["answers"]),
                )
                stagnant = stagnant + 1 if progress == last_fingerprint else 0
                last_fingerprint = progress
                if stagnant >= 5:
                    raise RuntimeError("Agent stopped after repeated actions without observable progress")
            except ModelDeadlineExceeded:
                raise
            except (ValueError, PermissionError, ModelError, BrowserError) as exc:
                if isinstance(exc, BrowserError) and (
                    controller.page.is_closed() or not context.browser.is_connected()
                ):
                    raise BrowserCrashed("Agent browser disconnected") from exc
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
                # Re-observe before replanning; never replay ambiguous input.
                with controller.engine.phase("recovery"):
                    recovered = await controller.observe()
                from .planning import replan

                ambiguous_write = bool(
                    controller.engine.dispatch_started
                    and decision
                    and decision.decision in {"CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"}
                )
                if ambiguous_write:
                    exc = PermissionError(
                        "Input may have modified external state; inspect the failed action before starting another task"
                    )
                safe_error = controller.observer.safe_text(str(exc))
                safe_reason = (
                    PermissionError(safe_error) if isinstance(exc, PermissionError) else ValueError(safe_error)
                )
                category = replan(self.memory["planning"], safe_reason, recovered)
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    task = session.get(AgentTask, self.id)
                    task.pending_step_id = None
                    step = session.get(AgentStep, step_id)
                    step.status, step.outcome = (
                        "failed",
                        {
                            "error": safe_error[:500],
                            "replanning": True,
                            "failure_classification": category,
                            "uncertain_submission": ambiguous_write,
                            "trace": controller.observer.sanitize(controller.engine.trace.copy()),
                            "traffic_kind": "automated",
                        },
                    )
                    emit(session, self.id, "agent_replanning", safe_error[:500], step_id=step_id)
                await self.checkpoint(controller)
                if ambiguous_write:
                    raise RuntimeError(str(exc)) from exc
                if category == "terminal":
                    raise RuntimeError(str(exc)) from exc
                consecutive_failures += 1
                if consecutive_failures >= settings().agent_max_retries:
                    raise RuntimeError("Agent recovery budget exhausted; inspect failed steps") from exc
        raise RuntimeError("Agent step budget exhausted before verified completion")

    def context_memory(self):
        return {
            "visited_urls": self.memory["visited_urls"][-30:],
            "evidence": [dict(e, quote=e["quote"][:1000]) for e in self.memory["evidence"][-20:]],
            "failures": self.memory["failures"][-6:],
            "answers": self.memory["answers"][-3:],
            "recent_actions": self.memory["recent_actions"][-6:],
            "summary": self.memory.get("summary", []),
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

    async def prepare_plan(self, observation):
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
        if not state.get("initialized"):
            if needs_model_plan(expected):
                try:
                    draft = await self.ask_model(
                        "plan",
                        {
                            "objective": self.objective,
                            "task_specification": expected,
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
                except ModelDeadlineExceeded:
                    raise
                except (ValueError, ModelError):
                    state["warnings"].append(
                        "Model decomposition unavailable or invalid; using disclosed conservative phases, not inferred task facts"
                    )
            state["initialized"] = True
        evaluate(
            state, observation, self.memory["evidence"], await database_call(self.dataset_count), bool(self.memory.get("export_artifact"))
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
