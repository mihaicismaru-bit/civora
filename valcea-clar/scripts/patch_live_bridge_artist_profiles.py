#!/usr/bin/env python3
"""Idempotently enforce artist/creator UI rendering in the VÂLCEA CLAR Sites live bridge.

The public bridge must visibly project the Artist Intelligence already present in
live-feed.json. For every story with artist_profiles it renders both:
1. exact artist/creator mentions in the article body as links to /artisti/<slug>/;
2. a complete artist/creator index below the article body.

This is a structural Sites bridge change; publishing the bridge in the existing
Sites project remains distinct from ordinary feed refreshes.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "site" / "chatgpt-sites-live-bridge.js"
PROFILE_MARKER = "function artistProfiles(story)"
INLINE_MARKER = "function artistLinkedText(value, story)"


def replace_function(text: str, name: str, replacement: str) -> str:
    pattern = re.compile(rf"  function {re.escape(name)}\([^\n]*\) \{{.*?\n  \}}\n", re.S)
    if not pattern.search(text):
        raise ValueError(f"{name} function anchor missing")
    return pattern.sub(replacement, text, count=1)


def ensure_helpers(text: str) -> str:
    anchor = "  function renderHome(nav, feed) {"
    if anchor not in text:
        raise ValueError("renderHome anchor missing")

    helper = r'''  function artistLinkedText(value, story) {
    const rows = Array.isArray(story?.artist_profiles) ? story.artist_profiles : [];
    let output = esc(value);
    if (!rows.length) return output;
    const ordered = [...rows]
      .filter(item => item?.name && /^\/artisti\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
      .sort((a,b) => String(b.name).length - String(a.name).length);
    for (const item of ordered) {
      const token = esc(item.name);
      if (!token || !output.includes(token)) continue;
      const linked = `<a class="vc-artist-inline" href="${esc(item.path)}" data-artist-profile="${esc(item.id || '')}">${token}</a>`;
      output = output.split(token).join(linked);
    }
    return output;
  }

  function artistProfiles(story) {
    const rows = Array.isArray(story?.artist_profiles) ? story.artist_profiles : [];
    if (!rows.length) return '';
    const links = rows
      .filter(item => item?.name && /^\/artisti\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
      .map(item => `<a href="${esc(item.path)}">${esc(item.name)}${item.external_identity_verified ? ' <span aria-label="identitate externă verificată">✓</span>' : ''}</a>`)
      .join('');
    if (!links) return '';
    return `<section class="vc-rich vc-artists" data-artist-intelligence="verified"><h2>Artiști și creatori din acest material</h2><p>Profiluri VÂLCEA CLAR construite din line-up, distribuții și programe verificate. Conturile externe apar numai după rezolvarea identității fără ambiguitate.</p><div class="vc-artistlinks">${links}</div><p><a href="/artisti/">Vezi directorul de artiști →</a></p></section>`;
  }

'''

    if INLINE_MARKER not in text and PROFILE_MARKER not in text:
        return text.replace(anchor, helper + anchor, 1)

    if INLINE_MARKER not in text and PROFILE_MARKER in text:
        text = replace_function(text, "artistProfiles", helper)
        return text

    # Both functions already exist: normalize the profile function wording/validation.
    profile_only = r'''  function artistProfiles(story) {
    const rows = Array.isArray(story?.artist_profiles) ? story.artist_profiles : [];
    if (!rows.length) return '';
    const links = rows
      .filter(item => item?.name && /^\/artisti\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
      .map(item => `<a href="${esc(item.path)}">${esc(item.name)}${item.external_identity_verified ? ' <span aria-label="identitate externă verificată">✓</span>' : ''}</a>`)
      .join('');
    if (!links) return '';
    return `<section class="vc-rich vc-artists" data-artist-intelligence="verified"><h2>Artiști și creatori din acest material</h2><p>Profiluri VÂLCEA CLAR construite din line-up, distribuții și programe verificate. Conturile externe apar numai după rezolvarea identității fără ambiguitate.</p><div class="vc-artistlinks">${links}</div><p><a href="/artisti/">Vezi directorul de artiști →</a></p></section>`;
  }
'''
    return replace_function(text, "artistProfiles", profile_only)


def patch(text: str) -> str:
    text = ensure_helpers(text)

    css_anchor = ".vc-rich li{margin:8px 0;line-height:1.55}"
    css_add = (
        ".vc-rich li{margin:8px 0;line-height:1.55}"
        ".vc-artist-inline{font-weight:700;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}"
        ".vc-artist-inline:hover{color:var(--vc-red)}"
        ".vc-artistlinks{display:flex;gap:9px;flex-wrap:wrap}"
        ".vc-artistlinks a{border:1px solid var(--vc-line);border-radius:999px;padding:7px 11px;text-decoration:none;font:750 13px/1.2 Inter,system-ui,sans-serif}"
        ".vc-artistlinks a:hover{text-decoration:underline}"
    )
    if ".vc-artist-inline{" not in text:
        if css_anchor not in text:
            raise ValueError("rich CSS anchor missing")
        if ".vc-artistlinks{" in text:
            text = text.replace(css_anchor, css_anchor + ".vc-artist-inline{font-weight:700;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}.vc-artist-inline:hover{color:var(--vc-red)}", 1)
        else:
            text = text.replace(css_anchor, css_add, 1)

    # Inline links in the main story paragraphs.
    old_body = "    const body = (story.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('');"
    new_body = "    const body = (story.paragraphs || []).map(p => `<p>${artistLinkedText(p, story)}</p>`).join('');"
    if old_body in text:
        text = text.replace(old_body, new_body, 1)
    elif new_body not in text:
        raise ValueError("renderStory body anchor missing")

    # Inline links in rich article sections too.
    old_rich = "    const ps = (section.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('');\n    const bullets = (section.bullets || []).length ? `<ul>${section.bullets.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';"
    new_rich = "    const ps = (section.paragraphs || []).map(p => `<p>${artistLinkedText(p, story)}</p>`).join('');\n    const bullets = (section.bullets || []).length ? `<ul>${section.bullets.map(x => `<li>${artistLinkedText(x, story)}</li>`).join('')}</ul>` : '';"
    if old_rich in text:
        text = text.replace(old_rich, new_rich, 1)

    # richSections needs story context if not already present.
    old_sig = "  const richSections = (story) => (story?.article_sections || []).map(section => {"
    if old_sig not in text:
        raise ValueError("richSections signature missing")

    # Ensure complete profile index is rendered below article body.
    old_insert = '${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}<section class="vc-article-sources">'
    new_insert = '${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}${artistProfiles(story)}<section class="vc-article-sources">'
    if new_insert not in text:
        if old_insert not in text:
            raise ValueError("renderStory artist insertion anchor missing")
        text = text.replace(old_insert, new_insert, 1)

    # Artist-only feed changes must invalidate the bridge fingerprint.
    old_fp = "`${s.id}:${s.headline}:${(s.article_sections || []).length}`"
    new_fp = "`${s.id}:${s.headline}:${(s.article_sections || []).length}:${(s.artist_profiles || []).map(a => `${a.id}:${a.path}`).join(',')}`"
    if old_fp in text:
        text = text.replace(old_fp, new_fp, 1)

    return text


def validate(text: str) -> None:
    required = [
        PROFILE_MARKER,
        INLINE_MARKER,
        ".vc-artist-inline{",
        ".vc-artistlinks{",
        "artistLinkedText(p, story)",
        "${artistProfiles(story)}<section class=\"vc-article-sources\">",
        "Artiști și creatori din acest material",
        "href=\"/artisti/\"",
        "external_identity_verified",
        "artist_profiles || []",
    ]
    missing = [value for value in required if value not in text]
    if missing:
        raise ValueError("artist bridge contract incomplete: " + ", ".join(missing))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    original = TARGET.read_text(encoding="utf-8")
    updated = patch(original)
    validate(updated)
    if args.check:
        print("VÂLCEA CLAR live bridge artist/creator UI contract: PASS")
        return 0
    if updated != original:
        TARGET.write_text(updated, encoding="utf-8")
        print("VÂLCEA CLAR live bridge artist/creator UI patch: UPDATED")
    else:
        print("VÂLCEA CLAR live bridge artist/creator UI patch: ALREADY_CURRENT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
