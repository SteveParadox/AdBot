"""Opt-in acceptance check against a running Adbot deployment (no mocks).

Run from the repository root with Python 3.10+. The workspace key is read
only from the environment. Never use a fixture deployment as live evidence.
"""
import argparse
import json
import os
import sys
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class SmokeFailure(Exception):
    pass


def require(condition, message):
    if not condition:
        raise SmokeFailure(message)


class Client:
    def __init__(self, base, key):
        parsed = urlsplit(base)
        require(parsed.scheme in ("http", "https") and parsed.hostname
                and not parsed.username and not parsed.password
                and not parsed.query and not parsed.fragment
                and parsed.path in ("", "/"), "Use an Adbot origin, not an API path.")
        require(parsed.scheme == "https" or parsed.hostname in ("localhost", "127.0.0.1", "::1"),
                "Use HTTPS for a non-loopback deployment.")
        self.root = base.rstrip("/") + "/api/research/v1"
        self.key = key
        self.opener = build_opener(NoRedirect())

    def request(self, path, data=None):
        headers = {"Authorization": "Bearer " + self.key, "Accept": "application/json"}
        body = None
        if data is not None:
            headers["Content-Type"] = "application/json"
            headers["Idempotency-Key"] = uuid.uuid4().hex
            body = json.dumps(data).encode()
        try:
            with self.opener.open(Request(self.root + path, data=body, headers=headers), timeout=15) as response:
                return json.load(response)
        except HTTPError as exc:
            raise SmokeFailure(f"{path}: HTTP {exc.code}") from None
        except (URLError, TimeoutError, ValueError, OSError):
            raise SmokeFailure(f"{path}: transport or invalid JSON response") from None

    def run(self, question, mode, timeout, **options):
        submitted = self.request("/query", {"question": question, "mode": mode, **options})
        task_id = str(uuid.UUID(submitted["id"]))
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            task = self.request("/tasks/" + task_id)
            if task["status"] in ("completed", "failed", "cancelled"):
                return task, round(time.monotonic() - start, 2)
            time.sleep(2)
        # Do not leave a timed-out smoke test consuming provider resources.
        try:
            self.request("/tasks/" + task_id + "/cancel", {})
        except SmokeFailure:
            pass
        raise SmokeFailure(f"Task {task_id} exceeded smoke-test deadline; cancellation requested.")

    def evidence(self, task_id):
        items = []
        while True:
            page = self.request(f"/tasks/{task_id}/evidence?limit=100&offset={len(items)}")
            batch = page["items"]
            items.extend(batch)
            if len(items) >= page["total"]:
                return items
            require(batch and len(items) < 10000, "Invalid or excessive evidence pagination.")


