"""Safe, actionable job failure summaries; retry advice never authorizes a write."""
from sqlalchemy import select
from .db import AgentStep, PageVisit


def diagnose(session, job, message, exception=None):
    last = session.scalar(select(AgentStep).where(AgentStep.job_id == job.id).order_by(AgentStep.number.desc()).limit(1))
    successful = session.scalar(select(AgentStep).where(AgentStep.job_id == job.id, AgentStep.status == "succeeded").order_by(AgentStep.number.desc()).limit(1))
    action = (last.decision or {}).get("decision") if last else None
    text = (message + " " + (str(last.outcome) if last else "")).lower()
    uncertain = bool(last and action in {"CLICK", "TYPE", "SEARCH", "PRESS_KEY", "SET_CHECKED", "SELECT_OPTION"} and (last.status == "executing" or "uncertain" in text or bool((last.outcome or {}).get("uncertain_submission"))))
    category, stage, recovery = "execution", "execution", "Inspect the job events and correct the failed operation before retrying."
    if uncertain:
        category, stage, recovery = "uncertain_submission", "interaction", "Check the destination for the action result before starting another task; do not replay automatically."
    elif "quota" in text or "429" in text or "throttl" in text:
        category, stage, recovery = "provider_throttling", "model_request", "Wait for the provider cooldown, then retry within the configured shared quota."
    elif exception is not None and type(exception).__module__ == "app.agent.model":
        category, stage, recovery = "provider_error", "model_request", "Check provider availability, credentials and model configuration before retrying."
    elif job.job_type == "export" or "export" in text:
        category, stage, recovery = "export", "dataset_export", "Review export options and dataset changes; retry against a consistent dataset."
    elif "extract" in text or "dataset" in text or action == "EXTRACT_DATASET":
        category, stage, recovery = "extraction", "structured_capture", "Review extraction issues, required fields and selectors before retrying."
    elif "navigation" in text or "net::" in text or "goto" in text:
        category, stage, recovery = "navigation", "navigation", "Check the target URL, domain policy and proxy connectivity before retrying."
    elif "duration" in text or "deadline" in text or "time budget" in text:
        category, stage, recovery = "timeout", "execution", "Review slow operations and task limits before starting a new run."
    elif "browser" in text:
        category, stage, recovery = "browser", "browser_runtime", "Check installed browser binaries and available resources before retrying."
    elif "initialization" in text:
        category, stage, recovery = "configuration", "initialization", "Check job configuration and the encrypted session key."
    workflow_steps = job.snapshot.get("workflow", {}).get("steps", [])
    if job.job_type == "workflow" and 0 < job.action_index <= len(workflow_steps):
        last_success = {"action": workflow_steps[job.action_index - 1]["action"], "step": job.action_index}
    elif successful:
        last_success = {"action": (successful.decision or {}).get("decision"), "step": successful.number}
    else:
        visit = session.scalar(select(PageVisit).where(PageVisit.job_id == job.id, PageVisit.error.is_(None)).order_by(PageVisit.id.desc()).limit(1))
        last_success = {"action": "NAVIGATE", "step": None} if visit else None
    return {"category": category, "stage": stage, "last_successful_action": last_success,
            "retry_eligible": not uncertain and job.job_type in {"crawl", "export"},
            "suggested_recovery": recovery, "automatic_retry_scheduled": False}
