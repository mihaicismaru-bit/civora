#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path

EUCONS_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = EUCONS_ROOT / "web"
CANONICAL_ORIGIN = "https://eucons.ro"

def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def load_contracts():
    return {
        "ia": load_json(WEB_ROOT / "information_architecture.json"),
        "services": load_json(EUCONS_ROOT / "services" / "service_registry.json"),
        "canon": load_json(EUCONS_ROOT / "canon" / "commercial_canon.json"),
        "evidence": load_json(EUCONS_ROOT / "evidence" / "evidence_registry.json"),
        "people": load_json(EUCONS_ROOT / "people" / "people_registry.json"),
        "cases": load_json(EUCONS_ROOT / "cases" / "case_study_registry.json"),
        "ux": load_json(WEB_ROOT / "jtbd_ux_contract.json"),
        "proof": load_json(EUCONS_ROOT / "evidence" / "service_proof_architecture.json"),
    }

def esc(value):
    return html.escape(str(value), quote=True)

def publishable_service_ids(evidence):
    return {
        claim.get("object_ref")
        for claim in evidence.get("claims", [])
        if claim.get("claim_class") == "SERVICE_OFFERING"
        and claim.get("publication_state") == "PUBLISHABLE"
        and claim.get("object_ref")
    }

def publishable_records(records, key):
    return [
        item for item in records.get(key, [])
        if item.get("publication_state") == "PUBLISHABLE"
    ]

def route_file(root: Path, path: str) -> Path:
    clean = path.strip("/")
    return root / clean / "index.html" if clean else root / "index.html"

def relative_asset_prefix(path: str) -> str:
    depth = len([p for p in path.strip("/").split("/") if p])
    return "../" * depth

def canonical(path: str) -> str:
    return CANONICAL_ORIGIN + (path if path.startswith("/") else "/" + path)

def page_head(title: str, description: str, path: str, asset_prefix: str) -> str:
    return f"""<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{esc(canonical(path))}">
  <link rel="stylesheet" href="{esc(asset_prefix)}assets/eucons.css">
  <title>{esc(title)} · Euroconsult</title>
</head>
<body>
<a class="eu-skip-link" href="#continut">Sari la conținut</a>
"""

def nav() -> str:
    links = [
        ("/servicii/", "Soluții"),
        ("/ce-finantare-mi-se-potriveste/", "Finanțare"),
        ("/proiect-in-implementare/", "Implementare"),
        ("/proiecte/", "Proiecte"),
        ("/expertiza/", "Expertiză"),
        ("/despre/", "Despre"),
    ]
    items = "".join(f'<a href="{href}">{esc(label)}</a>' for href, label in links)
    return f"""<header class="eu-header">
  <div class="eu-shell eu-header__inner">
    <a class="eu-wordmark" href="/">EUROCONSULT</a>
    <nav class="eu-nav" aria-label="Navigație principală">{items}</nav>
  </div>
</header>
"""
def footer() -> str:
    links = [
        ("/servicii/", "Servicii"),
        ("/ce-finantare-mi-se-potriveste/", "Ce finanțare mi se potrivește"),
        ("/verifica-proiectul/", "Verifică proiectul"),
        ("/proiect-in-implementare/", "Proiect în implementare"),
        ("/proiect-cu-probleme/", "Proiect cu probleme"),
        ("/finantari/", "Finanțări"),
        ("/pentru-companii/", "Companii"),
        ("/pentru-autoritati-publice/", "Autorități publice"),
        ("/pentru-ong/", "ONG"),
        ("/proiecte/", "Proiecte"),
        ("/echipa/", "Echipa"),
        ("/ghiduri/", "Ghiduri"),
        ("/articole/", "Articole"),
        ("/despre/", "Despre"),
        ("/contact/", "Contact"),
        ("/termeni/", "Termeni"),
        ("/confidentialitate/", "Confidențialitate"),
    ]
    items = "".join(f'<a href="{href}">{esc(label)}</a>' for href, label in links)
    return f"""<footer class="eu-footer">
  <div class="eu-shell eu-stack">
    <strong>EUROCONSULT</strong>
    <div class="eu-footer__links">{items}</div>
    <p class="eu-hint">Informațiile despre finanțări, eligibilitate și rezultate sunt publicate numai cu proveniență și stare verificabile.</p>
  </div>
</footer>
</body>
</html>
"""
def shell(title, description, path, body):
    return page_head(title, description, path, relative_asset_prefix(path)) + nav() + f'<main id="continut">{body}</main>' + footer()

