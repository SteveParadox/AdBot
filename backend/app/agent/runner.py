import time
import asyncio
import json
import random

from playwright.async_api import Error as BrowserError

from sqlalchemy import func, select

from ..browser import BrowserCrashed, Runner
from ..config import settings
from ..db import AgentStep, AgentTask, emit, transaction
from ..jobs import owned_job
from .contracts import Decision, Verification
from .controller import Controller
from .memory import action_key, decrypt_session, encrypt_session, relevant_memories, save_memory
from .model import ModelBudgetExceeded, ModelClient, ModelError


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
            self.memory = task.memory or {
                "visited_urls": [],
                "evidence": [],
                "failures": [],
                "answers": [],
                "recent_actions": [],
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
        if random.random() < 0.3:
            headers["X-Request-ID"] = f"req-{random.randint(100000, 999999)}"
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

    def account(self, prompt, completion, latency, reserve, reservation=None):
        with transaction() as session:
            owned_job(session, self.id, self.token)
            task = session.get(AgentTask, self.id)
            if reserve:
                provider_index = (reservation or {}).get("provider_index", 0)
                task_budget = self.options["max_tokens"]
                if provider_index == 0 and settings().ai_fallback_provider != "disabled":
                    task_budget = max(0, task_budget - settings().agent_fallback_tokens)
                if task.prompt_tokens + task.completion_tokens + prompt + completion > task_budget:
                    raise ModelBudgetExceeded("Model token budget exhausted before request")
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
        remaining = max(1, int(self.deadline - time.time()) - 5)
        return await self.model.request(
            kind, payload, schema, self.account, image, timeout_cap_seconds=remaining
        )

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
        with transaction() as session:
            owned_job(session, self.id, self.token)
            task = session.get(AgentTask, self.id)
            task.memory = json.loads(json.dumps(self.memory))
            if state is not None:
                task.encrypted_session = encrypt_session(state)

    async def review(self, step_id, decision, controller, observation):
        if not controller.needs_review(decision, self.mode):
            return False
        with transaction() as session:
            job = owned_job(session, self.id, self.token)
            task = session.get(AgentTask, self.id)
            step = session.get(AgentStep, step_id)
            task.pending_step_id = step_id
            step.status = "waiting_user"
            job.status = "waiting_user"
            emit(
                session,
                self.id,
                "review_requested",
                decision.text if decision.decision == "ASK_USER" else "Review proposed browser action",
                step_id=step_id,
                decision=decision.model_dump(),
            )
        while True:
            await self.gate.wait()
            with transaction() as session:
                owned_job(session, self.id, self.token)
                step = session.get(AgentStep, step_id)
                approved, answer = step.approved, step.user_answer
            if approved is not None:
                break
            await asyncio.sleep(0.25)
        with transaction() as session:
            owned_job(session, self.id, self.token)
            session.get(AgentTask, self.id).pending_step_id = None
        if answer:
            self.memory["answers"].append(answer)
        if not approved:
            raise ValueError("User declined the proposed action")
        # A review grants only the exact observed action, never a changed page.
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
        evidence = {e["id"]: e for e in self.memory["evidence"]}
        if any(key not in evidence for claim in decision.claims for key in claim.evidence_ids):
            raise ValueError("Completion cites missing or unobserved evidence")
        verification = await self.ask_model(
            "verify",
            {
                "objective": self.objective,
                "success_criteria": self.options["success_criteria"],
                "claims": [c.model_dump() for c in decision.claims],
                "evidence": list(evidence.values()),
            },
            Verification,
        )
        checks = verification.checks
        criteria = self.options["success_criteria"]
        valid = (
            verification.complete and len(checks) == len(criteria) and {c.criterion for c in checks} == set(criteria)
        )
        valid = valid and all(c.met and c.evidence_ids and all(e in evidence for e in c.evidence_ids) for c in checks)
        if not valid:
            raise ValueError("Goal verification incomplete: " + verification.explanation[:400])
        result = {
            "claims": [c.model_dump() for c in decision.claims],
            "evidence": list(evidence.values()),
            "verification": verification.model_dump(),
            "model": settings().ai_model,
            "models_used": sorted(self.model.models_used),
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
            with controller.engine.phase("inspection"):
                observation = await controller.observe()
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
                        },
                        Decision,
                        observation,
                    )
                key = action_key(decision.model_dump())
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
                if decision.decision == "FAIL":
                    raise RuntimeError("Agent reported task blocked: " + decision.text)
                if decision.decision == "COMPLETE":
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
                outcome["trace"] = controller.engine.trace.copy()
                outcome["traffic_kind"] = "automated"
                outcome["after_url"] = after["url"]
                outcome["page_changed"] = after["fingerprint"] != observation["fingerprint"]
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
            except (ValueError, ModelError, BrowserError) as exc:
                if isinstance(exc, BrowserError) and (
                    controller.page.is_closed() or not context.browser.is_connected()
                ):
                    raise BrowserCrashed("Agent browser disconnected") from exc
                decision_data = locals().get("decision")
                key = (
                    action_key(decision_data.model_dump()) if isinstance(decision_data, Decision) else f"model:{number}"
                )
                self.memory["failures"].append(
                    {"action_key": key, "fingerprint": observation["fingerprint"], "error": str(exc)[:500]}
                )
                # Re-observe before replanning; never replay ambiguous input.
                with controller.engine.phase("recovery"):
                    await controller.observe()
                with transaction() as session:
                    owned_job(session, self.id, self.token)
                    task = session.get(AgentTask, self.id)
                    task.pending_step_id = None
                    step = session.get(AgentStep, step_id)
                    step.status, step.outcome = (
                        "failed",
                        {
                            "error": str(exc)[:500],
                            "replanning": True,
                            "trace": controller.engine.trace.copy(),
                            "traffic_kind": "automated",
                        },
                    )
                    emit(session, self.id, "agent_replanning", str(exc)[:500], step_id=step_id)
                await self.checkpoint(controller)
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
