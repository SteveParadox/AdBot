"""Isolated browser observation measurements; never uses a provider or real DB."""

import argparse
import asyncio
import json
import sys
import time
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.update(
    ADBOT_API_KEYS="semantic-benchmark-local-key-0000000000",
    ADBOT_DATABASE_URL="sqlite://",
    ADBOT_AI_PROVIDER="disabled",
    ADBOT_ENVIRONMENT="development",
)


def owned_browser_processes():
    """Count browser helpers descended from this benchmark, excluding user apps."""
    if os.name != "nt":
        return None
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress",
        ],
        capture_output=True,
        text=True,
        check=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    processes = json.loads(completed.stdout)
    descendants = {os.getpid()}
    while True:
        found = {
            p["ProcessId"] for p in processes if p["ParentProcessId"] in descendants
        }
        if found <= descendants:
            break
        descendants |= found
    return sum(
        p["ProcessId"] in descendants
        and any(
            s in p["Name"].lower()
            for s in ("chrome", "headless", "firefox", "minibrowser", "playwright")
        )
        for p in processes
    )


async def measure():
    cpu_started = time.process_time()
    from playwright.async_api import async_playwright
    from app.agent.observe import Observer
    from app.agent.model import bounded_request_text
    from app.agent.contracts import Decision

    html = (ROOT / "backend/testsupport/accessibility.html").read_text(encoding="utf-8")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await page.set_content(html)
            observer = Observer()
            results = []
            for _ in range(3):
                start = time.perf_counter()
                observation = await observer.observe(page, "t1")
                elapsed = (time.perf_counter() - start) * 1000
                request = bounded_request_text(
                    "Fixed benchmark system instructions",
                    "decide",
                    {
                        "objective": "Search backend jobs, filter remote, sort newest and inspect preferences",
                        "current_page": observation,
                    },
                    Decision,
                    18000,
                )
                bounded = json.loads(request)["current_page"]
                results.append(
                    {
                        "milliseconds": round(elapsed, 3),
                        "characters": len(json.dumps(observation, ensure_ascii=False)),
                        "controls": len(observation["elements"]),
                        "roles": sorted({e["role"] for e in observation["elements"]}),
                        "diagnostics": observation.get("observation_metrics"),
                        "bounded_request_characters": len(request),
                        "bounded_controls": len(bounded["elements"]),
                    }
                )
            result = {
                "scenario": "Controlled semantic laboratory; Chromium; three repeated full observations; no LLM",
                "samples": results,
                "owned_browser_processes": owned_browser_processes(),
                "browser_contexts": len(browser.contexts),
                "pages": len(page.context.pages),
            }
        finally:
            await browser.close()
        result["owned_browser_processes_after_close"] = owned_browser_processes()
        result["python_process_cpu_seconds"] = time.process_time() - cpu_started
        return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    value = asyncio.run(measure())
    content = json.dumps(value, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content + "\n", encoding="utf-8")
    print(content)
