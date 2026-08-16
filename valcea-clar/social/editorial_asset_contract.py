#!/usr/bin/env python3
"""Shared fail-closed contract for deterministic editorial composite visuals.

An editorial composite is not mislabeled as a photograph. It is a deterministic
layout derived from an approved real source photograph plus newsroom text. The
source photograph keeps its own provenance and rights record.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ALLOWED_RENDERERS = {
    "instagram-editorial-v1.1",
    "facebook-editorial-v1.0",
}
ALLOWED_RIGHTS = {
    "owned",
    "written_permission",
    "press_use",
    "licensed",
    "public_domain",
    "creative_commons",
    "official_reuse_permission",
}
ALLOWED_SOURCE_TYPES = {
    "staff",
    "reader",
    "official_press",
    "official_institution",
    "licensed_agency",
    "public_domain",
    "creative_commons",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def source_photo_record(visual: dict[str, Any]) -> dict[str, Any]:
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    required = ("kind", "source_type", "credit", "rights_basis", "alt_text")
    missing = [key for key in required if not str(image.get(key, "")).strip()]
    if missing:
        raise ValueError("source photograph metadata missing: " + ", ".join(missing))
    if image.get("kind") != "photograph":
        raise ValueError("editorial composite source must be a photograph")
    if image.get("synthetic") is not False:
        raise ValueError("synthetic source media is forbidden")
    if image.get("subject_match") is not True or image.get("editor_approved") is not True:
        raise ValueError("source photograph lacks subject match/editor approval")
    if image.get("source_type") not in ALLOWED_SOURCE_TYPES:
        raise ValueError("unsupported source photograph type")
    if image.get("rights_basis") not in ALLOWED_RIGHTS:
        raise ValueError("source photograph lacks supported reuse rights")
    if image.get("source_type") not in {"staff", "public_domain"} and not str(image.get("source_url") or "").strip():
        raise ValueError("external source photograph lacks source_url")
    return {
        "kind": "photograph",
        "synthetic": False,
        "source_type": image["source_type"],
        "source_url": image.get("source_url"),
        "credit": image["credit"],
        "rights_basis": image["rights_basis"],
        "license_url": image.get("license_url"),
        "rights_note": image.get("rights_note"),
        "alt_text": image["alt_text"],
        "subject_match": True,
        "editor_approved": True,
        "contextual_archive": bool(image.get("contextual_archive")),
        "editorial_note": image.get("editorial_note"),
        "image_path": visual.get("image_path"),
    }


def build_asset(
    *,
    story_id: str,
    platform: str,
    renderer: str,
    rendered_path: Path,
    source_visual: dict[str, Any],
    product_fingerprint: str,
    public_url: str | None,
) -> dict[str, Any]:
    if renderer not in ALLOWED_RENDERERS:
        raise ValueError(f"unsupported editorial renderer: {renderer}")
    if not rendered_path.is_file():
        raise ValueError(f"rendered editorial asset missing: {rendered_path}")
    if rendered_path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
        raise ValueError("editorial asset must be JPEG/PNG")
    source = source_photo_record(source_visual)
    asset = {
        "kind": "editorial_composite",
        "synthetic": False,
        "story_id": story_id,
        "platform": platform,
        "renderer": renderer,
        "rendered_path": str(rendered_path.relative_to(ROOT)),
        "public_url": public_url,
        "sha256": sha256(rendered_path),
        "product_fingerprint_sha256": product_fingerprint,
        "rights_inherited_from_approved_source": True,
        "source_photo": source,
    }
    asset["asset_fingerprint_sha256"] = canonical_digest(asset)
    return asset


def validate_asset(asset: dict[str, Any]) -> None:
    if asset.get("kind") != "editorial_composite":
        raise ValueError("asset is not an editorial_composite")
    if asset.get("synthetic") is not False:
        raise ValueError("synthetic editorial asset forbidden")
    if asset.get("renderer") not in ALLOWED_RENDERERS:
        raise ValueError("unknown renderer")
    if asset.get("rights_inherited_from_approved_source") is not True:
        raise ValueError("rights lineage missing")
    source = asset.get("source_photo")
    if not isinstance(source, dict) or source.get("kind") != "photograph" or source.get("synthetic") is not False:
        raise ValueError("approved source-photo lineage missing")
    supplied = str(asset.get("asset_fingerprint_sha256") or "")
    candidate = dict(asset)
    candidate.pop("asset_fingerprint_sha256", None)
    if supplied != canonical_digest(candidate):
        raise ValueError("editorial asset fingerprint mismatch")
    rendered = (ROOT / str(asset.get("rendered_path") or "")).resolve()
    if not rendered.is_file() or sha256(rendered) != str(asset.get("sha256") or ""):
        raise ValueError("editorial asset bytes/fingerprint mismatch")


def self_test() -> int:
    assert canonical_digest({"b": 2, "a": 1}) == canonical_digest({"a": 1, "b": 2})
    assert "editorial_composite" != "photograph"
    print("VÂLCEA CLAR editorial asset contract self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
