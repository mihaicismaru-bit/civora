#!/usr/bin/env python3
"""Fail-closed repository contract for public VÂLCEA CLAR legal routes."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "site" / "legal" / "legal_pages.json"
NAVIGATION = ROOT / "site" / "navigation.json"
RUNTIME = ROOT / "site" / "runtime"


def main() -> int:
    doc = json.loads(LEGAL.read_text(encoding="utf-8"))
    assert doc.get("canonical_domain") == "valceaclar.ro"
    assert set(doc.get("pages", {})) == {"termeni", "confidentialitate"}

    nav = json.loads(NAVIGATION.read_text(encoding="utf-8"))
    assert nav.get("contract_id") == "valcea-clar-primary-v2"
    footer_links = {
        (str(row.get("label") or ""), str(row.get("href") or ""))
        for row in (nav.get("footer") or {}).get("links") or []
        if isinstance(row, dict)
    }
    assert ("Despre noi", "/despre/") in footer_links
    assert ("Termeni", "/termeni/") in footer_links
    assert ("Confidențialitate", "/confidentialitate/") in footer_links
    assert (nav.get("policy") or {}).get("legal_links_in_footer") is True
    assert (nav.get("policy") or {}).get("same_primary_navigation_on_every_public_page") is True
    assert (nav.get("policy") or {}).get("main_navigation_must_resolve_to_reader_content") is True
    assert (nav.get("policy") or {}).get("empty_category_fallback_to_other_category_forbidden") is True

    for slug, page in doc["pages"].items():
        expected_path = f"/{slug}/"
        assert page.get("path") == expected_path
        target = RUNTIME / slug / "index.html"
        assert target.is_file(), f"Missing generated legal page: {target}"
        text = target.read_text(encoding="utf-8")
        assert page["title"] in text
        assert f"https://valceaclar.ro{expected_path}" in text
        assert 'name="robots" content="index,follow"' in text
        assert doc["contact_email"] in text

    forbidden = ("CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "github-actions-secret:")
    leaked = []
    for slug in doc["pages"]:
        text = (RUNTIME / slug / "index.html").read_text(encoding="utf-8")
        leaked.extend(value for value in forbidden if value in text)
    assert not leaked, f"Secret marker leaked into public legal runtime: {sorted(set(leaked))}"

    print("VÂLCEA CLAR public legal runtime: PASS (canonical navigation v2 + repository legal contract)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
