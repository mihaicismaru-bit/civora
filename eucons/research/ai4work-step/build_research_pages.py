#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
DEFAULT_SCHEMA = HERE / "forms_definition.json"
DEFAULT_CONTRACT = HERE / "form_contract.json"
DEFAULT_MANIFEST = HERE / "PROD_ACTIVATION_MANIFEST_DRAFT.json"
DEFAULT_CLIENT = HERE / "research_form.js"
RESEARCH_ENDPOINT = "https://api.eucons.ro/research/ai4work/v1/submit"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def activation_enabled(contract: dict[str, Any], manifest: dict[str, Any]) -> bool:
    return (
        contract.get("production_enabled") is True
        and manifest.get("approved_for_prod") is True
        and manifest.get("collection_enabled") is True
        and manifest.get("deploy_authorized") is False
        and manifest.get("real_collection_authorized") is True
        and bool(str(manifest.get("explicit_user_approval_reference") or "").strip())
    )


def _unfrozen(value: Any) -> bool:
    text = str(value or "").strip()
    return not text or text.startswith(("TO_BE_", "OPEN_", "UNRESOLVED_"))


def validate_enabled_notice(contract: dict[str, Any]) -> None:
    notice = contract.get("pre_form_notice") or {}
    required = [
        "operator_legal_name",
        "operator_contact_details",
        "privacy_contact",
        "purpose_summary",
        "legal_basis",
        "recipients_summary",
        "international_transfer_summary",
        "retention_summary",
        "rights_summary",
        "complaint_summary",
        "provision_consequence_summary",
        "automated_decision_summary",
    ]
    missing = [key for key in required if _unfrozen(notice.get(key))]
    legal_basis = str(notice.get("legal_basis") or "").lower()
    if ("6(1)(f)" in legal_basis or "6 alin. (1) lit. (f)" in legal_basis or "legitimate" in legal_basis or "interes legitim" in legal_basis) and _unfrozen(notice.get("legitimate_interest_summary")):
        missing.append("legitimate_interest_summary")
    if missing:
        raise RuntimeError(f"enabled research form lacks frozen Article 13 notice fields: {sorted(set(missing))}")


def page(title: str, body: str, *, form_client: bool = False) -> str:
    script = '<script defer src="/assets/ai4work-research.js"></script>' if form_client else ""
    return f"""<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<meta name="referrer" content="no-referrer">
<link rel="stylesheet" href="/assets/eucons.css">
{script}
<title>{esc(title)} · Euroconsult</title>
</head>
<body>
<a class="eu-skip-link" href="#continut">Sari la conținut</a>
<header class="eu-header"><div class="eu-shell eu-header__inner"><a class="eu-wordmark" href="/">EUROCONSULT</a></div></header>
<main id="continut">{body}</main>
<footer class="eu-footer"><div class="eu-shell eu-stack"><strong>EUROCONSULT</strong><p class="eu-hint">Cercetare distinctă de fluxurile comerciale EUCONS. Răspunsurile analitice nu intră în CRM și nu sunt folosite pentru tracking comercial.</p></div></footer>
</body></html>"""


def input_field(field: dict[str, Any], disabled: bool) -> str:
    fid = esc(field["id"])
    label = esc(field["label"])
    attrs = ' disabled' if disabled else ''
    required = ' required' if field.get("required", True) else ''
    ftype = field["type"]
    if ftype != "select":
        raise RuntimeError(f"analytical profile field {field['id']} must be a controlled select, got {ftype}")
    options = '<option value="">Selectați</option>' + ''.join(
        f'<option value="{esc(v)}">{esc(v)}</option>' for v in field["options"]
    )
    control = f'<select id="{fid}" name="{fid}" data-profile-field="{fid}"{required}{attrs}>{options}</select>'
    return f'<div class="eu-stack eu-stack--tight"><label for="{fid}"><strong>{label}</strong></label>{control}</div>'


def _required(question: dict[str, Any]) -> str:
    return ' required' if question.get("required", True) else ''


def _dependency_attrs(question: dict[str, Any]) -> str:
    dependency = question.get("depends_on")
    if not dependency:
        return ""
    expected = dependency.get("equals")
    if isinstance(expected, bool):
        expected = "true" if expected else "false"
    return (
        f' data-depends-field="{esc(dependency.get("field", ""))}"'
        f' data-depends-value="{esc(expected)}" hidden'
    )


