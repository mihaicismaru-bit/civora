#!/usr/bin/env python3
"""Idempotently add and validate artist-profile rendering in the VÂLCEA CLAR live bridge."""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "chatgpt-sites-live-bridge.js"
MARKER = "function artistProfiles(story)"


def patch(text: str) -> str:
    if MARKER not in text:
        anchor = "  function renderHome(nav, feed) {"
        if anchor not in text:
            raise ValueError("renderHome anchor missing")
        helper = r'''  function artistProfiles(story) {
    const rows = Array.isArray(story?.artist_profiles) ? story.artist_profiles : [];
    if (!rows.length) return '';
    const links = rows.map(item => `<a href="${esc(item.path)}">${esc(item.name)}${item.external_identity_verified ? ' <span aria-label="identitate externă verificată">✓</span>' : ''}</a>`).join('');
    return `<section class="vc-rich vc-artists" data-artist-intelligence="verified"><h2>Artiști din acest festival</h2><p>Profiluri construite din line-up verificat. Conturile externe apar numai când identitatea muzicală a fost rezolvată fără ambiguitate.</p><div class="vc-artistlinks">${links}</div><p><a href="/artisti/">Vezi directorul de artiști →</a></p></section>`;
  }

'''
        text = text.replace(anchor, helper + anchor, 1)

    css_anchor = ".vc-rich li{margin:8px 0;line-height:1.55}"
    css_add = ".vc-rich li{margin:8px 0;line-height:1.55}.vc-artistlinks{display:flex;gap:9px;flex-wrap:wrap}.vc-artistlinks a{border:1px solid var(--vc-line);border-radius:999px;padding:7px 11px;text-decoration:none;font:750 13px/1.2 Inter,system-ui,sans-serif}.vc-artistlinks a:hover{text-decoration:underline}"
    if ".vc-artistlinks{" not in text:
        if css_anchor not in text:
            raise ValueError("rich CSS anchor missing")
        text = text.replace(css_anchor, css_add, 1)

    old = '${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}<section class="vc-article-sources">'
    new = '${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}${artistProfiles(story)}<section class="vc-article-sources">'
    if new not in text:
        if old not in text:
            raise ValueError("renderStory artist insertion anchor missing")
        text = text.replace(old, new, 1)
    return text


def validate(text: str) -> None:
    required = [
        MARKER,
        ".vc-artistlinks{",
        "${artistProfiles(story)}<section class=\"vc-article-sources\">",
        'href="${esc(item.path)}"',
        "href=\"/artisti/\"",
        "external_identity_verified",
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise ValueError("artist bridge contract incomplete: " + ", ".join(missing))


def self_test() -> None:
    unpatched = '''(() => {\n  function styleOnce() {\n    const css = ".vc-rich li{margin:8px 0;line-height:1.55}";\n  }\n  const factbox = () => '';\n  const richSections = () => '';\n  function renderHome(nav, feed) {}\n  function renderStory(story) {\n    return `${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}<section class="vc-article-sources">`;\n  }\n})();'''
    try:
        validate(unpatched)
    except ValueError:
        pass
    else:
        raise AssertionError("unpatched bridge must fail validation")
    patched = patch(unpatched)
    validate(patched)
    assert patch(patched) == patched, "artist bridge patch must be idempotent"
    print("VÂLCEA CLAR live bridge artist-profile patcher self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    original = TARGET.read_text(encoding="utf-8")
    if args.check:
        # Validation must inspect the checked-out artifact as-is. The old
        # implementation patched an in-memory copy first, which allowed an
        # unpatched-but-patchable bridge to report a false PASS.
        validate(original)
        print("VÂLCEA CLAR live bridge artist-profile contract: PASS")
        return 0

    updated = patch(original)
    validate(updated)
    if updated != original:
        TARGET.write_text(updated, encoding="utf-8")
        print("VÂLCEA CLAR live bridge artist-profile patch: UPDATED")
    else:
        print("VÂLCEA CLAR live bridge artist-profile patch: ALREADY_CURRENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
