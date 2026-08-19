#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

IA_PATH = WEB / "information_architecture.json"
SITE_PATH = WEB / "public_site.json"
SERVICES_PATH = ROOT / "services" / "service_registry.json"
COMMERCIAL_PATH = ROOT / "canon" / "commercial_canon.json"
EVIDENCE_PATH = ROOT / "evidence" / "evidence_registry.json"
PEOPLE_PATH = ROOT / "people" / "people_registry.json"
CASES_PATH = ROOT / "cases" / "case_study_registry.json"
CSS_PATH = WEB / "assets" / "eucons.css"


class PublicSiteBuildError(ValueError):
    pass


def fail(message: str) -> None:
    raise PublicSiteBuildError(message)


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing build input {path.relative_to(ROOT)}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def esc(value) -> str:
    return html.escape(str(value), quote=True)


def path_to_output(output: Path, route_path: str) -> Path:
    if route_path == "/":
        return output / "index.html"
    return output / route_path.strip("/") / "index.html"


def canonical_url(origin: str, route_path: str) -> str:
    return urljoin(origin.rstrip("/") + "/", route_path.lstrip("/"))


def rel_asset(route_path: str, asset: str) -> str:
    depth = len([part for part in route_path.strip("/").split("/") if part])
    return "../" * depth + asset


def active_evidence_map(evidence: dict) -> dict[str, dict]:
    return {
        item.get("id"): item
        for item in evidence.get("evidence_items", [])
        if item.get("status") == "ACTIVE" and item.get("id")
    }


def valid_claim(claim: dict, evidence_by_id: dict[str, dict]) -> bool:
    if claim.get("publication_state") != "PUBLISHABLE":
        return False
    claim_class = claim.get("claim_class")
    evidence_ids = claim.get("evidence_ids") or []
    if not evidence_ids:
        return False
    for evidence_id in evidence_ids:
        item = evidence_by_id.get(evidence_id)
        if not item:
            return False
        if claim_class not in (item.get("allowed_claim_classes") or []):
            return False
    return True


def publishable_service_ids(evidence: dict) -> set[str]:
    evidence_by_id = active_evidence_map(evidence)
    return {
        claim.get("object_ref")
        for claim in evidence.get("claims", [])
        if claim.get("claim_class") == "SERVICE_OFFERING"
        and claim.get("object_ref")
        and valid_claim(claim, evidence_by_id)
    }


def publishable_people(people: dict) -> list[dict]:
    return [item for item in people.get("people", []) if item.get("publication_state") == "PUBLISHABLE"]


def publishable_cases(cases: dict) -> list[dict]:
    return [item for item in cases.get("cases", []) if item.get("publication_state") == "PUBLISHABLE"]


def route_maps(ia: dict):
    core = {item["id"]: item for item in ia.get("core_routes", [])}
    services = {item["service_id"]: item for item in ia.get("service_routes", [])}
    ctas = {item["cta_id"]: item for item in ia.get("cta_destinations", [])}
    return core, services, ctas


def nav_label(route_id: str) -> str:
    labels = {
        "services_index": "Servicii",
        "funding_index": "Finanțări",
        "projects_index": "Proiecte",
        "team_index": "Echipa",
        "expertise": "Expertiză",
        "about": "Despre",
        "project_evaluation": "Evaluare proiect",
        "request_offer": "Solicită ofertă",
        "contact": "Contact",
    }
    return labels.get(route_id, route_id.replace("_", " ").title())


