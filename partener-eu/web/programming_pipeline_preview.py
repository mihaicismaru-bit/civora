#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PREVIEW_ID = "PROGRAMMING_PIPELINE_ACCESSIBLE_PREVIEW_V1"
PROJECTION_ID = "PROGRAMMING_PIPELINE_PUBLIC_PROJECTION_V1"
ALLOWED_STATES = {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
NON_AUTH_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)
MISSING_LABELS = {
    "exact_call_or_topic_identifier": "identificatorul exact al apelului sau topicului",
    "current_official_exact_call_endpoint": "endpointul oficial curent al apelului",
    "explicit_current_official_call_status": "statusul curent explicit confirmat de autoritatea oficială",
    "call_specific_deadline_budget_eligibility_and_geography": "termenul, bugetul, eligibilitatea și geografia specifice apelului",
    "semantic_reconciliation": "reconcilierea semantică a dovezii curente",
    "programme_specific_official_2028_2034_authority": "o autoritate oficială specifică programului pentru 2028–2034",
    "bounded_official_programme_endpoint": "un endpoint oficial bounded specific programului",
    "programme_specific_semantic_reconciliation": "reconcilierea semantică specifică programului",
}
STATE_LABELS = {
    "PROPOSAL": "Propunere",
    "CONSULTATION": "Consultare",
    "PROGRAMMING_PROCESS": "Programare în pregătire",
}
CONFIDENCE_LABELS = {"HIGH": "Ridicat", "MEDIUM": "Mediu", "LOW": "Scăzut"}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def _https_url(value: Any) -> str:
    text = str(value or "")
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"preview refuses non-HTTPS or empty authority URL: {text!r}")
    return text


def _require_non_authorizing(obj: dict[str, Any], label: str) -> None:
    if obj.get("market_intelligence_only") is not True:
        raise ValueError(f"{label}: market_intelligence_only must be true")
    if obj.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: publication_effect must remain NONE")
    for key in NON_AUTH_FLAGS:
        if obj.get(key) is not False:
            raise ValueError(f"{label}: authorizing drift: {key}")


def _validate_projection(data: dict[str, Any]) -> None:
    if data.get("projection_id") != PROJECTION_ID:
        raise ValueError("projection identity mismatch")
    if data.get("surface") != "PROGRAMARE_VIITOARE_PIPELINE":
        raise ValueError("projection surface mismatch")
    if data.get("surface_state") != "PREVIEW_READ_ONLY_NOT_PUBLISHED":
        raise ValueError("projection is not preview-only")
    if data.get("seo_indexing_state") != "NOINDEX_PREVIEW_ONLY":
        raise ValueError("projection SEO boundary drift")
    if data.get("reader_copy_generated") is not False:
        raise ValueError("projection unexpectedly claims reader copy")
    _require_non_authorizing(data, "projection")
    if data.get("call_alert_authorized") is not False:
        raise ValueError("projection call_alert_authorized drift")

    cards = data.get("cards")
    if not isinstance(cards, list) or len(cards) != data.get("card_count"):
        raise ValueError("projection card inventory mismatch")
    for card in cards:
        if not isinstance(card, dict):
            raise ValueError("projection card must be object")
        source_id = str(card.get("source_id") or "")
        if not source_id:
            raise ValueError("projection card missing source_id")
        if card.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{source_id}: forbidden observation state")
        if card.get("open_confirmation_state") != "NOT_CONFIRMED_MISSING_EXACT_CALL_EVIDENCE":
            raise ValueError(f"{source_id}: open-confirmation boundary drift")
        _require_non_authorizing(card, f"card {source_id}")
        _https_url(card.get("authority_url"))
        supporting = card.get("supporting_authority_url")
        if supporting:
            _https_url(supporting)

    gaps = data.get("coverage_gaps")
    if not isinstance(gaps, list) or len(gaps) != data.get("coverage_gap_count"):
        raise ValueError("coverage-gap inventory mismatch")
    for gap in gaps:
        if not isinstance(gap, dict) or not gap.get("programme_id"):
            raise ValueError("coverage gap missing programme_id")
        _require_non_authorizing(gap, f"coverage gap {gap.get('programme_id')}")
        if gap.get("open_confirmation_state") != "NOT_APPLICABLE_PROGRAMME_SPECIFIC_PIPELINE_NOT_ADMITTED":
            raise ValueError(f"coverage gap {gap.get('programme_id')}: open boundary drift")


