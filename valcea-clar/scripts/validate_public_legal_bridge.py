#!/usr/bin/env python3
"""Fail-closed contract for public VÂLCEA CLAR legal routes.

This validates repository artifacts only. It does not claim that an external Site
has been published; remote HTTP acceptance remains a separate deployment check.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "site" / "chatgpt-sites-live-bridge.js"
INSTALL = ROOT / "site" / "ONE_TIME_LIVE_BRIDGE_INSTALL.md"
LEGAL = ROOT / "site" / "legal" / "legal_pages.json"
RUNTIME = ROOT / "site" / "runtime"


def main() -> int:
    doc = json.loads(LEGAL.read_text(encoding="utf-8"))
    assert doc.get("canonical_domain") == "valceaclar.ro"
    assert set(doc.get("pages", {})) == {"termeni", "confidentialitate"}

    bridge = BRIDGE.read_text(encoding="utf-8")
    install = INSTALL.read_text(encoding="utf-8")

    required_bridge = (
        "site/legal/legal_pages.json",
        "path === '/termeni/'",
        "path === '/confidentialitate/'",
        "renderLegal(doc, slug)",
        "https://valceaclar.ro${page.path}",
        '<a href="/termeni/">Termeni</a>',
        '<a href="/confidentialitate/">Confidențialitate</a>',
    )
    missing_bridge = [value for value in required_bridge if value not in bridge]
    assert not missing_bridge, f"Public bridge legal contract missing: {missing_bridge}"

    required_install = (
        "server-rendered/static",
        "HTML-ul inițial",
        "https://valceaclar.ro/termeni/",
        "https://valceaclar.ro/confidentialitate/",
        "index,follow",
        "HTTP 200",
    )
    missing_install = [value for value in required_install if value not in install]
    assert not missing_install, f"Site install legal contract missing: {missing_install}"

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
    leaked = [value for value in forbidden if value in bridge or value in install]
    assert not leaked, f"Secret marker leaked into public bridge/install docs: {leaked}"

    print("VÂLCEA CLAR public legal bridge: PASS (repository contract; remote HTTP still requires Site publish)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