def service_route_map(ia):
    return {item["service_id"]: item["path"] for item in ia.get("service_routes", [])}

def cta_map(canon_data, ia):
    labels = {item["id"]: item["label"] for item in canon_data.get("ctas", [])}
    paths = {item["cta_id"]: item["path"] for item in ia.get("cta_destinations", [])}
    return {key: {"label": labels.get(key, key), "path": paths.get(key, "/evaluare-proiect/")} for key in labels}

def publishable_proof_for_services(data, service_ids):
    wanted = set(service_ids)
    return [
        item for item in data["proof"].get("historical_proof_objects", [])
        if item.get("publication_state") == "PUBLISHABLE"
        and wanted.intersection(item.get("service_ids", []))
    ]

def render_proof_cards(data, service_ids, limit=None):
    records = publishable_proof_for_services(data, service_ids)
    if limit is not None:
        records = records[:limit]
    return "".join(
        f"""<article class="eu-card eu-proof eu-stack">
  <p class="eu-eyebrow">Exemplu documentat</p>
  <p class="eu-card__body">{esc(item["proof_message"])}</p>
  <a href="/proiecte/">Vezi contextul și limitele dovezii</a>
</article>"""
        for item in records
    )

def render_intent_card(journey):
    return f"""<article class="eu-card eu-card--interactive eu-intent-card eu-stack">
  <p class="eu-eyebrow">{esc(journey["eyebrow"])}</p>
  <h2 class="eu-heading-md"><a class="eu-card__link" href="{esc(journey["path"])}">{esc(journey["question"])}</a></h2>
  <p class="eu-card__body">{esc(journey["lead"])}</p>
  <span class="eu-intent-card__action" aria-hidden="true">Vezi traseul →</span>
</article>"""

def render_service_card(service, path):
    return f"""<article class="eu-card eu-card--interactive eu-stack">
  <p class="eu-eyebrow">Serviciu</p>
  <h3 class="eu-heading-md"><a class="eu-card__link" href="{esc(path)}">{esc(service["label"])}</a></h3>
  <p class="eu-card__body">{esc(service["summary"])}</p>
</article>"""

