#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EUCONS_ROOT = HERE.parents[1]
DEFAULT_SCHEMA = HERE / "forms_definition.json"
DEFAULT_CONTRACT = HERE / "form_contract.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<link rel="stylesheet" href="/assets/eucons.css">
<title>{esc(title)} · Euroconsult</title>
</head>
<body>
<a class="eu-skip-link" href="#continut">Sari la conținut</a>
<header class="eu-header"><div class="eu-shell eu-header__inner"><a class="eu-wordmark" href="/">EUROCONSULT</a></div></header>
<main id="continut">{body}</main>
<footer class="eu-footer"><div class="eu-shell eu-stack"><strong>EUROCONSULT</strong><p class="eu-hint">Cercetare distinctă de fluxurile comerciale EUCONS. Răspunsurile analitice nu intră în CRM.</p></div></footer>
</body></html>"""


def warning() -> str:
    return '<p class="eu-hint"><strong>Important:</strong> Nu introduceți nume, e-mail, telefon, CNP, adresă, numele angajatorului sau alte informații care pot identifica o persoană.</p>'


def input_field(field: dict[str, Any], disabled: bool) -> str:
    fid = esc(field["id"])
    label = esc(field["label"])
    attrs = ' disabled' if disabled else ''
    required = ' required' if field.get("required", True) else ''
    note = warning() if field.get("pii_warning") else ''
    ftype = field["type"]
    if ftype == "select":
        options = '<option value="">Selectați</option>' + ''.join(f'<option value="{esc(v)}">{esc(v)}</option>' for v in field["options"])
        control = f'<select id="{fid}" name="{fid}"{required}{attrs}>{options}</select>'
    elif ftype == "textarea":
        control = f'<textarea id="{fid}" name="{fid}" maxlength="{int(field.get("max_chars",500))}"{required}{attrs}></textarea>'
    else:
        control = f'<input id="{fid}" name="{fid}" type="text" maxlength="{int(field.get("max_chars",160))}"{required}{attrs}>'
    return f'<div class="eu-stack eu-stack--tight"><label for="{fid}"><strong>{label}</strong></label>{control}{note}</div>'


def question_field(question: dict[str, Any], disabled: bool) -> str:
    qid = esc(question["id"])
    label = esc(question["label"])
    attrs = ' disabled' if disabled else ''
    qtype = question["type"]
    if qtype == "rating":
        controls = ''.join(f'<label><input type="radio" name="{qid}" value="{i}"{attrs}> {i}</label>' for i in range(int(question["min"]), int(question["max"]) + 1))
    elif qtype in {"single", "boolean"}:
        options = question.get("options", ["da", "nu"])
        controls = ''.join(f'<label><input type="radio" name="{qid}" value="{esc(v)}"{attrs}> {esc(v)}</label>' for v in options)
    elif qtype == "multi":
        controls = ''.join(f'<label><input type="checkbox" name="{qid}" value="{esc(v)}"{attrs}> {esc(v)}</label>' for v in question["options"])
    elif qtype == "rating_matrix":
        rows = []
        for key, row_label in question["rows"].items():
            ratings = ''.join(f'<label><input type="radio" name="{esc(qid)}__{esc(key)}" value="{i}"{attrs}> {i}</label>' for i in range(int(question["min"]), int(question["max"]) + 1))
            rows.append(f'<div class="eu-stack eu-stack--tight"><span>{esc(row_label)}</span><div>{ratings}</div></div>')
        controls = ''.join(rows)
    elif qtype == "textarea":
        controls = f'<textarea name="{qid}" maxlength="{int(question.get("max_chars",500))}"{attrs}></textarea>' + warning()
    else:
        controls = f'<input type="text" name="{qid}" maxlength="{int(question.get("max_chars",160))}"{attrs}>' + (warning() if question.get("pii_warning") else '')
    note = f'<p class="eu-hint">{esc(question["note"])}</p>' if question.get("note") else ''
    return f'<fieldset class="eu-card eu-stack"><legend><strong>{qid}</strong> — {label}</legend>{controls}{note}</fieldset>'


def render_form(form: dict[str, Any], schema: dict[str, Any], contract: dict[str, Any]) -> str:
    enabled = contract.get("production_enabled") is True
    disabled = not enabled
    notice = schema["common_notice"]
    profile = ''.join(input_field(field, disabled) for field in form["profile"])
    questions = ''.join(question_field(q, disabled) for q in form["questions"])
    gate = '' if enabled else '<div class="eu-alert eu-alert--warning" role="status"><strong>Colectarea nu este activată.</strong> Aceasta este versiunea de validare. Trimiterea răspunsurilor rămâne blocată până la completarea operatorului, contactului GDPR, storage-ului de cercetare și testelor de integrare.</div>'
    ack_disabled = ' disabled' if disabled else ''
    submit_disabled = ' disabled' if disabled else ''
    body = f"""