def question_field(question: dict[str, Any], disabled: bool) -> str:
    qid = esc(question["id"])
    label = esc(question["label"])
    attrs = ' disabled' if disabled else ''
    required = _required(question)
    qtype = question["type"]
    if qtype == "rating":
        controls = ''.join(
            f'<label><input type="radio" name="{qid}" value="{i}"{required}{attrs}> {i}</label>'
            for i in range(int(question["min"]), int(question["max"]) + 1)
        )
    elif qtype == "boolean":
        controls = ''.join(
            f'<label><input type="radio" name="{qid}" value="{value}"{required}{attrs}> {text}</label>'
            for value, text in (("true", "Da"), ("false", "Nu"))
        )
    elif qtype == "single":
        controls = ''.join(
            f'<label><input type="radio" name="{qid}" value="{esc(v)}"{required}{attrs}> {esc(v)}</label>'
            for v in question["options"]
        )
    elif qtype == "select":
        options = '<option value="">Selectați</option>' + ''.join(
            f'<option value="{esc(v)}">{esc(v)}</option>' for v in question["options"]
        )
        controls = f'<select id="{qid}" name="{qid}"{required}{attrs}>{options}</select>'
    elif qtype == "multi":
        controls = ''.join(
            f'<label><input type="checkbox" name="{qid}" value="{esc(v)}"{attrs}> {esc(v)}</label>'
            for v in question["options"]
        )
    elif qtype == "rating_matrix":
        rows = []
        for key, row_label in question["rows"].items():
            ratings = ''.join(
                f'<label><input type="radio" name="{qid}__{esc(key)}" value="{i}"{required}{attrs}> {i}</label>'
                for i in range(int(question["min"]), int(question["max"]) + 1)
            )
            rows.append(
                f'<div class="eu-stack eu-stack--tight" data-matrix-row="{esc(key)}"><span>{esc(row_label)}</span><div>{ratings}</div></div>'
            )
        controls = ''.join(rows)
    else:
        raise RuntimeError(
            f"analytical question {question['id']} uses unsupported/non-minimised field type {qtype}"
        )
    note = f'<p class="eu-hint">{esc(question["note"])}</p>' if question.get("note") else ''
    dependency = _dependency_attrs(question)
    return (
        f'<fieldset class="eu-card eu-stack" data-question-id="{qid}" data-question-type="{esc(qtype)}"{dependency}>'
        f'<legend><strong>{qid}</strong> — {label}</legend>{controls}{note}</fieldset>'
    )


def _notice_value(pre_notice: dict[str, Any], key: str, fallback: str = "DE APROBAT ÎNAINTE DE ACTIVAREA COLECTĂRII") -> str:
    value = pre_notice.get(key)
    return fallback if _unfrozen(value) else str(value)


def render_form(
    form: dict[str, Any], schema: dict[str, Any], contract: dict[str, Any], *, enabled: bool
) -> str:
    disabled = not enabled
    notice = schema["common_notice"]
    pre_notice = contract.get("pre_form_notice") or {}
    operator_name = _notice_value(pre_notice, "operator_legal_name", "DE STABILIT ÎNAINTE DE ACTIVAREA COLECTĂRII")
    operator_contact = _notice_value(pre_notice, "operator_contact_details")
    privacy_contact = _notice_value(pre_notice, "privacy_contact", "DE COMPLETAT ÎNAINTE DE ACTIVAREA COLECTĂRII")
    purpose = _notice_value(pre_notice, "purpose_summary")
    legal_basis = _notice_value(pre_notice, "legal_basis")
    legitimate_interest = _notice_value(pre_notice, "legitimate_interest_summary")
    recipients = _notice_value(pre_notice, "recipients_summary")
    transfers = _notice_value(pre_notice, "international_transfer_summary")
    retention = _notice_value(pre_notice, "retention_summary")
    rights = _notice_value(pre_notice, "rights_summary")
    complaint = _notice_value(pre_notice, "complaint_summary")
    consequence = _notice_value(pre_notice, "provision_consequence_summary")
    automated = _notice_value(pre_notice, "automated_decision_summary")
    profile = ''.join(input_field(field, disabled) for field in form["profile"])
    questions = ''.join(question_field(q, disabled) for q in form["questions"])
    gate = '' if enabled else '<div class="eu-alert eu-alert--warning" role="status"><strong>Colectarea nu este activată.</strong> Pagina este pregătită tehnic, dar trimiterea răspunsurilor rămâne blocată până la aprobarea integrală a manifestului PROD și activarea explicită a mediului.</div>'
    ack_disabled = ' disabled' if disabled else ''
    submit_disabled = ' disabled' if disabled else ''
    body = f"""
<section class="eu-section eu-section--surface"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">AI4WORK STEP · cercetare primară</p>
<h1 class="eu-heading-lg">{esc(form['title'])}</h1>
{gate}
<div class="eu-card eu-stack"><h2 class="eu-heading-md">{esc(notice['title'])}</h2><p>{esc(notice['body'])}</p><p><strong>Operator:</strong> {esc(operator_name)}</p><p><strong>Date de contact operator:</strong> {esc(operator_contact)}</p><p><strong>Contact protecția datelor:</strong> {esc(privacy_contact)}</p><p><strong>Scop:</strong> {esc(purpose)}</p><p><strong>Temei juridic:</strong> {esc(legal_basis)}</p><p><strong>Interes legitim propus, dacă acesta este temeiul final:</strong> {esc(legitimate_interest)}</p><p><strong>Destinatari/categorii de destinatari:</strong> {esc(recipients)}</p><p><strong>Transferuri internaționale:</strong> {esc(transfers)}</p><p><strong>Păstrare:</strong> {esc(retention)}</p><p><strong>Drepturi:</strong> {esc(rights)}</p><p><strong>Plângere:</strong> {esc(complaint)}</p><p><strong>Caracter voluntar și consecințele necompletării:</strong> {esc(consequence)}</p><p><strong>Decizii automate/profilare:</strong> {esc(automated)}</p></div>
<form class="eu-stack" data-ai4work-research-form data-form-id="{esc(form['id'])}" data-endpoint="{esc(RESEARCH_ENDPOINT)}" data-collection-enabled="{'true' if enabled else 'false'}">
<label><input type="checkbox" name="notice_read_and_voluntary_participation" value="true" required{ack_disabled}> {esc(notice['acknowledgement_label'])}</label>
<h2 class="eu-heading-md">Profil statistic minim</h2>{profile}
<h2 class="eu-heading-md">Întrebări</h2>{questions}
<button class="eu-button eu-button--primary" type="button" data-ai4work-submit{submit_disabled}>Trimite răspunsul</button>
<p class="eu-hint" role="status" aria-live="polite" data-ai4work-status></p>
<p class="eu-card eu-hint" data-ai4work-receipt hidden></p>
</form>
</div></section>"""
    return page(form["title"], body, form_client=True)