def page_shell(*, route_path: str, title: str, description: str, body: str, ia: dict, core: dict) -> str:
    origin = ia["canonical_origin"]
    css = rel_asset(route_path, "assets/eucons.css")
    nav = []
    for route_id in ia["navigation"]["primary"]:
        route = core[route_id]
        nav.append(f'<a href="{esc(route["path"])}">{esc(nav_label(route_id))}</a>')
    nav.append(f'<a class="eu-button eu-button--primary" href="{esc(core["project_evaluation"]["path"])}">Evaluare proiect</a>')
    footer_links = []
    for route_id in ia["navigation"]["footer"]:
        route = core[route_id]
        footer_links.append(f'<a href="{esc(route["path"])}">{esc(nav_label(route_id))}</a>')
    return f'''<!doctype html>
<html lang="ro">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>{esc(title)} · Euroconsult</title>
  <meta name="description" content="{esc(description)}">
  <link rel="canonical" href="{esc(canonical_url(origin, route_path))}">
  <link rel="stylesheet" href="{esc(css)}">
</head>
<body data-eucons-phase="E08" data-build-state="DEVELOPMENT_NOINDEX">
<a class="eu-skip-link" href="#main-content">Sari la conținut</a>
<header class="eu-header">
  <div class="eu-shell eu-header__inner">
    <a class="eu-wordmark" href="/">EUROCONSULT</a>
    <nav class="eu-nav" aria-label="Navigație principală">{''.join(nav)}</nav>
  </div>
</header>
<main id="main-content">{body}</main>
<footer class="eu-footer">
  <div class="eu-shell eu-stack">
    <strong>EUROCONSULT</strong>
    <p class="eu-reading">Consultanță pentru finanțare, pregătire și implementare de proiecte. Conținutul de dezvoltare este publicat numai din registrele EUCONS admise.</p>
    <nav class="eu-footer__links" aria-label="Navigație subsol">{''.join(footer_links)}</nav>
  </div>
</footer>
</body>
</html>
'''


def section(title: str, content: str, eyebrow: str | None = None, surface: bool = False) -> str:
    cls = "eu-section eu-section--surface" if surface else "eu-section"
    eyebrow_html = f'<p class="eu-eyebrow">{esc(eyebrow)}</p>' if eyebrow else ""
    return f'<section class="{cls}"><div class="eu-shell eu-stack">{eyebrow_html}<h2 class="eu-heading-lg">{esc(title)}</h2>{content}</div></section>'


def list_items(items: list[str]) -> str:
    return "<ul>" + "".join(f"<li>{esc(item)}</li>" for item in items) + "</ul>"


def cta_link(cta_id: str, commercial: dict, cta_routes: dict, class_name: str = "eu-button eu-button--primary") -> str:
    cta = next((item for item in commercial.get("ctas", []) if item.get("id") == cta_id), None)
    route = cta_routes.get(cta_id)
    if not cta or not route:
        fail(f"unknown CTA {cta_id}")
    return f'<a class="{class_name}" href="{esc(route["path"])}">{esc(cta["label"])}</a>'


