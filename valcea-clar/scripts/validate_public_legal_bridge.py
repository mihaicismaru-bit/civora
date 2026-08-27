#!/usr/bin/env python3
"""Fail-closed contract for public VÂLCEA CLAR policy/legal routes.

This validates canonical repository data plus the generated server-rendered/static
runtime. It does not claim that an external deployment has been published; remote
HTTP acceptance remains a separate deployment check.
"""
from __future__ import annotations

import json
from pathlib import Path

import build_legal_pages

ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "site" / "legal" / "legal_pages.json"
NAVIGATION = ROOT / "site" / "navigation.json"
RUNTIME = ROOT / "site" / "runtime"
EXPECTED_PAGES = {"termeni", "confidentialitate", "corectii"}


def main() -> int:
    # Generated HTML is deployment/runtime output, not an independent source of
    # truth. Rebuild it deterministically before validating the repository contract.
    build_legal_pages.build()

    doc = json.loads(LEGAL.read_text(encoding="utf-8"))
    assert doc.get("canonical_domain") == "valceaclar.ro"
    assert set(doc.get("pages", {})) == EXPECTED_PAGES

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
    assert ("Corecții", "/corectii/") in footer_links
    assert (nav.get("policy") or {}).get("legal_links_in_footer") is True
    assert (nav.get("policy") or {}).get("same_primary_navigation_on_every_public_page") is True
    assert (nav.get("policy") or {}).get("main_navigation_must_resolve_to_reader_content") is True
    assert (nav.get("policy") or {}).get("empty_category_fallback_to_other_category_forbidden") is True

    rendered: list[str] = []
    for slug, page in doc["pages"].items():
        expected_path = f"/{slug}/"
        assert page.get("path") == expected_path
        target = RUNTIME / slug / "index.html"
        assert target.is_file(), f"Missing generated public policy page: {target}"
        text = target.read_text(encoding="utf-8")
        rendered.append(text)
        assert page["title"] in text
        assert f"https://valceaclar.ro{expected_path}" in text
        assert 'name="robots" content="index,follow"' in text
        assert doc["contact_email"] in text
        assert "<main" in text

    corectii = doc["pages"]["corectii"]
    assert corectii["title"] == "Corecții și drept la replică"
    assert len(corectii.get("sections") or []) >= 5

    forbidden = ("CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "github-actions-secret:")
    corpus = LEGAL.read_text(encoding="utf-8") + NAVIGATION.read_text(encoding="utf-8") + "\n".join(rendered)
    leaked = [value for value in forbidden if value in corpus]
    assert not leaked, f"Secret marker leaked into public policy artifacts: {leaked}"

    print(
        "VÂLCEA CLAR public policy routes: PASS "
        "(canonical navigation v2 + 3 server-rendered/static repository routes; remote HTTP remains separate)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