def _human_missing(items: list[Any]) -> str:
    if not items:
        return "<li>confirmare oficială suplimentară înainte de orice clasificare ca apel</li>"
    return "".join(f"<li>{_e(MISSING_LABELS.get(str(item), str(item)))}</li>" for item in items)


def _health_label(card: dict[str, Any]) -> tuple[str, str]:
    state = str((card.get("source_health") or {}).get("health_state") or "UNKNOWN")
    if state == "HEALTHY":
        return "Sursă curentă verificată", "health-ok"
    if state.startswith("DEGRADED"):
        return "Sursă curentă degradată", "health-degraded"
    return "Stare sursă necunoscută", "health-unknown"


def _card(card: dict[str, Any]) -> str:
    state = str(card["observation_state"])
    state_label = STATE_LABELS[state]
    health_label, health_class = _health_label(card)
    confidence = CONFIDENCE_LABELS.get(str(card.get("confidence") or ""), str(card.get("confidence") or "Nespecificat"))
    authority = _https_url(card.get("authority_url"))
    supporting = card.get("supporting_authority_url")
    consultation_end = card.get("consultation_end_date")
    consultation_line = ""
    if state == "CONSULTATION" and consultation_end:
        consultation_line = (
            f'<div class="datum"><span>Termen al consultării</span><strong>{_e(consultation_end)}</strong>'
            '<small>Nu este termen de apel de finanțare.</small></div>'
        )
    supporting_link = (
        f'<a class="source secondary" href="{_e(_https_url(supporting))}" target="_blank" rel="noreferrer">'
        "Sursă oficială de corroborare ↗</a>"
        if supporting
        else ""
    )
    return f'''<article class="pipeline-card" data-state="{_e(state)}">
  <div class="card-top">
    <span class="state state-{_e(state.lower())}">{_e(state_label)}</span>
    <span class="health {health_class}">{_e(health_label)}</span>
  </div>
  <h2>{_e(card.get("programme") or card.get("source_id"))}</h2>
  <div class="facts">
    <div class="datum"><span>Observat</span><strong>{_e(card.get("observed_at") or "—")}</strong></div>
    <div class="datum"><span>Încredere</span><strong>{_e(confidence)}</strong></div>
    <div class="datum"><span>Stadiu</span><strong>{_e(state_label)}</strong><small>Nu este apel deschis.</small></div>
    {consultation_line}
  </div>
  <div class="proof">
    <h3>Ce lipsește pentru un apel confirmat</h3>
    <ul>{_human_missing(list(card.get("missing_for_open_confirmation") or []))}</ul>
  </div>
  <div class="sources">
    <a class="source" href="{_e(authority)}" target="_blank" rel="noreferrer">Sursa oficială ↗</a>
    {supporting_link}
  </div>
</article>'''


def _gap(gap: dict[str, Any]) -> str:
    pid = str(gap.get("programme_id"))
    evidence = gap.get("framework_evidence") or []
    links = []
    for item in evidence:
        if isinstance(item, dict) and item.get("authority_url"):
            url = _https_url(item.get("authority_url"))
            links.append(
                f'<a class="source secondary" href="{_e(url)}" target="_blank" rel="noreferrer">'
                f'{_e(item.get("source_id") or "Sursă oficială")} ↗</a>'
            )
    return f'''<article class="gap-card">
  <div class="card-top"><span class="state state-gap">Acoperire incompletă</span><span class="health health-degraded">Încredere scăzută</span></div>
  <h2>{_e(pid)} · 2028–2034</h2>
  <p>Programul apare în contextul cadrului viitor, dar nu este încă admis ca acoperire specifică programului pentru 2028–2034.</p>
  <div class="proof">
    <h3>Ce lipsește pentru admiterea în Programare viitoare</h3>
    <ul>{_human_missing(list(gap.get("missing_for_programme_specific_admission") or []))}</ul>
  </div>
  <div class="sources">{''.join(links)}</div>
</article>'''


