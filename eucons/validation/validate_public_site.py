#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import re
import tempfile
from pathlib import Path

EUCONS_ROOT = Path(__file__).resolve().parents[1]
WEB_ROOT = EUCONS_ROOT / "web"

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def load_builder():
    path = WEB_ROOT / "build_public_site.py"
    spec = importlib.util.spec_from_file_location("eucons_build_public_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module

def assert_true(condition, message):
    if not condition:
        raise AssertionError(message)

def main():
    builder = load_builder()
    ia = load_json(WEB_ROOT / "information_architecture.json")
    evidence = load_json(EUCONS_ROOT / "evidence" / "evidence_registry.json")
    people = load_json(EUCONS_ROOT / "people" / "people_registry.json")
    cases = load_json(EUCONS_ROOT / "cases" / "case_study_registry.json")

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "site"
        pages = builder.build_site(target)
        expected = {item["path"] for item in ia["core_routes"]}
        publishable_service_ids = builder.publishable_service_ids(evidence)
        service_routes = {
            item["service_id"]: item["path"]
            for item in ia["service_routes"]
            if item["service_id"] in publishable_service_ids
        }
        expected.update(service_routes.values())
        assert_true(set(pages) == expected, f"Rendered route set drifted: expected {len(expected)}, got {len(pages)}")

        for path in sorted(expected):
            file_path = builder.route_file(target, path)
            assert_true(file_path.exists(), f"Missing generated page for {path}")
            text = file_path.read_text(encoding="utf-8")
            assert_true('<meta name="robots" content="noindex,nofollow">' in text, f"{path} must remain noindex during E08")
            assert_true(f'<link rel="canonical" href="https://eucons.ro{path}">' in text, f"Canonical drift for {path}")
            assert_true('class="eu-skip-link"' in text, f"Missing skip link on {path}")
            assert_true('aria-label="Navigație principală"' in text, f"Missing primary navigation on {path}")
            assert_true("/termeni/" in text and "/confidentialitate/" in text, f"Missing legal footer links on {path}")
            assert_true("fonts.googleapis.com" not in text and "http://fonts." not in text, f"Remote font dependency on {path}")
            assert_true("<form" not in text.lower(), f"E08 preview must not collect data before E11: {path}")

        home = builder.route_file(target, "/").read_text(encoding="utf-8")
        for required in ia["internal_link_contract"]["home_must_link"]:
            path = next(item["path"] for item in ia["core_routes"] if item["id"] == required)
            assert_true(f'href="{path}"' in home, f"Homepage missing required internal link {path}")
        assert_true('href="/servicii/"' in home, "Homepage missing secondary service catalogue")
        for route in service_routes.values():
            generated = builder.route_file(target, route)
            assert_true(generated.exists(), f"Publishable service route is not generated: {route}")
        for path in ["/pentru-companii/", "/pentru-autoritati-publice/", "/pentru-ong/"]:
            assert_true(f'href="{path}"' in home, f"Homepage missing priority audience route {path}")

        assert_true("Alege traseul potrivit" in home, "Visitor/commercial QA: JTBD-first primary CTA missing")
        assert_true("Vezi soluțiile" in home, "Commercial QA: secondary service discovery CTA missing")
        assert_true('href="#trasee-home"' in home, "JTBD QA: homepage primary CTA must target the four-journey chooser")
        assert_true("Ce nu promitem" in home, "Trust QA: explicit boundaries missing")
        assert_true("Nu garantăm obținerea finanțării" in home, "Trust QA: guarantee boundary missing")
        assert_true("O potrivire preliminară nu este eligibilitate confirmată" in home, "Trust QA: eligibility boundary missing")
        assert_true("În ce punct este proiectul tău?" in home, "JTBD QA: decision-first hero missing")
        assert_true("O recomandare utilă, fără certitudini inventate." in home, "Trust QA: uncertainty contract missing")
        assert_true("Exemple documentate, nu promisiuni" in home, "Proof QA: bounded proof section missing")
        for journey_path in (
            "/ce-finantare-mi-se-potriveste/",
            "/verifica-proiectul/",
            "/proiect-in-implementare/",
            "/proiect-cu-probleme/",
        ):
            assert_true(f'href="{journey_path}"' in home, f"JTBD QA: homepage missing {journey_path}")
        forbidden_price = re.compile(r"\b\d[\d\s.,]*\s*(?:€|EUR|RON|lei)\b", re.IGNORECASE)
        assert_true(not forbidden_price.search(home), "Homepage contains a numeric price/proof claim without an approved rule")

        if not builder.publishable_records(people, "people"):
            team = builder.route_file(target, "/echipa/").read_text(encoding="utf-8")
            assert_true("Nu există încă obiecte verificate" in team, "Empty people projection must fail closed")
        if not builder.publishable_records(cases, "cases"):
            projects = builder.route_file(target, "/proiecte/").read_text(encoding="utf-8")
            assert_true("Nu există încă obiecte verificate" in projects, "Empty cases projection must fail closed")

        root_preview = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        assert_true("Development preview" not in root_preview, "Root preview still contains E00 bootstrap placeholder")
        assert_true("Alege traseul potrivit" in root_preview, "Root preview does not start with JTBD selection")
        assert_true("Vezi soluțiile" in root_preview, "Root preview is missing secondary service discovery")
        assert_true('href="#trasee-home"' in root_preview, "Root preview primary CTA does not target four-journey chooser")
        assert_true("În ce punct este proiectul tău?" in root_preview, "Root preview is not decision-first")
        for journey_path in (
            "/ce-finantare-mi-se-potriveste/",
            "/verifica-proiectul/",
            "/proiect-in-implementare/",
            "/proiect-cu-probleme/",
        ):
            assert_true(f'href="{journey_path}"' in root_preview, f"Root preview missing {journey_path}")
        assert_true('<meta name="robots" content="noindex,nofollow">' in root_preview, "Root preview must remain noindex")

    print(json.dumps({
        "status": "PASS", "phase": "E08", "core_routes": len(ia["core_routes"]),
        "service_routes": len(service_routes), "people_projection": len(builder.publishable_records(people, "people")),
        "case_projection": len(builder.publishable_records(cases, "cases")), "visitor_qa": "PASS",
        "trust_qa": "PASS", "commercial_qa": "PASS"
    }, ensure_ascii=False))

if __name__ == "__main__":
    main()