def render_landing(schema: dict[str, Any], contract: dict[str, Any], *, enabled: bool) -> str:
    status = "Colectarea este activă." if enabled else "Colectarea este încă blocată până la validarea completă a fluxului de confidențialitate, stocare și aprobare PROD."
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-reading eu-stack">
<p class="eu-eyebrow">Cercetare independentă</p><h1 class="eu-heading-lg">AI4WORK STEP — analiză de nevoi</h1><p class="eu-lead">Două instrumente distincte măsoară experiența adulților și observațiile angajatorilor. Răspunsurile nu sunt folosite ca lead-uri comerciale, nu sunt legate de CRM și nu folosesc tracking comercial.</p><div class="eu-alert eu-alert--info">{esc(status)}</div>
<div class="eu-actions"><a class="eu-button eu-button--secondary" href="/cercetare/ai4work-step/adulti/">Chestionar adulți</a><a class="eu-button eu-button--secondary" href="/cercetare/ai4work-step/angajatori/">Chestionar angajatori</a></div>
</div></section>"""
    return page("AI4WORK STEP — cercetare", body)


def write_route(target: Path, route: str, content: str) -> Path:
    out = target / route.strip("/") / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return out


def build(
    target: Path,
    schema_path: Path = DEFAULT_SCHEMA,
    contract_path: Path = DEFAULT_CONTRACT,
    manifest_path: Path = DEFAULT_MANIFEST,
    client_path: Path = DEFAULT_CLIENT,
) -> dict[str, Any]:
    schema = load_json(schema_path)
    contract = load_json(contract_path)
    manifest = load_json(manifest_path)
    if contract.get("crm_integration") != "FORBIDDEN" or contract.get("commercial_analytics") != "FORBIDDEN":
        raise RuntimeError("research isolation contract is not fail-closed")
    enabled = activation_enabled(contract, manifest)
    if enabled:
        validate_enabled_notice(contract)
    target.mkdir(parents=True, exist_ok=True)
    outputs = [write_route(target, contract["public_routes"]["landing"], render_landing(schema, contract, enabled=enabled))]
    by_id = {form["id"]: form for form in schema["forms"]}
    outputs.append(write_route(target, contract["public_routes"]["adults"], render_form(by_id["AI4WORK_ADULTS_V1"], schema, contract, enabled=enabled)))
    outputs.append(write_route(target, contract["public_routes"]["employers"], render_form(by_id["AI4WORK_EMPLOYERS_V1"], schema, contract, enabled=enabled)))
    assets = target / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(client_path, assets / "ai4work-research.js")
    return {
        "status": "PASS_ENABLED" if enabled else "PASS_FAIL_CLOSED",
        "pages": [str(path) for path in outputs],
        "production_enabled": enabled,
        "endpoint": RESEARCH_ENDPOINT,
        "test_twin_evidence_eligible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.target), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())