def homepage(site, services, commercial, people, cases, ia, core, cta_routes) -> str:
    home = site["homepage"]
    hero = f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack">
      <p class="eu-eyebrow">{esc(home["eyebrow"])}</p>
      <h1 class="eu-heading-xl">{esc(home["headline"])}</h1>
      <p class="eu-lead">{esc(home["lead"])}</p>
      <div class="eu-actions">{cta_link(home["primary_cta"], commercial, cta_routes)}{cta_link(home["secondary_cta"], commercial, cta_routes, "eu-button eu-button--secondary")}</div>
    </div></section>'''
    cards = []
    for service in services[: home["service_limit"]]:
        route = next(item for item in ia["service_routes"] if item["service_id"] == service["id"])
        cards.append(f'''<article class="eu-card eu-card--interactive">
          <span class="eu-badge eu-badge--info">Serviciu</span>
          <h3 class="eu-heading-md">{esc(service["label"])}</h3>
          <p class="eu-card__body">{esc(service["summary"])}</p>
          <p><a class="eu-card__link" href="{esc(route["path"])}">Vezi serviciul</a></p>
        </article>''')
    service_section = section("Servicii pentru întregul ciclu al proiectului", '<div class="eu-grid">' + "".join(cards) + "</div>", "Ce putem face")

    audience_by_id = {item["id"]: item for item in commercial.get("audiences", [])}
    audience_route_by_id = {item.get("audience_id"): item for item in ia.get("core_routes", []) if item.get("surface") == "AUDIENCE"}
    audience_cards = []
    for audience_id in home["audience_ids"]:
        audience = audience_by_id[audience_id]
        route = audience_route_by_id.get(audience_id)
        href = route["path"] if route else core["project_evaluation"]["path"]
        audience_cards.append(f'''<article class="eu-card eu-card--interactive">
          <h3 class="eu-heading-md">{esc(audience["label"])}</h3>
          <p class="eu-card__body">{esc(audience["primary_goal"])}</p>
          <p><a class="eu-card__link" href="{esc(href)}">Vezi traseul potrivit</a></p>
        </article>''')
    audience_section = section("Pornește de la situația organizației tale", '<div class="eu-grid">' + "".join(audience_cards) + "</div>", "Pentru cine lucrăm", surface=True)

    conditional = ""
    if cases:
        case_cards = "".join(
            f'<article class="eu-card"><h3 class="eu-heading-md">{esc(item.get("public_title") or item.get("title") or "Studiu de caz")}</h3></article>'
            for item in cases[:3]
        )
        conditional += section("Studii de caz verificate", f'<div class="eu-grid">{case_cards}</div>', "Dovezi")
    if people:
        people_cards = "".join(
            f'<article class="eu-card"><h3 class="eu-heading-md">{esc(item.get("display_name") or item.get("name") or "Expert")}</h3></article>'
            for item in people[:4]
        )
        conditional += section("Oamenii din spatele serviciilor", f'<div class="eu-grid">{people_cards}</div>', "Echipa", surface=bool(cases))

    close = section(
        "Ai o investiție, un proiect în pregătire sau o implementare care are nevoie de control?",
        f'<p class="eu-lead">Începem cu o evaluare a situației și definim serviciul numai după ce avem date suficiente.</p><div class="eu-actions">{cta_link("request_project_evaluation", commercial, cta_routes)}{cta_link("request_offer", commercial, cta_routes, "eu-button eu-button--secondary")}</div>',
        "Următorul pas",
        surface=not bool(people),
    )
    return hero + service_section + audience_section + conditional + close


def services_index(services, ia) -> str:
    cards = []
    route_by_service = {item["service_id"]: item for item in ia["service_routes"]}
    for service in services:
        route = route_by_service[service["id"]]
        cards.append(f'''<article class="eu-card eu-card--interactive"><span class="eu-badge eu-badge--info">Serviciu</span><h3 class="eu-heading-md">{esc(service["label"])}</h3><p class="eu-card__body">{esc(service["summary"])}</p><p><a class="eu-card__link" href="{esc(route["path"])}">Detalii serviciu</a></p></article>''')
    return section("Servicii Euroconsult", '<p class="eu-lead">Serviciile de mai jos sunt publicate din registrul canonic și includ limite explicite; niciun serviciu nu implică o garanție de finanțare sau aprobare.</p><div class="eu-grid">' + "".join(cards) + "</div>", "Oferta de consultanță", surface=True)


def service_page(service, site, commercial, cta_routes) -> str:
    actions = "".join(cta_link(cta, commercial, cta_routes, "eu-button eu-button--primary" if idx == 0 else "eu-button eu-button--secondary") for idx, cta in enumerate(service.get("ctas", [])[:2]))
    hero = f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">{esc(site["service_page"]["eyebrow"])}</p><h1 class="eu-heading-xl">{esc(service["label"])}</h1><p class="eu-lead">{esc(service["summary"])}</p><div class="eu-actions">{actions}</div></div></section>'''
    parts = [
        section(site["service_page"]["deliverables_heading"], list_items(service.get("deliverables", []))),
        section(site["service_page"]["process_heading"], list_items(service.get("process", [])), surface=True),
        section(site["service_page"]["boundaries_heading"], list_items(service.get("boundaries", []))),
        section(site["service_page"]["evidence_heading"], list_items(service.get("evidence_requirements", [])), surface=True),
    ]
    return hero + "".join(parts)


def audience_page(audience, relevant_services, site, commercial, cta_routes, ia) -> str:
    problems = "".join(f'<article class="eu-card"><h3 class="eu-heading-md">{esc(item["problem"])}</h3></article>' for item in audience.get("problems", []))
    route_by_service = {item["service_id"]: item for item in ia["service_routes"]}
    service_cards = "".join(
        f'<article class="eu-card eu-card--interactive"><h3 class="eu-heading-md">{esc(service["label"])}</h3><p class="eu-card__body">{esc(service["summary"])}</p><p><a class="eu-card__link" href="{esc(route_by_service[service["id"]]["path"])}">Vezi serviciul</a></p></article>'
        for service in relevant_services
    )
    return f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">{esc(site["audience_page"]["eyebrow"])}</p><h1 class="eu-heading-xl">{esc(audience["label"])}</h1><p class="eu-lead">{esc(audience["primary_goal"])}</p><div class="eu-actions">{cta_link(site["audience_page"]["cta"], commercial, cta_routes)}</div></div></section>''' + section(site["audience_page"]["problem_heading"], f'<div class="eu-grid">{problems}</div>') + section(site["audience_page"]["service_heading"], f'<div class="eu-grid">{service_cards}</div>', surface=True)


