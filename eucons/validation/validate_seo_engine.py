#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "seo" / "seo_engine.py"
    spec = importlib.util.spec_from_file_location("e16_seo", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "seo" / "seo_contract.json").read_text(encoding="utf-8"))
    ia = json.loads((EUCONS / "web" / "information_architecture.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    evidence = json.loads((EUCONS / "evidence" / "evidence_registry.json").read_text(encoding="utf-8"))

    result = engine.build_projection(ia, services, evidence, contract)

    assert result["engine_id"] == "EUCONS_E16_SEO_ENGINE"
    assert result["canonical_origin"] == "https://eucons.ro"
    assert result["production_indexing_enabled"] is False
    assert result["preview_robots"] == "noindex,nofollow"
    assert result["summary"]["core_routes"] == 18
    assert result["summary"]["service_routes"] == 8
    assert result["summary"]["active_routes"] == 26
    assert result["summary"]["sitemap_entries"] == 26
    assert result["summary"]["orphan_routes"] == 0
    assert result["orphans"] == []
    assert len(result["conditional_families"]) == 5
    assert all(row["state"] == "CONDITIONAL_HOLD_UNTIL_ROUTE_EXISTS" for row in result["conditional_families"])

    routes = result["routes"]
    assert len({row["path"] for row in routes}) == 26
    assert len({row["canonical"] for row in routes}) == 26
    assert len({row["title"] for row in routes}) == 26
    assert all(row["canonical"].startswith("https://eucons.ro/") or row["canonical"] == "https://eucons.ro/" for row in routes)
    assert all(row["description"].strip() for row in routes)
    assert all(row["schema"]["@context"] == "https://schema.org" for row in routes)

    service_routes = [row for row in routes if row["surface"] == "SERVICE"]
    assert len(service_routes) == 8
    assert all(row["schema"]["@type"] == "Service" for row in service_routes)
    assert all(row["provenance"]["evidence_state"] == "PUBLISHABLE" for row in service_routes)

    home = next(row for row in routes if row["route_id"] == "home")
    assert home["schema"]["@type"] == "WebSite"
    assert "/servicii/" in result["internal_links"]["/"]
    assert "/evaluare-proiect/" in result["internal_links"]["/"]
    assert all(result["incoming_link_counts"][row["path"]] > 0 for row in routes if row["path"] != "/")

    expected_clusters = {"services", "funding", "audiences", "authority", "trust"}
    assert set(result["clusters"]) == expected_clusters
    assert len(result["clusters"]["services"]) == 9

    print(json.dumps({
        "status": "PASS",
        "phase": "E16",
        "active_routes": result["summary"]["active_routes"],
        "sitemap_entries": result["summary"]["sitemap_entries"],
        "orphans": result["summary"]["orphan_routes"],
        "clusters": sorted(result["clusters"]),
        "preview_indexing": "DISABLED",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