<section class="eu-section eu-section--surface"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">AI4WORK STEP · cercetare primară</p>
<h1 class="eu-heading-lg">{esc(form['title'])}</h1>
{gate}
<div class="eu-card eu-stack"><h2 class="eu-heading-md">{esc(notice['title'])}</h2><p>{esc(notice['body'])}</p><p><strong>Operator:</strong> {esc(notice['operator'])}</p><p><strong>Contact protecția datelor:</strong> {esc(notice['privacy_contact'])}</p></div>
<form class="eu-stack" method="post">
<label><input type="checkbox" name="notice_read_and_voluntary_participation" value="true"{ack_disabled}> {esc(notice['acknowledgement_label'])}</label>
<h2 class="eu-heading-md">Profil statistic minim</h2>{profile}
<h2 class="eu-heading-md">Întrebări</h2>{questions}
<button class="eu-button eu-button--primary" type="submit"{submit_disabled}>Trimite răspunsul</button>
</form>
</div></section>"""
    return page(form["title"], body)


def render_landing(schema: dict[str, Any], contract: dict[str, Any]) -> str:
    enabled = contract.get("production_enabled") is True
    status = "Colectarea este activă." if enabled else "Colectarea este încă blocată până la validarea completă a fluxului de confidențialitate și stocare."
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">Cercetare independentă</p><h1 class="eu-heading-lg">AI4WORK STEP — analiză de nevoi</h1><p class="eu-lead">Două instrumente distincte măsoară experiența adulților și observațiile angajatorilor. Răspunsurile nu sunt folosite ca lead-uri comerciale și nu sunt legate de CRM.</p><div class="eu-alert eu-alert--info">{esc(status)}</div>
<div class="eu-actions"><a class="eu-button eu-button--secondary" href="/cercetare/ai4work-step/adulti/">Chestionar adulți</a><a class="eu-button eu-button--secondary" href="/cercetare/ai4work-step/angajatori/">Chestionar angajatori</a></div>
</div></section>"""
    return page("AI4WORK STEP — cercetare", body)


def write_route(target: Path, route: str, content: str) -> Path:
    out = target / route.strip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


def build(target: Path, schema_path: Path = DEFAULT_SCHEMA, contract_path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    schema = load_json(schema_path)
    contract = load_json(contract_path)
    if contract.get("crm_integration") != "FORBIDDEN" or contract.get("commercial_analytics") != "FORBIDDEN":
        raise RuntimeError("research isolation contract is not fail-closed")
    if contract.get("production_enabled") is True:
        notice = schema["common_notice"]
        if "[" in notice.get("operator", "") or "[" in notice.get("privacy_contact", ""):
            raise RuntimeError("production cannot be enabled with unresolved operator/privacy placeholders")
        raise RuntimeError("production collection requires an HTTP/storage adapter binding; static builder cannot enable submission")
    target.mkdir(parents=True, exist_ok=True)
    outputs = [write_route(target, contract["public_routes"]["landing"], render_landing(schema, contract))]
    by_id = {form["id"]: form for form in schema["forms"]}
    outputs.append(write_route(target, contract["public_routes"]["adults"], render_form(by_id["AI4WORK_ADULTS_V1"], schema, contract)))
    outputs.append(write_route(target, contract["public_routes"]["employers"], render_form(by_id["AI4WORK_EMPLOYERS_V1"], schema, contract)))
    return {"status":"PASS_PREVIEW_ONLY", "pages":[str(path) for path in outputs], "production_enabled":False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.target), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