def render_home(data):
    ux = data["ux"]
    journeys = ux.get("journeys", [])
    intent_cards = "".join(render_intent_card(item) for item in journeys)
    all_service_ids = [item["id"] for item in data["services"].get("services", [])]
    proof_cards = render_proof_cards(data, all_service_ids, limit=2)
    trust_items = "".join(f"<li>{esc(item)}</li>" for item in ux["homepage_contract"]["trust_items"])
    body = f"""
<section class="eu-section eu-section--surface eu-hero">
  <div class="eu-shell eu-hero-grid">
    <div class="eu-stack">
      <p class="eu-eyebrow">Consultanță pentru proiecte finanțate</p>
      <p class="eu-hero-question">{esc(ux["homepage_contract"]["hero_question"])}</p>
      <h1 class="eu-heading-xl">{esc(ux["homepage_contract"]["hero_headline"])}</h1>
      <p class="eu-lead">{esc(ux["homepage_contract"]["hero_lead"])}</p>
      <div class="eu-actions">
        <a class="eu-button eu-button--primary" href="/verifica-proiectul/">Cere evaluarea proiectului</a>
        <a class="eu-button eu-button--secondary" href="/solicita-oferta/">Solicită ofertă</a>
      </div>
    </div>
    <aside class="eu-trust-panel eu-stack" aria-label="Cum păstrăm încrederea">
      <p class="eu-eyebrow">Cum lucrăm</p>
      <h2 class="eu-heading-md">O recomandare utilă, fără certitudini inventate.</h2>
      <ul class="eu-check-list">{trust_items}</ul>
    </aside>
  </div>
</section>
<section class="eu-section" aria-labelledby="trasee-home">
  <div class="eu-shell eu-stack">
    <div class="eu-section-heading">
      <div class="eu-stack eu-stack--tight">
        <p class="eu-eyebrow">Alege situația ta</p>
        <h2 class="eu-heading-lg" id="trasee-home">Începe cu decizia pe care trebuie să o iei</h2>
      </div>
      <p class="eu-lead">Nu trebuie să cunoști programul sau numele serviciului. Alege punctul în care te afli acum.</p>
    </div>
    <div class="eu-intent-grid">{intent_cards}</div>
  </div>
</section>
<section class="eu-section eu-section--surface" aria-labelledby="dovezi-home">
  <div class="eu-shell eu-stack">
    <div class="eu-section-heading">
      <div class="eu-stack eu-stack--tight"><p class="eu-eyebrow">Dovadă</p><h2 class="eu-heading-lg" id="dovezi-home">{esc(ux["homepage_contract"]["proof_section_title"])}</h2></div>
      <p class="eu-lead">Arătăm numai roluri și rezultate care pot fi reconstruite din evidențele aprobate. Restul rămâne în așteptarea dovezilor.</p>
    </div>
    <div class="eu-grid">{proof_cards}</div>
    <div class="eu-actions"><a class="eu-button eu-button--quiet" href="/proiecte/">Vezi proiectele documentate</a></div>
  </div>
</section>
<section class="eu-section" aria-labelledby="finantari-home">
  <div class="eu-shell eu-grid">
    <article class="eu-card eu-stack"><span class="eu-badge eu-badge--info">Surse verificate</span><h2 class="eu-heading-md" id="finantari-home">Finanțări cu proveniență și stare vizibile</h2><p class="eu-card__body">O oportunitate apare numai când sursa, versiunea și faptele materiale sunt controlate. O potrivire preliminară nu este eligibilitate confirmată.</p><div><a href="/finantari/">Vezi finanțările verificate</a></div></article>
    <article class="eu-card eu-stack"><span class="eu-badge">Limite explicite</span><h2 class="eu-heading-md">Ce nu promitem</h2><p class="eu-card__body">Nu garantăm obținerea finanțării, nu inventăm criterii sau rezultate și nu afișăm prețuri numerice fără o regulă comercială aprobată.</p><div><a href="/despre/">Cum lucrăm</a></div></article>
  </div>
</section>
<section class="eu-section eu-section--navy">
  <div class="eu-shell eu-stack"><p class="eu-eyebrow">Următorul pas</p><h2 class="eu-heading-lg">Spune-ne ce decizie trebuie luată acum.</h2><p class="eu-lead">Începem cu informațiile minime, apoi cerem doar datele necesare traseului ales.</p><div class="eu-actions"><a class="eu-button eu-button--primary" href="/verifica-proiectul/">Cere evaluarea proiectului</a><a class="eu-button eu-button--secondary" href="/solicita-oferta/">Solicită ofertă</a></div></div>
</section>
"""
    return shell("Consultanță pentru proiecte finanțate", "Trasee Euroconsult pentru finanțare, verificarea proiectului, implementare și remediere.", "/", body)
def render_services_index(data):
    ia, services_data, evidence = data["ia"], data["services"], data["evidence"]
    publishable = publishable_service_ids(evidence)
    routes = service_route_map(ia)
    cards = "".join(render_service_card(s, routes[s["id"]]) for s in services_data.get("services", []) if s.get("id") in publishable and s.get("id") in routes)
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Servicii Euroconsult</p><h1 class="eu-heading-lg">Consultanță structurată pe etapele proiectului</h1><p class="eu-lead">De la analiza rutei de finanțare la implementare, plăți, achiziții, conformitate și remediere. Detaliile comerciale se stabilesc după calificarea situației.</p><div class="eu-grid">{cards}</div><div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">Cere evaluarea proiectului</a><a class="eu-button eu-button--secondary" href="/solicita-oferta/">Solicită ofertă</a></div></div></section>"""
    return shell("Servicii", "Serviciile Euroconsult definite pentru pregătirea și implementarea proiectelor finanțate.", "/servicii/", body)

