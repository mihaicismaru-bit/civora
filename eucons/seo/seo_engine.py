#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "seo" / "seo_contract.json"


class SEOError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical(origin: str, path: str) -> str:
    return origin.rstrip("/") + (path if path.startswith("/") else "/" + path)


def publishable_service_ids(evidence: dict[str, Any]) -> set[str]:
    return {
        str(claim.get("object_ref"))
        for claim in evidence.get("claims") or []
        if claim.get("claim_class") == "SERVICE_OFFERING"
        and claim.get("publication_state") == "PUBLISHABLE"
        and claim.get("object_ref")
    }


def validate_ia(ia: dict[str, Any], contract: dict[str, Any]) -> None:
    origin = str(ia.get("canonical_origin") or "")
    if not origin.startswith("https://"):
        raise SEOError("canonical origin must use https")
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    allowed_surfaces = set(contract["surfaces"])
    for row in ia.get("core_routes") or []:
        rid = str(row.get("id") or "")
        path = str(row.get("path") or "")
        surface = str(row.get("surface") or "")
        if not rid or rid in seen_ids:
            raise SEOError("duplicate or missing core route id")
        if not path or path in seen_paths:
            raise SEOError("duplicate or missing core route path")
        if path != "/" and (not path.endswith("/") or path.lower() != path):
            raise SEOError("core route path policy violation")
        if surface not in allowed_surfaces:
            raise SEOError("unknown core route surface")
        seen_ids.add(rid)
        seen_paths.add(path)
    for row in ia.get("service_routes") or []:
        path = str(row.get("path") or "")
        if not row.get("service_id") or not path or path in seen_paths:
            raise SEOError("duplicate or invalid service route")
        if not path.endswith("/") or path.lower() != path:
            raise SEOError("service route path policy violation")
        seen_paths.add(path)


def metadata_for_core(route: dict[str, Any], contract: dict[str, Any]) -> tuple[str, str]:
    templates = contract["core_metadata"]
    key = str(route["id"])
    if key not in templates:
        raise SEOError(f"missing metadata template for {key}")
    row = templates[key]
    return str(row["title"]), str(row["description"])


def schema_for(route: dict[str, Any], title: str, url: str) -> dict[str, Any]:
    surface = route["surface"]
    if surface == "HOME":
        return {"@context": "https://schema.org", "@type": "WebSite", "name": "Euroconsult", "url": url}
    if surface in {"SERVICE_INDEX", "AUDIENCE", "OPPORTUNITY_INDEX", "CASE_INDEX", "PEOPLE_INDEX", "KNOWLEDGE_INDEX", "GUIDE_INDEX", "ARTICLE_INDEX", "RESOURCE_INDEX"}:
        return {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "url": url}
    if surface == "ABOUT":
        return {"@context": "https://schema.org", "@type": "AboutPage", "name": title, "url": url}
    if surface in {"CONTACT", "LEAD_JOURNEY", "LEGAL"}:
        return {"@context": "https://schema.org", "@type": "WebPage", "name": title, "url": url}
    raise SEOError(f"unsupported schema surface {surface}")


def route_links(ia: dict[str, Any], active_service_paths: list[str]) -> dict[str, list[str]]:
    core = {row["id"]: row["path"] for row in ia.get("core_routes") or []}
    links: dict[str, set[str]] = {path: set() for path in core.values()}
    for path in active_service_paths:
        links[path] = set()

    home = core["home"]
    for rid in ia["navigation"]["primary"] + ia["navigation"]["utility"]:
        links[home].add(core[rid])
    for rid in ia["internal_link_contract"]["home_must_link"]:
        links[home].add(core[rid])

    services_index = core["services_index"]
    links[services_index].update(active_service_paths)
    for path in active_service_paths:
        links[path].update({services_index, core["project_evaluation"], core["request_offer"]})

    for rid in ("companies", "public_authorities", "ngos"):
        links[core[rid]].update({services_index, core["funding_index"], core["project_evaluation"]})

    links[core["expertise"]].update({core["guides_index"], core["articles_index"], core["resources"]})
    for rid in ("guides_index", "articles_index", "resources"):
        links[core[rid]].update({core["expertise"], services_index, core["funding_index"], core["project_evaluation"]})

    links[core["projects_index"]].update({services_index, core["project_evaluation"]})
    links[core["team_index"]].update({services_index, core["about"]})
    links[core["funding_index"]].update({services_index, core["project_evaluation"]})
    links[core["about"]].update({core["team_index"], services_index, core["contact"]})
    links[core["contact"]].update({home, services_index})
    links[core["project_evaluation"]].update({services_index, core["funding_index"]})
    links[core["request_offer"]].update({services_index, core["contact"]})
    links[core["terms"]].update({home, core["privacy"], core["contact"]})
    links[core["privacy"]].update({home, core["terms"], core["contact"]})

    footer_paths = {core[rid] for rid in ia["navigation"]["footer"]}
    for path in links:
        if path != home:
            links[path].update(footer_paths)

    return {path: sorted(target for target in targets if target != path) for path, targets in sorted(links.items())}