def empty_index(payload: dict) -> str:
    return section(payload["title"], f'<p class="eu-lead">{esc(payload["body"])}</p>', "Verificare înainte de publicare", surface=True)


def dry_run_form(title: str, lead: str, commercial, cta_routes) -> str:
    return f'''<section class="eu-section eu-section--surface"><div class="eu-shell eu-stack"><p class="eu-eyebrow">Flux comercial · dry-run E08</p><h1 class="eu-heading-xl">{esc(title)}</h1><p class="eu-lead">{esc(lead)}</p><form class="eu-form" action="#" method="post" data-eucons-dry-run="true" onsubmit="return false"><div class="eu-field"><label class="eu-label" for="organization">Organizație</label><input class="eu-control" id="organization" name="organization" autocomplete="organization"></div><div class="eu-field"><label class="eu-label" for="context">Pe scurt, ce vrei să faci?</label><textarea class="eu-control" id="context" name="context"></textarea></div><div class="eu-alert eu-alert--info" role="status">Transmiterea nu este activă în E08. Transportul și consimțământul sunt validate în E11.</div><button class="eu-button eu-button--primary" type="submit" disabled aria-disabled="true">Transmitere indisponibilă în preview</button></form></div></section>'''


def generic_knowledge(title: str, body: str) -> str:
    return section(title, f'<p class="eu-lead">{esc(body)}</p>', "Bază de cunoaștere", surface=True)


