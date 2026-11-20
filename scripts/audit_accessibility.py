"""Run a supplied axe-core bundle only in isolated, controlled local fixture pages."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


async def audit(bundle):
    from playwright.async_api import async_playwright

    samples = {
        "semantic_laboratory": (
            ROOT / "backend/testsupport/accessibility.html"
        ).read_text(encoding="utf-8"),
        "accessible_reference": '<!doctype html><html lang="en"><head><title>Public search</title></head><body><main><h1>Search jobs</h1><form aria-label="Job search"><label for="q">Search jobs</label><input id="q" type="search"><button type="submit">Search</button></form></main></body></html>',
        "known_inaccessible_reference": '<!doctype html><html lang="en"><head><title>Known violations</title></head><body><main><h1>Known inaccessible controls</h1><input><div role="checkbox" tabindex="0">Broken checkbox</div></main></body></html>',
    }
    output = {
        "axe_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
        "scenarios": {},
    }
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            for name, html in samples.items():
                await page.set_content(html)
                await page.add_script_tag(path=str(bundle))
                result = await page.evaluate("""async () => {
                  const r=await axe.run(document,{runOnly:{type:'tag',values:['wcag2a','wcag2aa','wcag21a','wcag21aa']}});
                  return {version:axe.version,violations:r.violations.map(v=>({id:v.id,impact:v.impact,description:v.description,help_url:v.helpUrl,targets:v.nodes.map(n=>n.target)})),incomplete:r.incomplete.map(v=>v.id),passes:r.passes.length};
                }""")
                output["scenarios"][name] = result
            assert output["scenarios"]["accessible_reference"]["violations"] == []
            assert {
                v["id"]
                for v in output["scenarios"]["known_inaccessible_reference"][
                    "violations"
                ]
            } >= {"label", "aria-required-attr"}
        finally:
            await browser.close()
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--axe", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(audit(args.axe))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                name: {
                    "version": value["version"],
                    "violation_rules": [v["id"] for v in value["violations"]],
                    "passes": value["passes"],
                }
                for name, value in result["scenarios"].items()
            },
            indent=2,
        )
    )
