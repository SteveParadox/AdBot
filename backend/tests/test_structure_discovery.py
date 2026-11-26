import json
from html import escape

import pytest
from fastapi.responses import HTMLResponse

from app import fixture
from app.agent.classification import AssessmentBatch
from app.agent.contracts import Decision, Verification
from app.agent.model import ModelClient
from app.agent.routing import RouteAssessment
from app.config import settings
from app.jobs import claim
from app.worker import execute
from test_browser import fixture_server  # noqa: F401


CASES = {
    "retail": ("Lagerbestand", "Artikel", "Vorrat", "Amber glass", "12", "Canvas sack", "8", "table"),
    "vacancies": ("Offres en cours", "Poste", "Ville", "Acheteur", "Lyon", "Juriste", "Nice", "list"),
    "library": ("Plantillas reutilizables", "Instrucción", "Uso", "Borrador comercial", "Auditoría", "Ficha logística", "Inventario", "custom"),
    "press": ("Dépêches du jour", "Titre", "Rubrique", "Crue locale", "Météo", "Budget voté", "Politique", "article"),
    "ledger": ("Offene Positionen", "Konto", "Saldo", "Mietkonto", "120 CHF", "Barkasse", "340 CHF", "grid"),
    "manual": ("Referências técnicas", "Operação", "Versão", "Importar", "3.1", "Sincronizar", "4.2", "custom"),
    "dining": ("Plat du jour", "Plat", "Allergènes", "Salade", "Moutarde", "Soupe", "Céleri", "list"),
    "lab": ("Muestras activas", "Muestra", "Estado", "Alpha", "Pendiente", "Beta", "Revisada", "grid"),
}


def record_layout(case, records):
    heading, left, right, *_, layout = case
    pairs = [(escape(a), escape(b)) for a, b in records]
    if layout == "table":
        return f"<table><thead><tr><th>{left}</th><th>{right}</th></tr></thead><tbody>" + "".join(
            f"<tr><td>{a}</td><td>{b}</td></tr>" for a, b in pairs
        ) + "</tbody></table>"
    if layout == "grid":
        return f'<div role="grid"><div role="row"><span role="columnheader">{left}</span><span role="columnheader">{right}</span></div><div role="rowgroup">' + "".join(
            f'<div role="row"><span role="gridcell">{a}</span><span role="gridcell">{b}</span></div>' for a, b in pairs
        ) + "</div></div>"
    tag, outer = {"article": ("article", "aside"), "list": ("li", "ul"), "custom": ("x-entry", "div")}[layout]
    rows = []
    for index, (a, b) in enumerate(pairs):
        fields = ((right, b), (left, a)) if heading == "Plantillas reutilizables" and index else ((left, a), (right, b))
        (first, second) = fields
        rows.append(f'<{tag}><strong aria-label="{first[0]}">{first[1]}</strong><span aria-label="{second[0]}">{second[1]}</span></{tag}>')
    return f"<{outer}>{''.join(rows)}</{outer}>"


@fixture.app.get("/structure-check/{site}", response_class=HTMLResponse)
def structure_home(site: str):
    title = CASES[site][0]
    return (f'<nav><a href="/structure-check/{site}/preview">{title} Preview</a>'
            f'<a href="/structure-check/{site}/live">{title}</a></nav>')


@fixture.app.get("/structure-check/{site}/{source}", response_class=HTMLResponse)
def structure_source(site: str, source: str):
    case = CASES[site]
    title, _, _, a, b, c, d, _ = case
    # One case changes its rows in place and another has no count metadata.
    if site in {"ledger", "lab"} and source == "live":
        first = record_layout(case, [(a, b)])
        second = record_layout(case, [(c, d)])
        if site == "lab":
            return (f'<section><h1>{title}</h1><p>Disponibles 2</p><div id="listing">{first}</div></section>'
                    '<div style="height:2000px"></div><script>'
                    f'addEventListener("scroll",()=>{{document.getElementById("listing").innerHTML={json.dumps(second)}}},{{once:true}})'
                    '</script>')
        return (f'<section><h1>{title}</h1><p>Positionen insgesamt 2</p><div id="listing">{first}</div>'
                '<button id="forward">Weiter</button></section><script>'
                f'document.getElementById("forward").onclick=e=>{{document.getElementById("listing").innerHTML={json.dumps(second)};e.target.disabled=true}}'
                '</script>')
    count = "" if site == "manual" else "<p>Registros disponibles 2</p>"
    layout = record_layout(case, [(a, b), (c, d)] if source == "live" else [(a, "preview"), (c, "preview")])
    return f'<section><h1>{title}</h1>{count}{layout}</section>'