def render(data: dict[str, Any]) -> str:
    _validate_projection(data)
    cards = data["cards"]
    gaps = data["coverage_gaps"]
    observed_at = _e(data.get("observed_at") or "—")
    reconciliation = _e(data.get("reconciliation_state") or "—")
    cards_html = "".join(_card(card) for card in cards)
    gaps_html = "".join(_gap(gap) for gap in gaps) or '<p class="empty">Nu există goluri de acoperire în acest preview.</p>'
    return f'''<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>PARTENER.EU · Programare viitoare · Preview</title>
<style>
:root{{--bg:#f6f7f9;--panel:#fff;--ink:#17202a;--muted:#65717e;--line:#dfe4ea;--accent:#1546a0;--warn:#8a4b00;--good:#166534;--radius:18px}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}}
a{{color:var(--accent)}} .wrap{{max-width:1120px;margin:auto;padding:20px}} header{{padding:28px 0 18px}}
.eyebrow{{font-weight:800;text-transform:uppercase;letter-spacing:.08em;font-size:.78rem;color:var(--accent)}}
h1{{font-size:clamp(2rem,7vw,4rem);line-height:1.02;margin:.35rem 0 1rem}} .lead{{max-width:820px;font-size:1.08rem;color:var(--muted)}}
.guard{{background:#fff8e8;border:1px solid #f0d49c;border-radius:var(--radius);padding:16px 18px;margin:18px 0}}
.guard strong{{display:block;margin-bottom:4px}} .summary{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:18px 0}}
.metric{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:13px}} .metric span{{display:block;color:var(--muted);font-size:.8rem}} .metric strong{{font-size:1.15rem}}
.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0}} button{{font:inherit;border:1px solid var(--line);background:var(--panel);padding:9px 12px;border-radius:999px;cursor:pointer}}
button[aria-pressed="true"]{{border-color:var(--accent);box-shadow:0 0 0 2px rgba(21,70,160,.12)}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
.pipeline-card,.gap-card{{background:var(--panel);border:1px solid var(--line);border-radius:var(--radius);padding:18px}}
.card-top{{display:flex;gap:8px;justify-content:space-between;align-items:center;flex-wrap:wrap}} .state,.health{{font-size:.78rem;font-weight:800;border-radius:999px;padding:5px 8px}}
.state{{background:#eef3ff;color:#183b83}} .state-gap{{background:#fff3df;color:#754200}} .health-ok{{background:#eaf7ee;color:var(--good)}} .health-degraded{{background:#fff0df;color:var(--warn)}} .health-unknown{{background:#eef0f2;color:#48515b}}
h2{{font-size:1.2rem;line-height:1.25;margin:14px 0}} h3{{font-size:.9rem;margin:.2rem 0 .4rem}}
.facts{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}} .datum{{border-top:1px solid var(--line);padding-top:8px}}
.datum span,.datum small{{display:block;color:var(--muted);font-size:.78rem}} .proof{{margin-top:14px;background:#f8fafc;border-radius:12px;padding:12px}}
.proof ul{{margin:.4rem 0 0;padding-left:1.2rem}} .sources{{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px}} .source{{font-weight:750;text-decoration:none}} .source.secondary{{font-weight:600}}
section{{margin:34px 0}} .section-head p{{color:var(--muted);max-width:760px}} .empty{{color:var(--muted)}} footer{{border-top:1px solid var(--line);margin-top:40px;padding:20px 0;color:var(--muted);font-size:.85rem}}
[hidden]{{display:none!important}}
@media(max-width:760px){{.wrap{{padding:14px}}.summary{{grid-template-columns:repeat(2,minmax(0,1fr))}}.grid{{grid-template-columns:1fr}}.facts{{grid-template-columns:1fr}}h1{{font-size:2.35rem}}}}
@media(prefers-reduced-motion:reduce){{*{{scroll-behavior:auto!important}}}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <div class="eyebrow">PARTENER.EU · Programare viitoare · preview read-only</div>
  <h1>Ce se pregătește după 2027</h1>
  <p class="lead">Semnale oficiale despre propuneri, consultări și procese de programare. Această suprafață separă deliberat programarea viitoare de apelurile de finanțare deschise.</p>
  <div class="guard" role="note"><strong>Nu este o listă de apeluri deschise.</strong> Niciun card de aici nu autorizează status de apel, termen de depunere, buget sau eligibilitate. Pentru OPEN este necesară dovadă oficială exactă la nivel de apel/topic și reconciliere semantică.</div>
  <div class="summary" aria-label="Rezumat preview">
    <div class="metric"><span>Semnale de programare</span><strong>{len(cards)}</strong></div>
    <div class="metric"><span>Surse curente sănătoase</span><strong>{_e(data.get("healthy_source_count"))}</strong></div>
    <div class="metric"><span>Surse degradate</span><strong>{_e(data.get("degraded_source_count"))}</strong></div>
    <div class="metric"><span>Goluri de acoperire</span><strong>{len(gaps)}</strong></div>
  </div>
  <p class="lead"><small>Observație: {observed_at} · Reconciliere: {reconciliation}</small></p>
</header>

<nav class="filters" aria-label="Filtre după stadiul programării">
  <button type="button" data-filter="ALL" aria-pressed="true">Toate</button>
  <button type="button" data-filter="PROPOSAL" aria-pressed="false">Propuneri</button>
  <button type="button" data-filter="CONSULTATION" aria-pressed="false">Consultări</button>
  <button type="button" data-filter="PROGRAMMING_PROCESS" aria-pressed="false">Programare în pregătire</button>
</nav>

<main>
<section aria-labelledby="pipeline-title">
  <div class="section-head"><h2 id="pipeline-title">Programare viitoare verificată</h2><p>Ordinea reflectă prioritatea de monitorizare din engine. Starea sursei și nivelul de încredere sunt afișate separat de stadiul programării.</p></div>
  <div class="grid" id="pipeline-grid">{cards_html}</div>
</section>

<section aria-labelledby="gaps-title">
  <div class="section-head"><h2 id="gaps-title">Ce încă nu este confirmat la nivel de program</h2><p>Aceste intrări sunt păstrate ca research-watch. Nu sunt promovate la acoperire 2028–2034 fără autoritate oficială specifică programului.</p></div>
  <div class="grid">{gaps_html}</div>
</section>
</main>

<footer>Preview tehnic noindex · {PREVIEW_ID} · nicio publicare sau distribuție autorizată.</footer>
</div>
<script>
(()=>{{const buttons=[...document.querySelectorAll('[data-filter]')];const cards=[...document.querySelectorAll('.pipeline-card')];for(const button of buttons){{button.addEventListener('click',()=>{{const value=button.dataset.filter;for(const b of buttons)b.setAttribute('aria-pressed',String(b===button));for(const card of cards)card.hidden=value!=='ALL'&&card.dataset.state!==value;}})}}}})();
</script>
</body>
</html>
'''


def build_manifest(*, projection_raw: bytes, html_raw: bytes, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "preview_id": PREVIEW_ID,
        "projection_id": data.get("projection_id"),
        "generated_from_run_id": data.get("generated_from_run_id"),
        "observed_at": data.get("observed_at"),
        "projection_sha256": _sha256(projection_raw),
        "preview_html_sha256": _sha256(html_raw),
        "card_count": data.get("card_count"),
        "coverage_gap_count": data.get("coverage_gap_count"),
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "publication_effect": "NONE",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Render a noindex, accessible, non-authorizing PROGRAMARE VIITOARE preview.")
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()

    projection_raw = args.projection.read_bytes()
    data = json.loads(projection_raw.decode("utf-8"))
    rendered = render(data)
    html_raw = rendered.encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(html_raw)
    manifest = build_manifest(projection_raw=projection_raw, html_raw=html_raw, data=data)
    args.manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
