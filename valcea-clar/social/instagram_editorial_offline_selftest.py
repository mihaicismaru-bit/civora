#!/usr/bin/env python3
"""Hermetic Instagram editorial adapter self-test.

This test exercises the premium fact-check carousel and mocked Graph publish path
without requiring any network-fetched photo. It deliberately uses the real,
rights-documented CET Govora archive photograph that is pinned in the repository.
Production eligibility, live credentials and external publishing remain untouched.
"""
from __future__ import annotations

import json
from pathlib import Path

import instagram_editorial_publish as adapter


FIXTURE_STORY_ID = "cet-govora-cine-a-decis-oprirea-20260821"
PINNED_PHOTO = (
    adapter.ROOT
    / "valcea-clar"
    / "social"
    / "photos"
    / "approved"
    / "cet-govora-context-2011.jpg"
).resolve()


def main() -> int:
    assert adapter.state_key("x") == "story-x"
    assert "olanesti-bridge-monitor" not in adapter.canonical_story_ready_ids()

    visuals = adapter.load(adapter.VISUALS)
    visual = adapter.ig.base.visual_for(FIXTURE_STORY_ID, visuals)
    if not isinstance(visual, dict):
        raise AssertionError(f"fixture visual missing: {FIXTURE_STORY_ID}")
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    source = (adapter.ROOT / str(visual.get("image_path") or "")).resolve()
    assert source == PINNED_PHOTO
    assert source.is_file(), f"pinned real-photo fixture missing: {source}"
    assert source.stat().st_size >= 50_000
    assert image.get("kind") == "photograph"
    assert image.get("synthetic") is False
    assert image.get("subject_match") is True
    assert image.get("editor_approved") is True
    assert str(image.get("rights_basis") or "") in {"creative_commons", "public_domain"}
    assert str(image.get("source_url") or "").startswith("https://")
    assert str(image.get("direct_source_url") or "").startswith("https://")

    story = {
        "id": FIXTURE_STORY_ID,
        "editorial_type": "fact_check",
        "section": "ENERGIE",
        "headline": "CET Govora: cine a decis oprirea",
        "dek": "Documentele oficiale permit verificarea afirmațiilor publice despre oprire.",
        "paragraphs": ["Document verificat suficient pentru test." for _ in range(5)],
    }
    product = adapter.render_product(story, visual, adapter.load(adapter.SYSTEM))
    if product.get("status") != "READY":
        raise AssertionError(f"hermetic fixture not READY: {product}")
    assert product["native_format"] == "carousel"
    assert 2 <= len(product["assets"]) <= 10
    assert product["assets"][0]["kind"] == "editorial_composite"
    assert all(asset["synthetic"] is False for asset in product["assets"])
    assert all(str(asset["public_url"]).startswith(adapter.PUBLIC_BASE) for asset in product["assets"])
    assert all(asset["kind"] == "editorial_text_card" for asset in product["assets"][1:])
    assert "OUG 20/2026" in json.dumps(product, ensure_ascii=False)
    assert all(
        (adapter.DIST / Path(asset["rendered_path"]).name).is_file()
        for asset in product["assets"]
    )

    ok, reason = adapter.public_urls_ready(
        product,
        lambda url: (_ for _ in ()).throw(RuntimeError("not deployed yet")),
    )
    assert ok is False and "not deployed yet" in str(reason)
    assert adapter.public_urls_ready(product, lambda url: None) == (True, None)

    calls: list[tuple[str, dict[str, str]]] = []
    counter = {"n": 0}

    def fake_post(host, version, path, token, fields):
        calls.append((path, dict(fields)))
        counter["n"] += 1
        if path.endswith("/media_publish"):
            return {"id": "published-media-id"}
        return {"id": f"container-{counter['n']}"}

    def fake_get(host, version, path, token, params=None):
        return {"status_code": "FINISHED"}

    result = adapter.publish_product(
        product,
        account_id="17841439178488749",
        token="fixture-token-never-logged",
        version="v26.0",
        host="graph.facebook.com",
        graph_post_fn=fake_post,
        graph_get_fn=fake_get,
        sleep_fn=lambda seconds: None,
    )
    assert result["instagram_media_id"] == "published-media-id"
    assert len(result["child_container_ids"]) == len(product["assets"])
    assert any(fields.get("media_type") == "CAROUSEL" for _, fields in calls)
    assert calls[-1][0].endswith("/media_publish")

    print(
        "VÂLCEA CLAR Instagram editorial hermetic self-test: PASS "
        f"({len(product['assets'])} assets; pinned real photo; zero network)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