@pytest.mark.browser
@pytest.mark.parametrize("site", [*CASES, "incomplete", "misleading", "wrong-source"])
async def test_unfamiliar_authorized_sites(client, target, fixture_server, monkeypatch, site):  # noqa: F811
    monkeypatch.setattr(settings(), "ai_provider", "local")
    mode = site if site in {"incomplete", "misleading", "wrong-source"} else "matching"
    site = "ledger" if mode == "incomplete" else "retail" if mode in {"misleading", "wrong-source"} else site
    title, left, right, a, b, c, d, _ = CASES[site]
    exhaustive = site in {"ledger", "lab", "retail"}
    objective = f"List all entries for {title} with {left} and {right}" if exhaustive else f"Report {left} and {right} for {title}"
    if site == "library":
        objective += " for audit work"
    dispatched = []

    async def answer(self, kind, payload, schema, *_args, **_kwargs):
        if kind == "plan":
            return schema.model_validate(payload["seed_plan"])
        if kind == "route":
            return RouteAssessment(exhaustive_inventory=False, entity_phrase="")
        if kind == "classify":
            assert site == "library" and "audit work" in payload["objective"]
            return AssessmentBatch(records=[
                {"id": record["id"], "classification": "match" if "Auditoría" in record["excerpts"] else "excluded",
                 "evidence": 2} for record in payload["records"]
            ])
        if kind == "verify":
            capture = payload["captured_records"]
            assert {key: data["fields"] for key, data in capture["records"].items()} == {
                a: {left: a, right: "preview" if mode == "wrong-source" else b},
                c: {left: c, right: "preview" if mode == "wrong-source" else d},
            }
            evidence = [e["id"] for e in payload["evidence"] if e["id"].startswith("capture-")]
            assert evidence
            if site == "library":
                assert capture["records"][a]["classification_evidence"] == b
                assert capture["records"][c]["classification"] == "excluded"
            # A model claiming verification with a fabricated citation cannot complete.
            return Verification(complete=mode != "wrong-source", explanation="Observed source and records reviewed", checks=[
                {"criterion": criterion, "met": mode != "wrong-source", "evidence_ids": ["invented"] if mode == "misleading" else evidence}
                for criterion in payload["success_criteria"]
            ])
        assert kind == "decide", kind
        page = payload["current_page"]
        defaults = {"observation": "Authorized page observed", "reason": "Use the observed source", "confidence": 1,
                    "expected_result": "Observe the requested records"}
        if not page["url"].endswith(("/live", "/preview")):
            destination = title + " Preview" if mode == "wrong-source" else title
            link = next(item for item in page["elements"] if item["name"] == destination)
            dispatched.append(link["href"])
            return Decision(decision="NAVIGATE", url=link["href"], **defaults)
        groups = page.get("record_groups", [])
        group = next(g for g in groups if g["examples"] and [s["label"] for s in g["examples"][0]] == [left, right])
        count = payload.get("captured_record_count", 0)
        if count == 0 or (count == 1 and group["examples"][0][0]["value"] == c):
            quote = next((q for q in group["context"] if q.endswith(" 2")), None)
            return Decision(decision="CAPTURE_RECORDS", **defaults, capture={
                "group": group["id"], "identity": 1, "exhaustive": exhaustive, "total_quote": quote,
                "restrict_to_objective": site == "library",
                "fields": [{"name": left, "position": 1}, {"name": right, "position": 2}],
            })
        if count == 1 and mode != "incomplete":
            if site == "lab":
                return Decision(decision="SCROLL", **defaults)
            return Decision(decision="CLICK", target={"element_id": next_control(page)["element_id"]}, **defaults)
        evidence = [e["id"] for e in payload["session_memory"]["evidence"] if e["id"].startswith("capture-")]
        return Decision(decision="COMPLETE", claims=[{"text": f"Observed entries for {title}", "evidence_ids": evidence}], **defaults)

    monkeypatch.setattr(ModelClient, "request", answer)
    registration = {key: target[key] for key in ("name", "allowed_domains", "configuration")}
    registration.update(base_url=f"http://127.0.0.1:8765/structure-check/{site}", authorized=True)
    registration["configuration"].update(screenshots=False, max_duration_seconds=150)
    assert client.patch(f"/api/websites/{target['id']}", json=registration).status_code == 200
    job = client.post("/api/agent/tasks", json={"website_id": target["id"], "objective": objective, "max_steps": 5}).json()["id"]
    await execute(*claim())
    result = client.get(f"/api/agent/tasks/{job}").json()
    expected_status = "completed" if mode == "matching" else "failed"
    if result["status"] != expected_status:
        steps = client.get(f"/api/agent/tasks/{job}/steps").json()["items"]
        pytest.fail(str((result.get("error_message"), [(s["status"], s["decision"], s["outcome"].get("error")) for s in steps])))
    assert len(dispatched) == 1 and dispatched[0].endswith("/preview" if mode == "wrong-source" else "/live")
    assert result["execution"]["strategy"] == result["planning"]["route"] == "structured_discovery"
    data = result["result"]
    assert data["verification"]["complete"] is (mode == "matching")
    assert [r["fields"] for r in data["structured_records"]] == (
        [{left: a, right: b}] if mode == "incomplete" or site == "library" else
        [{left: a, right: "preview"}, {left: c, right: "preview"}] if mode == "wrong-source" else
        [{left: a, right: b}, {left: c, right: d}]
    )


def next_control(page):
    return next(item for item in page["elements"] if item["name"] == "Weiter")
