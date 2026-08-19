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
        ("/servicii/", "Servicii"),
        ("/finantari/", "Finanțări"),
        ("/proiecte/", "Proiecte"),
        ("/echipa/", "Echipa"),
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
    <p class="eu-hint">Versiune de dezvoltare: indexarea publică și colectarea de date rămân dezactivate până la porțile de acceptanță.</p>
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

def render_service_card(service, path):
    return f"""<article class="eu-card eu-card--interactive eu-stack">
  <p class="eu-eyebrow">Serviciu</p>
  <h3 class="eu-heading-md"><a class="eu-card__link" href="{esc(path)}">{esc(service["label"])}</a></h3>
  <p class="eu-card__body">{esc(service["summary"])}</p>
</article>"""

def render_home(data):
    ia, services_data, canon_data, evidence = data["ia"], data["services"], data["canon"], data["evidence"]
    publishable = publishable_service_ids(evidence)
    routes = service_route_map(ia)
    services = [s for s in services_data.get("services", []) if s.get("id") in publishable]
    service_cards = "".join(render_service_card(s, routes[s["id"]]) for s in services if s.get("id") in routes)

    audience_path = {
        "companies_entrepreneurs": "/pentru-companii/",
        "public_authorities_institutions": "/pentru-autoritati-publice/",
        "ngos_eligible_organizations": "/pentru-ong/",
        "existing_beneficiaries": "/servicii/implementare-raportare/",
    }
    audiences = []
    for audience in canon_data.get("audiences", []):
        if audience["id"] == "existing_beneficiaries":
            continue
        audiences.append(f"""<article class="eu-card eu-card--interactive eu-stack">
  <p class="eu-eyebrow">Pentru</p>
  <h3 class="eu-heading-md"><a class="eu-card__link" href="{esc(audience_path[audience["id"]])}">{esc(audience["label"])}</a></h3>
  <p class="eu-card__body">{esc(audience["primary_goal"])}</p>
</article>""")
    body = f"""
<section class="eu-section eu-section--surface">
  <div class="eu-shell eu-stack">
    <p class="eu-eyebrow">Consultanță pentru proiecte finanțate</p>
    <h1 class="eu-heading-xl">De la investiție la implementare, cu pași și limite explicite.</h1>
    <p class="eu-lead">Euroconsult oferă servicii pentru identificarea rutei de finanțare, pregătirea proiectului și controlul implementării. Publicăm numai servicii și informații care au trecut regulile interne de verificare.</p>
    <div class="eu-actions">
      <a class="eu-button eu-button--primary" href="/evaluare-proiect/">Cere evaluarea proiectului</a>
      <a class="eu-button eu-button--secondary" href="/solicita-oferta/">Solicită ofertă</a>
    </div>
  </div>
</section>
<section class="eu-section" aria-labelledby="servicii-home">
  <div class="eu-shell eu-stack">
    <div class="eu-stack"><p class="eu-eyebrow">Servicii</p><h2 class="eu-heading-lg" id="servicii-home">Unde putem interveni</h2><p class="eu-lead">Fiecare serviciu are livrabile, proces și limite definite înainte de ofertare.</p></div>
    <div class="eu-grid">{service_cards}</div>
    <div class="eu-actions"><a class="eu-button eu-button--quiet" href="/servicii/">Vezi toate serviciile</a></div>
  </div>
</section>
<section class="eu-section eu-section--surface" aria-labelledby="audiente-home">
  <div class="eu-shell eu-stack"><p class="eu-eyebrow">Traseu potrivit situației tale</p><h2 class="eu-heading-lg" id="audiente-home">Începe de la tipul organizației</h2><div class="eu-grid">{''.join(audiences)}</div></div>
</section>
<section class="eu-section" aria-labelledby="finantari-home">
  <div class="eu-shell eu-grid">
    <article class="eu-card eu-stack"><span class="eu-badge eu-badge--info">Verificare înainte de publicare</span><h2 class="eu-heading-md" id="finantari-home">Finanțări fără statut inventat</h2><p class="eu-card__body">O oportunitate va apărea pe EUCONS numai după ce statusul, sursa și faptele materiale sunt disponibile printr-o proiecție verificată. Până atunci nu afișăm apeluri demonstrative.</p><div><a href="/finantari/">Vezi suprafața de finanțări</a></div></article>
    <article class="eu-card eu-stack"><span class="eu-badge">Abordare</span><h2 class="eu-heading-md">Ce nu promitem</h2><p class="eu-card__body">Nu garantăm obținerea finanțării, nu inventăm criterii sau rezultate și nu publicăm prețuri numerice fără o regulă comercială aprobată.</p><div><a href="/despre/">Cum lucrăm</a></div></article>
  </div>
</section>
<section class="eu-section eu-section--navy">
  <div class="eu-shell eu-stack"><p class="eu-eyebrow">Următorul pas</p><h2 class="eu-heading-lg">Spune-ne ce vrei să finanțezi sau ce proiect trebuie stabilizat.</h2><p class="eu-lead">Fluxurile de evaluare și ofertare sunt construite separat de conținutul editorial, astfel încât informațiile comerciale să rămână trasabile.</p><div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">Cere evaluarea proiectului</a><a class="eu-button eu-button--secondary" href="/solicita-oferta/">Solicită ofertă</a></div></div>
</section>
"""
    return shell("Consultanță pentru proiecte finanțate", "Servicii Euroconsult pentru finanțare, pregătirea proiectelor, implementare și conformitate.", "/", body)

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
    body = f"""<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Serviciu</p><h1 class="eu-heading-lg">{esc(service["label"])}</h1><p class="eu-lead">{esc(service["summary"])}</p><div class="eu-actions">{''.join(actions)}</div></div></section>
<section class="eu-section"><div class="eu-shell eu-grid"><article class="eu-card eu-stack"><h2 class="eu-heading-md">Rezultatul urmărit</h2><p class="eu-card__body">{esc(service["commercial_outcome"])}</p></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Ce livrăm</h2><ul>{deliverables}</ul></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Cum lucrăm</h2><ol>{process}</ol></article><article class="eu-card eu-stack"><h2 class="eu-heading-md">Limite explicite</h2><ul>{boundaries}</ul></article></div></section>
<section class="eu-section eu-section--navy"><div class="eu-shell eu-stack"><h2 class="eu-heading-md">Ai nevoie de acest serviciu?</h2><p class="eu-lead">Înainte de ofertare clarificăm situația, documentele disponibile și aria exactă de lucru.</p><div class="eu-actions">{''.join(actions)}</div></div></section>"""
    return shell(service["label"], service["summary"], path, body)

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
    extra = '<div class="eu-alert eu-alert--info" role="status">Bridge-ul verificat PARTENER → EUCONS se activează în E09. Până atunci nu publicăm apeluri, bugete sau termene ca date comerciale.</div><div class="eu-actions"><a class="eu-button eu-button--primary" href="/evaluare-proiect/">Cere evaluarea proiectului</a></div>'
    return simple_page("Finanțări", "Oportunități verificate", "Această suprafață va afișa numai oportunități cu proveniență și stare materială verificabile.", "/finantari/", extra)

def render_lead_page(title, path):
    extra = '<div class="eu-alert eu-alert--warning" role="status">În această versiune de dezvoltare nu colectăm date. Fluxul securizat de transmitere și consimțământ se activează numai după validarea Lead Engine.</div><div class="eu-actions"><a class="eu-button eu-button--secondary" href="/servicii/">Revino la servicii</a></div>'
    return simple_page(title, "Flux comercial", "Pregătim un traseu structurat pentru calificarea cererii fără a transforma site-ul într-un formular generic.", path, extra)

def render_core_pages(data):
    audience_by_id = {a["id"]: a for a in data["canon"].get("audiences", [])}
    return {
        "/": render_home(data),
        "/servicii/": render_services_index(data),
        "/finantari/": render_funding(),
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