def build(output: Path) -> dict:
    ia = load(IA_PATH)
    site = load(SITE_PATH)
    service_registry = load(SERVICES_PATH)
    commercial = load(COMMERCIAL_PATH)
    evidence = load(EVIDENCE_PATH)
    people_registry = load(PEOPLE_PATH)
    case_registry = load(CASES_PATH)

    if site.get("phase") != "E08" or site.get("build_state") != "DEVELOPMENT_NOINDEX":
        fail("E08 public site manifest is not in canonical development state")

    allowed_service_ids = publishable_service_ids(evidence)
    services = [item for item in service_registry.get("services", []) if item.get("id") in allowed_service_ids]
    if not services:
        fail("no evidence-backed service offering is available for E08")
    public_people = publishable_people(people_registry)
    public_cases = publishable_cases(case_registry)
    core, service_routes, cta_routes = route_maps(ia)
    audience_by_id = {item["id"]: item for item in commercial.get("audiences", [])}

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    (output / "assets").mkdir(parents=True)
    shutil.copy2(CSS_PATH, output / "assets" / "eucons.css")

    pages: dict[str, str] = {}
    pages[core["home"]["path"]] = homepage(site, services, commercial, public_people, public_cases, ia, core, cta_routes)
    pages[core["services_index"]["path"]] = services_index(services, ia)
    pages[core["funding_index"]["path"]] = empty_index(site["empty_states"]["funding_index"])
    pages[core["projects_index"]["path"]] = empty_index(site["empty_states"]["projects_index"]) if not public_cases else generic_knowledge("Proiecte și studii de caz", "Sunt afișate numai înregistrările PUBLISHABLE din registrul de cazuri.")
    pages[core["team_index"]["path"]] = empty_index(site["empty_states"]["team_index"]) if not public_people else generic_knowledge("Echipa Euroconsult", "Sunt afișate numai profilurile PUBLISHABLE din registrul de persoane.")
    pages[core["expertise"]["path"]] = generic_knowledge("Expertiză", "Analizele și materialele de expertiză sunt proiectate numai după validarea motorului de cunoaștere E14.")
    pages[core["guides_index"]["path"]] = generic_knowledge("Ghiduri", "Ghidurile publice sunt activate după validarea motorului de cunoaștere E14.")
    pages[core["articles_index"]["path"]] = generic_knowledge("Articole", "Articolele sunt activate după validarea buclei editoriale E15.")
    pages[core["resources"]["path"]] = generic_knowledge("Resurse", "Resursele sunt publicate numai după verificarea conținutului și a provenienței.")
    pages[core["about"]["path"]] = section(site["about"]["title"], f'<p class="eu-lead">{esc(site["about"]["body"])}</p>', "Euroconsult", surface=True)
    pages[core["project_evaluation"]["path"]] = dry_run_form(site["journey_pages"]["project_evaluation"]["title"], site["journey_pages"]["project_evaluation"]["lead"], commercial, cta_routes)
    pages[core["request_offer"]["path"]] = dry_run_form(site["journey_pages"]["request_offer"]["title"], site["journey_pages"]["request_offer"]["lead"], commercial, cta_routes)
    pages[core["contact"]["path"]] = section(site["contact"]["title"], f'<p class="eu-lead">{esc(site["contact"]["body"])}</p><div class="eu-actions">{cta_link("request_project_evaluation", commercial, cta_routes)}{cta_link("request_offer", commercial, cta_routes, "eu-button eu-button--secondary")}</div>', "Contact", surface=True)
    pages[core["terms"]["path"]] = generic_knowledge("Termeni", site["legal_placeholders"]["terms"])
    pages[core["privacy"]["path"]] = generic_knowledge("Confidențialitate", site["legal_placeholders"]["privacy"])

    for route_id in ("companies", "public_authorities", "ngos"):
        route = core[route_id]
        audience = audience_by_id[route["audience_id"]]
        relevant_ids = {sid for problem in audience.get("problems", []) for sid in problem.get("service_capabilities", [])}
        relevant_services = [item for item in services if item["id"] in relevant_ids]
        pages[route["path"]] = audience_page(audience, relevant_services, site, commercial, cta_routes, ia)

    services_by_id = {item["id"]: item for item in services}
    for service_id, route in service_routes.items():
        if service_id not in services_by_id:
            continue
        pages[route["path"]] = service_page(services_by_id[service_id], site, commercial, cta_routes)

    expected_core_paths = {item["path"] for item in ia.get("core_routes", [])}
    missing_core = expected_core_paths - set(pages)
    if missing_core:
        fail(f"core build is incomplete: {sorted(missing_core)}")

    rendered = []
    for route_path, body in sorted(pages.items()):
        route_title = "Euroconsult"
        if route_path == "/":
            route_title = site["brand"]["descriptor"]
        else:
            route_title = next((nav_label(rid) for rid, route in core.items() if route["path"] == route_path), route_title)
            if route_path.startswith("/servicii/") and route_path != "/servicii/":
                service_id = next((sid for sid, route in service_routes.items() if route["path"] == route_path), None)
                if service_id in services_by_id:
                    route_title = services_by_id[service_id]["label"]
        description = site["brand"]["descriptor"]
        document = page_shell(route_path=route_path, title=route_title, description=description, body=body, ia=ia, core=core)
        target = path_to_output(output, route_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document, encoding="utf-8")
        rendered.append({"path": route_path, "file": str(target.relative_to(output)).replace("\\", "/"), "sha256": hashlib.sha256(document.encode("utf-8")).hexdigest()})

    manifest = {
        "schema_version": 1,
        "product": "EUCONS_COMMERCIAL_OS",
        "phase": "E08",
        "build_state": "DEVELOPMENT_NOINDEX",
        "pages": rendered,
        "page_count": len(rendered),
        "core_page_count": len(expected_core_paths),
        "service_page_count": len([p for p in pages if p.startswith("/servicii/") and p != "/servicii/"]),
        "publishable_service_count": len(services),
        "publishable_people_count": len(public_people),
        "publishable_case_count": len(public_cases),
        "funding_projection_active": False,
        "source_hashes": {
            "information_architecture": hashlib.sha256(IA_PATH.read_bytes()).hexdigest(),
            "public_site": hashlib.sha256(SITE_PATH.read_bytes()).hexdigest(),
            "service_registry": hashlib.sha256(SERVICES_PATH.read_bytes()).hexdigest(),
            "evidence_registry": hashlib.sha256(EVIDENCE_PATH.read_bytes()).hexdigest(),
        },
    }
    (output / "build_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=WEB / ".build-e08")
    args = parser.parse_args()
    try:
        manifest = build(args.output)
    except PublicSiteBuildError as exc:
        raise SystemExit(f"EUCONS E08 public site build failed: {exc}")
    print(f"EUCONS E08 public site build: {manifest['page_count']} pages, {manifest['publishable_service_count']} verified services")


if __name__ == "__main__":
    main()