def validate(task, evidence, shopping=False):
    require(task["status"] == "completed", "Worker did not complete the research task.")
    result = task.get("result", {})
    require(result.get("quality") == "complete", "Research returned partial quality; inspect task notes.")
    require(bool(result.get("answer", "").strip()), "No answer.")
    sources = {s["id"]: s for s in result.get("sources", [])}
    records = {e["id"]: e for e in evidence}
    claims = result.get("claims", [])
    require(bool(claims), "No verified claims.")
    require(len({s.get("independence_group") for s in sources.values() if s.get("independence_group")}) >= 2,
            "Fewer than two independent source groups.")
    for claim in claims:
        require(claim.get("kind") in ("fact", "inference", "recommendation", "conflict"),
                "Unverified excerpt or unknown claim kind.")
        require(bool(claim.get("evidence")), "Claim has no evidence.")
        for identifier in claim["evidence"]:
            record = records.get(identifier)
            require(record and record.get("quote") and record.get("source_id") in sources,
                    "Claim refers to missing evidence or source.")
            source = sources[record["source_id"]]
            require(record.get("source_url") == source.get("url")
                    and record.get("content_hash") == source.get("content_hash"),
                    "Evidence provenance does not match source.")
    metrics = result.get("metrics", {})
    require(metrics.get("model_calls", 0) >= 2 and metrics.get("claims_verified", 0) > 0,
            "No recorded synthesis and verification model calls.")
    if shopping:
        offers = [p for p in result.get("products", [])
                  if p.get("price") is not None and p.get("currency") == "NGN"
                  and p.get("within_budget") is True
                  and p.get("source_id") in sources
                  and p.get("evidence_id") in records
                  and records[p["evidence_id"]].get("source_id") == p["source_id"]
                  and p.get("geographic_match") in ("explicit", "domain_hint", "currency_hint")]
        require(bool(offers), "No sourced, within-budget Nigerian-currency product offer.")
    return metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.getenv("ADBOT_SMOKE_URL", "http://127.0.0.1:5173"))
    parser.add_argument("--timeout", type=int, default=180, help="Maximum polling seconds per task.")
    parser.add_argument("--confirm-live", action="store_true",
                        help="Confirm the deployment uses real providers, not test doubles.")
    args = parser.parse_args()
    key = os.getenv("ADBOT_WORKSPACE_KEY", "")
    if not args.confirm_live or not key or not 10 <= args.timeout <= 900:
        parser.error("Require --confirm-live, ADBOT_WORKSPACE_KEY, and timeout between 10 and 900 seconds.")
    try:
        client = Client(args.base_url, key)
        config = client.request("/providers")
        require(config.get("enabled") and config.get("model_configured") and config.get("providers"),
                "Enable research and configure at least one search provider and an AI model.")
        print("Configured providers:", ", ".join(p["name"] for p in config["providers"]), flush=True)
        cases = [
            ("general", "What is the difference between a solar eclipse and a lunar eclipse?", "quick", {}),
            ("current", "What are recent developments in quantum computing?", "quick", {"freshness": "month"}),
            ("shopping", "Find laptops under ₦1.5 million in Nigeria suitable for AI engineering.", "shopping",
             {"country": "NG"}),
            ("follow_up", "Which of those products is cheapest? Cite the retailer.", "auto", {}),
        ]
        conversation = None
        total_requests = total_http = 0
        failures = []
        for label, question, mode, options in cases:
            if label == "follow_up":
                if not conversation:
                    failures.append("follow_up: shopping conversation unavailable")
                    continue
                options = {**options, "conversation_id": conversation}
            try:
                task, seconds = client.run(question, mode, args.timeout, **options)
                print(f"{label}: task={task['id']} status={task['status']} quality={task.get('quality')} "
                      f"elapsed={seconds}s", flush=True)
                if label == "shopping":
                    conversation = task["conversation_id"]
                if label == "follow_up":
                    require(task["conversation_id"] == conversation and task.get("intent") == "follow_up",
                            "Follow-up lost its conversation or intent.")
                    require(task["question"].get("country") == "NG", "Follow-up lost country constraint.")
                metrics = validate(task, client.evidence(task["id"]), shopping=label in ("shopping", "follow_up"))
                requests = sum(metrics.get("provider_requests", {}).values())
                http = metrics.get("http_requests", 0)
                total_requests += requests
                total_http += http
                print(f"  provider_requests={requests} source_http_requests={http} "
                      f"model_calls={metrics['model_calls']} verified_claims={metrics['claims_verified']}", flush=True)
            except (SmokeFailure, KeyError, TypeError, ValueError) as exc:
                message = str(exc) if isinstance(exc, SmokeFailure) else "Unexpected API response schema."
                failures.append(f"{label}: {message}")
                print("FAIL:", failures[-1], file=sys.stderr, flush=True)
        if not total_requests or not total_http:
            failures.append("No actual provider/source network requests recorded; retry with cold caches.")
        if failures:
            print("LIVE ACCEPTANCE FAILED:", "; ".join(failures), file=sys.stderr)
            return 1
        print("LIVE ACCEPTANCE PASSED (operator-confirmed live deployment; inspect cited facts separately).")
        return 0
    except (SmokeFailure, KeyError, TypeError, ValueError) as exc:
        print("LIVE ACCEPTANCE BLOCKED:", str(exc) if isinstance(exc, SmokeFailure)
              else "Unexpected API response schema.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
