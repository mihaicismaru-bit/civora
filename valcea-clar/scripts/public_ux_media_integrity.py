#!/usr/bin/env python3
"""Extend canonical story integrity with explicit contextual photographs.

Exact verified story media always wins. Contextual media is admitted only from
the explicit presentation registry and is disclosed on the article page.
"""
from __future__ import annotations

import json
from urllib.parse import urlparse

import public_ux_media as media
import public_ux_story_integrity as integrity

ux = integrity.ux
_ORIGINAL_RESOLVER = integrity.verified_image_for_story


def verified_image_for_story(story_id: str, visual_registry: dict, asset_manifest: dict):
    exact = _ORIGINAL_RESOLVER(story_id, visual_registry, asset_manifest)
    if exact:
        return exact
    _exact, contextual = media.media_indexes()
    return contextual.get(story_id)


def image_head_and_figure(image: dict | None, headline: str) -> tuple[str, str]:
    if not isinstance(image, dict) or image.get("provenance_status") != "VERIFIED" or not image.get("public_url"):
        return "", ""
    public_url = str(image["public_url"])
    source_url = str(image.get("source_url") or "")
    credit = str(image.get("credit") or "Sursă foto verificată")
    alt_text = str(image.get("alt_text") or headline)
    parsed = urlparse(public_url)
    local_hosts = {"", "valceaclar.ro", "www.valceaclar.ro"}
    src = parsed.path if parsed.netloc in local_hosts else public_url
    head = (
        f'<meta property="og:image" content="{ux.esc(public_url)}">'
        f'<meta property="og:image:alt" content="{ux.esc(alt_text)}">'
        f'<meta name="twitter:image" content="{ux.esc(public_url)}">'
        f'<meta name="twitter:image:alt" content="{ux.esc(alt_text)}">'
    )
    disclosure = ""
    if image.get("contextual_archive") is True:
        note = str(image.get("editorial_note") or "Foto de context; imaginea nu documentează evenimentul descris.")
        disclosure = f' · {ux.esc(note)}'
    credit_html = ux.esc(credit)
    if source_url:
        credit_html = f'<a href="{ux.esc(source_url)}" rel="nofollow noopener">{credit_html}</a>'
    figure = (
        f'<figure data-photo-provenance="verified" data-media-context="{"contextual" if image.get("contextual_archive") else "exact"}">'
        f'<img src="{ux.esc(src)}" alt="{ux.esc(alt_text)}" loading="eager" '
        'style="width:100%;max-height:560px;object-fit:cover;display:block;margin:24px 0 7px">'
        f'<figcaption style="font-size:11px;color:#6c665c">Foto: {credit_html}{disclosure}</figcaption></figure>'
    )
    return head, figure


integrity.verified_image_for_story = verified_image_for_story
integrity.image_head_and_figure = image_head_and_figure


def validate_contextual_projection() -> dict:
    manifest = integrity.load(integrity.MANIFEST, {"stories": []})
    contextual = [row for row in manifest.get("stories") or [] if isinstance(row.get("image"), dict) and row["image"].get("contextual_archive") is True]
    if not contextual:
        raise SystemExit("Story media integrity projected no contextual photographs")
    checked = 0
    for row in contextual:
        page = integrity.RUNTIME / str(row["path"]).strip("/") / "index.html"
        text = page.read_text(encoding="utf-8")
        if 'data-media-context="contextual"' not in text:
            raise SystemExit(f"Contextual disclosure marker missing: {row['id']}")
        if str(row["image"].get("editorial_note") or "") not in text:
            raise SystemExit(f"Contextual editorial note missing: {row['id']}")
        checked += 1
    result = {"status": "PASS", "contextual_story_pages": checked}
    print(json.dumps(result, ensure_ascii=False))
    return result


def self_test() -> int:
    integrity.self_test()
    head, figure = image_head_and_figure({
        "public_url": "https://example.test/photo.jpg",
        "source_url": "https://example.test/source",
        "credit": "Credit",
        "provenance_status": "VERIFIED",
        "contextual_archive": True,
        "editorial_note": "Foto de context.",
    }, "Titlu")
    assert 'https://example.test/photo.jpg' in head
    assert 'src="https://example.test/photo.jpg"' in figure
    assert 'data-media-context="contextual"' in figure
    print("VÂLCEA CLAR contextual story-media integrity self-test: PASS")
    return 0


def main() -> int:
    import sys
    if "--self-test" in sys.argv:
        return self_test()
    if "--check" in sys.argv:
        integrity.check()
        validate_contextual_projection()
        return 0
    integrity.build()
    validate_contextual_projection()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