def build_projection(
    ia: dict[str, Any],
    services: dict[str, Any],
    evidence: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, Any]:
    validate_ia(ia, contract)
    origin = ia["canonical_origin"]
    publishable = publishable_service_ids(evidence)
    service_by_id = {str(row.get("id")): row for row in services.get("services") or []}
    service_routes = []
    for row in ia.get("service_routes") or []:
        sid = str(row["service_id"])
        if sid not in publishable:
            continue
        service = service_by_id.get(sid)
        if not service:
            raise SEOError(f"publishable service route has no service registry row: {sid}")
        if not service.get("label") or not service.get("summary"):
            raise SEOError(f"service metadata incomplete: {sid}")
        service_routes.append((row, service))

    routes: list[dict[str, Any]] = []
    for route in ia.get("core_routes") or []:
        title, description = metadata_for_core(route, contract)
        url = canonical(origin, route["path"])
        routes.append({
            "route_id": route["id"],
            "path": route["path"],
            "surface": route["surface"],
            "indexable_candidate": bool(route.get("indexable")),
            "canonical": url,
            "title": title,
            "description": description,
            "schema": schema_for(route, title, url),
        })

    for route, service in service_routes:
        url = canonical(origin, route["path"])
        title = f"{service['label']} | Euroconsult"
        description = str(service["summary"])
        routes.append({
            "route_id": f"service:{route['service_id']}",
            "path": route["path"],
            "surface": "SERVICE",
            "indexable_candidate": True,
            "canonical": url,
            "title": title,
            "description": description,
            "schema": {
                "@context": "https://schema.org",
                "@type": "Service",
                "name": service["label"],
                "description": description,
                "url": url,
                "provider": {"@type": "Organization", "name": "Euroconsult"},
            },
            "provenance": {
                "service_id": route["service_id"],
                "evidence_class": "SERVICE_OFFERING",
                "evidence_state": "PUBLISHABLE",
            },
        })

    paths = [row["path"] for row in routes]
    canonicals = [row["canonical"] for row in routes]
    titles = [row["title"] for row in routes]
    if len(paths) != len(set(paths)):
        raise SEOError("duplicate active route path")
    if len(canonicals) != len(set(canonicals)):
        raise SEOError("duplicate canonical")
    if len(titles) != len(set(titles)):
        raise SEOError("duplicate SEO title")
    if any(not row["description"].strip() for row in routes):
        raise SEOError("empty SEO description")

    active_service_paths = [row["path"] for row, _ in service_routes]
    links = route_links(ia, active_service_paths)
    active_paths = set(paths)
    incoming = {path: 0 for path in paths}
    broken_targets: set[str] = set()
    for source, targets in links.items():
        if source not in active_paths:
            continue
        for target in targets:
            if target not in active_paths:
                broken_targets.add(target)
            else:
                incoming[target] += 1

    if broken_targets:
        raise SEOError(f"internal link target missing: {sorted(broken_targets)}")
    home_path = next(row["path"] for row in routes if row["route_id"] == "home")
    orphans = sorted(path for path, count in incoming.items() if path != home_path and count == 0)
    if contract["rules"]["orphan_routes_forbidden"] and orphans:
        raise SEOError(f"orphan routes: {orphans}")

    clusters = {
        "services": ["/servicii/"] + sorted(active_service_paths),
        "funding": ["/finantari/", "/evaluare-proiect/"],
        "audiences": ["/pentru-companii/", "/pentru-autoritati-publice/", "/pentru-ong/", "/servicii/"],
        "authority": ["/expertiza/", "/ghiduri/", "/articole/", "/resurse/"],
        "trust": ["/despre/", "/echipa/", "/proiecte/", "/contact/"],
    }

    sitemap = [
        {"loc": row["canonical"], "path": row["path"]}
        for row in sorted(routes, key=lambda item: item["path"])
        if row["indexable_candidate"]
    ]

    return {
        "schema_version": contract["output"]["schema_version"],
        "product": contract["output"]["product"],
        "engine_id": contract["engine_id"],
        "canonical_origin": origin,
        "production_indexing_enabled": contract["output"]["production_indexing_enabled"],
        "preview_robots": contract["output"]["preview_robots"],
        "summary": {
            "active_routes": len(routes),
            "core_routes": len(ia.get("core_routes") or []),
            "service_routes": len(service_routes),
            "sitemap_entries": len(sitemap),
            "orphan_routes": len(orphans),
        },
        "routes": routes,
        "sitemap": sitemap,
        "clusters": clusters,
        "internal_links": links,
        "incoming_link_counts": incoming,
        "orphans": orphans,
        "conditional_families": [
            {
                "id": row["id"],
                "pattern": row["pattern"],
                "state": "CONDITIONAL_HOLD_UNTIL_ROUTE_EXISTS",
                "source": row["source"],
            }
            for row in ia.get("conditional_route_families") or []
        ],
    }


def assert_output_path_safe(path: Path) -> None:
    try:
        path.resolve().relative_to(ROOT.resolve())
    except ValueError:
        return
    raise SEOError("runtime SEO output cannot be written under repository root")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ia", default=str(EUCONS / "web" / "information_architecture.json"))
    parser.add_argument("--services", default=str(EUCONS / "services" / "service_registry.json"))
    parser.add_argument("--evidence", default=str(EUCONS / "evidence" / "evidence_registry.json"))
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    result = build_projection(load_json(Path(args.ia)), load_json(Path(args.services)), load_json(Path(args.evidence)), load_json(Path(args.contract)))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        output = Path(args.output)
        assert_output_path_safe(output)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