def render_service_page(data, service, path):
    ctas = cta_map(data["canon"], data["ia"])
    actions = []
    for cta_id in service.get("ctas", []):
        cta = ctas.get(cta_id)
        if cta:
            variant = "eu-button--primary" if not actions else "eu-button--secondary"
            actions.append(f'<a class="eu-button {variant}" href="{esc(cta["path"])}">{esc(cta["label"])}</a>')
    deliverables = "".join(f"<li>{esc(x)}</li>" for x in service.get("deliverables", []))
    process = "".join(f"<li>{esc(x)}</li>" for x in service.get("process", []))
    boundaries = "".join(f"<li>{esc(x)}</li>" for x in service.get("boundaries", []))
    proof_cards = render_proof_cards(data, [service["id"]])
    proof_section = ""
    if proof_cards:
        proof_section = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Dovadă relevantă</p><h2 class="eu-heading-md">Exemple care susțin exact acest tip de intervenție</h2><div class="eu-grid">{proof_cards}</div></div></section>"""
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Serviciu</p><h1 class="eu-heading-lg">{esc(service["label"])}</h1><p class="eu-lead">{esc(service["summary"])}</p><div class="eu-actions">{''.join(actions)}</div></div></section>
<section class="eu-section"><div class="eu-shell eu-grid"><article class="eu-card eu-stack"><h2 class="eu-heading-md">Rezultatul urmărit</h2><p class="eu-card__body">{esc(service["commercial_outcome"])}</p></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Ce livrăm</h2><ul>{deliverables}</ul></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Cum lucrăm</h2><ol>{process}</ol></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Limite explicite</h2><ul>{boundaries}</ul></article></div></section>
{proof_section}
<section class="eu-section eu-section--navy"><div class="eu-shell eu-stack"><h2 class="eu-heading-md">Ai nevoie de acest serviciu?</h2><p class="eu-lead">Înainte de ofertare clarificăm situația, documentele disponibile și aria exactă de lucru.</p><div class="eu-actions">{''.join(actions)}</div></div></section>"""
    return shell(service["label"], service["summary"], path, body)
def render_journey_page(data, journey):
    service_labels = {item["id"]: item["label"] for item in data["services"].get("services", [])}
    route_map = service_route_map(data["ia"])
    service_links = "".join(
        f'<li><a href="{esc(route_map[service_id])}">{esc(service_labels[service_id])}</a></li>'
        for service_id in journey.get("service_ids", [])
        if service_id in service_labels and service_id in route_map
    )
    steps = "".join(f"<li>{esc(item)}</li>" for item in journey.get("steps", []))
    proof_cards = render_proof_cards(data, journey.get("service_ids", []))
    proof_section = ""
    if proof_cards:
        proof_section = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Dovadă relevantă traseului</p><h2 class="eu-heading-md">Ce putem susține din proiecte documentate</h2><div class="eu-grid">{proof_cards}</div></div></section>"""
    body = f"""
<section class="eu-section eu-section--surface">
  <div class="eu-shell eu-reading eu-stack">
    <p class="eu-eyebrow">{esc(journey["eyebrow"])}</p>
    <h1 class="eu-heading-lg">{esc(journey["headline"])}</h1>
    <p class="eu-lead">{esc(journey["lead"])}</p>
    <div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">{esc(journey["cta_label"])}</a><a class="eu-button eu-button--secondary" href="{esc(journey["secondary_path"])}">{esc(journey["secondary_label"])}</a></div>
    <div class="eu-alert eu-alert--info" role="note"><strong>Limită:</strong> {esc(journey["boundary"])}</div>
  </div>
</section>
<section class="eu-section">
  <div class="eu-shell eu-journey-layout">
    <article class="eu-stack"><p class="eu-eyebrow">Cum decurge</p><h2 class="eu-heading-md">Patru pași, fără să ascundem necunoscutele</h2><ol class="eu-step-list">{steps}</ol></article>
    <aside class="eu-card eu-stack"><p class="eu-eyebrow">Servicii relevante</p><h2 class="eu-heading-md">Intervenția se stabilește după evaluare</h2><ul>{service_links}</ul><p class="eu-hint">Nu toate serviciile sunt necesare în fiecare situație.</p></aside>
  </div>
</section>
{proof_section}
<section class="eu-section eu-section--navy"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Primul pas</p><h2 class="eu-heading-md">Începem cu organizația, etapa și obiectivul.</h2><p class="eu-lead">Datele tehnice și financiare sunt cerute progresiv, numai dacă devin necesare traseului ales.</p><div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">{esc(journey["cta_label"])}</a></div></div></section>
"""
    return shell(journey["question"], journey["lead"], journey["path"], body)

def render_audience_page(data, audience, path):
    service_labels = {s["id"]: s["label"] for s in data["services"].get("services", [])}
    route_map = service_route_map(data["ia"])
    problem_cards = []
    for problem in audience.get("problems", []):
        service_links = ", ".join(f'<a href="{esc(route_map[sid])}">{esc(service_labels[sid])}</a>' for sid in problem.get("service_capabilities", []) if sid in service_labels and sid in route_map)
        problem_cards.append(f'<article class="eu-card eu-stack"><h2 class="eu-heading-md">{esc(problem["problem"])}</h2><p class="eu-card__meta">Servicii relevante</p><p class="eu-card__body">{service_links}</p></article>')
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">{esc(audience["label"])}</p><h1 class="eu-heading-lg">{esc(audience["primary_goal"])}</h1><p class="eu-lead">{esc(audience["definition"])}</p><div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">Cere evaluarea proiectului</a><a class="eu-button eu-button--secondary" href="/finantari/">Vezi finanțările verificate</a></div></div></section><section class="eu-section"><div class="eu-shell eu-stack"><h2 class="eu-heading-md">Situații în care putem ajuta</h2><div class="eu-grid">{''.join(problem_cards)}</div></div></section>"""
    return shell(audience["label"], audience["definition"], path, body)

def simple_page(title, eyebrow, lead, path, extra=""):
    body = f'<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">{esc(eyebrow)}</p><h1 class="eu-heading-lg">{esc(title)}</h1><p class="eu-lead">{esc(lead)}</p>{extra}</div></section>'
    return shell(title, lead, path, body)

def render_registry_page(data, kind, path):
    if kind == "people":
        records = publishable_records(data["people"], "people")
        title = "Echipa"
        lead = "Publicăm profiluri profesionale numai după verificarea identității, rolului și competențelor."
    else:
        records = publishable_records(data["cases"], "cases")
        title = "Proiecte și studii de caz"
        lead = "Publicăm rezultate și relații cu clienți numai după verificarea dovezilor și a clasificării de confidențialitate."
    if not records:
        extra = '<div class="eu-alert eu-alert--info" role="status">Nu există încă obiecte verificate pentru proiecția publică. Nu afișăm profiluri sau cazuri demonstrative.</div>'
    else:
        cards = []
        for item in records:
            label = item.get("display_name") or item.get("title") or item.get("name") or "Înregistrare verificată"
            cards.append(f'<article class="eu-card"><h2 class="eu-heading-md">{esc(label)}</h2></article>')
        extra = f'<div class="eu-grid">{"".join(cards)}</div>'
    return simple_page(title, "Dovezi înainte de promovare", lead, path, extra)

def render_funding():
    extra = '<div class="eu-alert eu-alert--info" role="status">Afișăm numai oportunități curente care trec verificarea de sursă, versiune și stare materială. Dacă proiecția nu conține oportunități acționabile, nu completăm pagina cu exemple demonstrative.</div><div class="eu-actions"><a class="eu-button eu-button--primary" href="/ce-finantare-mi-se-potriveste/">Verifică potrivirea investiției</a></div>'
    return simple_page("Finanțări", "Oportunități verificate", "O listă de apeluri nu este suficientă: potrivirea depinde de organizație, investiție și condițiile oficiale aplicabile.", "/finantari/", extra)

def render_lead_page(title, path):
    extra = '<div class="eu-alert eu-alert--warning" role="status">În această versiune de dezvoltare nu colectăm date. Fluxul securizat de transmitere și consimțământ se activează numai după validarea Lead Engine.</div><div class="eu-actions"><a class="eu-button eu-button--secondary" href="/servicii/">Revino la servicii</a></div>'
    return simple_page(title, "Flux comercial", "Pregătim un traseu structurat pentru calificarea cererii fără a transforma site-ul într-un formular generic.", path, extra)

def render_core_pages(data):
    audience_by_id = {a["id"]: a for a in data["canon"].get("audiences", [])}
    journeys = {item["path"]: item for item in data["ux"].get("journeys", [])}
    return {
        "/": render_home(data),
        "/servicii/": render_services_index(data),
        "/finantari/": render_funding(),
        **{path: render_journey_page(data, journey) for path, journey in journeys.items()},
        "/pentru-companii/": render_audience_page(data, audience_by_id["companies_entrepreneurs"], "/pentru-companii/"),
        "/pentru-autoritati-publice/": render_audience_page(data, audience_by_id["public_authorities_institutions"], "/pentru-autoritati-publice/"),
        "/pentru-ong/": render_audience_page(data, audience_by_id["ngos_eligible_organizations"], "/pentru-ong/"),
        "/proiecte/": render_registry_page(data, "cases", "/proiecte/"),
        "/echipa/": render_registry_page(data, "people", "/echipa/"),
        "/expertiza/": simple_page("Expertiză", "Cunoaștere aplicată", "Analizele publice vor lega regulile și oportunitățile verificate de deciziile concrete ale beneficiarilor.", "/expertiza/"),
        "/ghiduri/": simple_page("Ghiduri", "Resurse", "Ghidurile vor fi publicate numai cu surse și limite explicite, fără a transforma o interpretare în regulă administrativă.", "/ghiduri/"),
        "/articole/": simple_page("Articole", "Analize și actualizări", "Conținutul editorial va fi publicat după verificarea faptelor și a relevanței comerciale.", "/articole/"),
        "/resurse/": simple_page("Resurse", "Instrumente pentru beneficiari", "Resursele publice vor fi proiectate pentru decizii, pregătire și controlul implementării.", "/resurse/"),
        "/despre/": simple_page("Despre EUCONS", "Euroconsult", "EUCONS este suprafața comercială prin care sunt prezentate serviciile Euroconsult și, pe măsură ce trec verificarea, oportunități, expertiză și exemple documentate.", "/despre/"),
        "/evaluare-proiect/": render_lead_page("Evaluare proiect", "/evaluare-proiect/"),
        "/solicita-oferta/": render_lead_page("Solicită ofertă", "/solicita-oferta/"),
        "/contact/": simple_page("Contact", "Legătură comercială", "Canalul comercial verificat va fi conectat înainte de producție. Preview-ul nu publică adrese sau date de contact neverificate.", "/contact/"),
        "/termeni/": simple_page("Termeni", "Document juridic", "Textul juridic complet va fi activat înainte de producție. Această versiune noindex nu colectează date și nu oferă servicii contractuale prin site.", "/termeni/"),
        "/confidentialitate/": simple_page("Confidențialitate", "Protecția datelor", "Politica completă de confidențialitate și retenție va fi activată înainte de colectarea oricăror date prin EUCONS.", "/confidentialitate/"),
    }

def build_site(target: Path, data=None):
    data = data or load_contracts()
    target = Path(target)
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    (target / "assets").mkdir(parents=True, exist_ok=True)
    shutil.copy2(WEB_ROOT / "assets" / "eucons.css", target / "assets" / "eucons.css")
    pages = render_core_pages(data)
    publishable = publishable_service_ids(data["evidence"])
    routes = service_route_map(data["ia"])
    for service in data["services"].get("services", []):
        sid = service.get("id")
        if sid in publishable and sid in routes:
            pages[routes[sid]] = render_service_page(data, service, routes[sid])
    for path, content in pages.items():
        out = route_file(target, path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")
    return pages

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default=str(WEB_ROOT / "build"))
    args = parser.parse_args()
    pages = build_site(Path(args.target))
    print(json.dumps({"status": "PASS", "pages": len(pages), "target": args.target}, ensure_ascii=False))

if __name__ == "__main__":
    main()
