#!/usr/bin/env python3
"""Build the VÂLCEA CLAR Photo Atlas from already-approved story visuals.

The atlas is an inventory/search layer only. It never grants story assignment,
editorial approval or publication authority. Reuse of an atlas asset in a new
story must create a new explicit story_visuals.json assignment that passes the
existing photo gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
SOURCE_PATH = SOCIAL / "story_visuals.json"
ATLAS_PATH = SOCIAL / "photo_atlas.json"

ALLOWED_RIGHTS = {
    "owned",
    "written_permission",
    "press_use",
    "licensed",
    "public_domain",
    "creative_commons",
    "official_reuse_permission",
}
REQUIRED_IMAGE_FIELDS = {
    "kind",
    "synthetic",
    "subject_match",
    "editor_approved",
    "source_type",
    "source_url",
    "direct_source_url",
    "credit",
    "rights_basis",
    "rights_note",
    "alt_text",
}


class AtlasError(ValueError):
    pass


def _text(value: object) -> str:
    return str(value or "").strip()


def _asset_id(direct_source_url: str) -> str:
    digest = hashlib.sha256(direct_source_url.encode("utf-8")).hexdigest()[:20]
    return f"photo-{digest}"


def _validate_story_visuals(doc: dict[str, Any]) -> None:
    policy = doc.get("policy") or {}
    required_policy = {
        "story_specific_only": True,
        "real_photographs_only": True,
        "rights_metadata_required": True,
        "editor_approval_required": True,
        "generic_substitution_forbidden": True,
        "archival_context_requires_explicit_disclosure": True,
    }
    for key, expected in required_policy.items():
        if policy.get(key) is not expected:
            raise AtlasError(f"unsafe story visual policy: {key} must be {expected!r}")


def _validated_image(story_id: str, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    image_path = _text(row.get("image_path"))
    image = row.get("image")
    if not image_path.startswith("valcea-clar/social/photos/approved/"):
        raise AtlasError(f"{story_id}: image_path is outside approved photo root")
    if not isinstance(image, dict):
        raise AtlasError(f"{story_id}: missing image metadata")

    missing = sorted(field for field in REQUIRED_IMAGE_FIELDS if field not in image or image.get(field) in (None, ""))
    if missing:
        raise AtlasError(f"{story_id}: missing required image metadata: {', '.join(missing)}")
    if image.get("kind") != "photograph":
        raise AtlasError(f"{story_id}: non-photograph cannot enter Photo Atlas")
    if image.get("synthetic") is not False:
        raise AtlasError(f"{story_id}: synthetic/unknown image cannot enter Photo Atlas")
    if image.get("subject_match") is not True or image.get("editor_approved") is not True:
        raise AtlasError(f"{story_id}: only explicitly approved story visuals can enter Photo Atlas")

    rights_basis = _text(image.get("rights_basis"))
    if rights_basis not in ALLOWED_RIGHTS:
        raise AtlasError(f"{story_id}: unsupported rights_basis {rights_basis!r}")
    if rights_basis == "creative_commons" and not _text(image.get("license_url")).startswith("https://"):
        raise AtlasError(f"{story_id}: Creative Commons asset requires HTTPS license_url")

    source_url = _text(image.get("source_url"))
    direct_source_url = _text(image.get("direct_source_url"))
    if not source_url.startswith("https://") or not direct_source_url.startswith("https://"):
        raise AtlasError(f"{story_id}: source URLs must use HTTPS")

    contextual_archive = image.get("contextual_archive") is True
    if contextual_archive:
        if not _text(image.get("captured_at")):
            raise AtlasError(f"{story_id}: archive photo requires captured_at")
        if not _text(image.get("editorial_note")):
            raise AtlasError(f"{story_id}: archive photo requires explicit editorial_note disclosure")

    return image_path, image


def build_atlas(doc: dict[str, Any]) -> dict[str, Any]:
    _validate_story_visuals(doc)
    assets_by_url: dict[str, dict[str, Any]] = {}

    stories = doc.get("stories") or {}
    if not isinstance(stories, dict):
        raise AtlasError("story_visuals stories must be an object")

    for story_id in sorted(stories):
        row = stories[story_id]
        if not isinstance(row, dict):
            raise AtlasError(f"{story_id}: story visual row must be an object")
        image_path, image = _validated_image(story_id, row)

        direct_url = _text(image["direct_source_url"])
        contextual_archive = image.get("contextual_archive") is True
        reusable_rights = _text(image.get("rights_basis")) in {
            "creative_commons",
            "public_domain",
            "owned",
            "written_permission",
            "official_reuse_permission",
        }
        candidate_reuse_scope = (
            "contextual_archive_candidate"
            if contextual_archive and reusable_rights
            else "story_assignment_only"
        )

        invariant = {
            "source_type": _text(image["source_type"]),
            "source_url": _text(image["source_url"]),
            "credit": _text(image["credit"]),
            "rights_basis": _text(image["rights_basis"]),
            "license_url": _text(image.get("license_url")),
            "rights_note": _text(image["rights_note"]),
            "captured_at": _text(image.get("captured_at")),
            "contextual_archive": contextual_archive,
            "editorial_note": _text(image.get("editorial_note")),
            "alt_text": _text(image["alt_text"]),
        }

        existing = assets_by_url.get(direct_url)
        if existing is not None:
            compare = {key: existing.get(key, "") for key in invariant}
            if compare != invariant:
                raise AtlasError(f"{story_id}: conflicting provenance for duplicate direct_source_url")
            existing["source_story_ids"].append(story_id)
            existing["approved_paths"].append(image_path)
            continue

        assets_by_url[direct_url] = {
            "asset_id": _asset_id(direct_url),
            "kind": "photograph",
            "synthetic": False,
            "direct_source_url": direct_url,
            **invariant,
            "source_story_ids": [story_id],
            "approved_paths": [image_path],
            "candidate_reuse_scope": candidate_reuse_scope,
            "automatic_story_assignment_allowed": False,
            "new_story_subject_match_required": True,
            "new_story_editor_approval_required": True,
            "archive_disclosure_required_on_reuse": contextual_archive,
            "publication_authority": "NONE",
        }

    assets = sorted(assets_by_url.values(), key=lambda item: item["asset_id"])
    archive_candidates = sum(1 for item in assets if item["candidate_reuse_scope"] == "contextual_archive_candidate")

    return {
        "schema_version": "1.1",
        "product": "VÂLCEA CLAR PHOTO ATLAS",
        "source_of_truth": "valcea-clar/social/story_visuals.json",
        "publication_authority": "NONE",
        "policy": {
            "approved_real_photographs_only": True,
            "synthetic_assets_forbidden": True,
            "generic_stock_substitution_forbidden": True,
            "rights_metadata_required": True,
            "atlas_never_inherits_story_approval": True,
            "automatic_story_assignment_allowed": False,
            "new_story_subject_match_required": True,
            "new_story_editor_approval_required": True,
            "contextual_archive_requires_disclosure": True,
            "no_photo_is_better_than_false_relevance": True,
        },
        "summary": {
            "approved_asset_count": len(assets),
            "contextual_archive_candidate_count": archive_candidates,
            "story_assignment_only_count": len(assets) - archive_candidates,
        },
        "assets": assets,
    }


def _dump(doc: dict[str, Any]) -> str:
    return json.dumps(doc, ensure_ascii=False, indent=2, sort_keys=False) + "\n"


def self_test() -> None:
    base_image = {
        "kind": "photograph",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "contextual_archive": True,
        "captured_at": "2020-01-01",
        "source_type": "creative_commons",
        "source_url": "https://example.test/source",
        "direct_source_url": "https://example.test/photo.jpg",
        "credit": "Example / CC BY 4.0",
        "rights_basis": "creative_commons",
        "license_url": "https://creativecommons.org/licenses/by/4.0/",
        "rights_note": "Reusable under CC BY 4.0.",
        "editorial_note": "Archive photo; not the current event.",
        "alt_text": "Example archive photograph.",
    }
    fixture = {
        "policy": {
            "story_specific_only": True,
            "real_photographs_only": True,
            "rights_metadata_required": True,
            "editor_approval_required": True,
            "generic_substitution_forbidden": True,
            "archival_context_requires_explicit_disclosure": True,
        },
        "stories": {
            "one": {
                "image_path": "valcea-clar/social/photos/approved/one.jpg",
                "image": dict(base_image),
            },
            "two": {
                "image_path": "valcea-clar/social/photos/approved/two.jpg",
                "image": dict(base_image),
            },
        },
    }
    atlas = build_atlas(fixture)
    assert atlas["summary"]["approved_asset_count"] == 1
    assert atlas["assets"][0]["source_story_ids"] == ["one", "two"]
    assert atlas["assets"][0]["candidate_reuse_scope"] == "contextual_archive_candidate"
    assert atlas["assets"][0]["automatic_story_assignment_allowed"] is False
    assert atlas["assets"][0]["publication_authority"] == "NONE"

    broken = json.loads(json.dumps(fixture))
    broken["stories"]["one"]["image"].pop("rights_note")
    try:
        build_atlas(broken)
    except AtlasError:
        pass
    else:
        raise AssertionError("missing rights metadata must fail closed")

    broken = json.loads(json.dumps(fixture))
    broken["stories"]["one"]["image"].pop("captured_at")
    try:
        build_atlas(broken)
    except AtlasError:
        pass
    else:
        raise AssertionError("archive asset without captured_at must fail closed")

    broken = json.loads(json.dumps(fixture))
    broken["stories"]["two"]["image"]["credit"] = "Conflicting credit"
    try:
        build_atlas(broken)
    except AtlasError:
        pass
    else:
        raise AssertionError("duplicate asset with conflicting provenance must fail closed")

    current_only = json.loads(json.dumps(fixture))
    current_only["stories"] = {"one": current_only["stories"]["one"]}
    current_only["stories"]["one"]["image"].pop("contextual_archive")
    current_only["stories"]["one"]["image"].pop("captured_at")
    current_only["stories"]["one"]["image"].pop("editorial_note")
    atlas = build_atlas(current_only)
    assert atlas["assets"][0]["candidate_reuse_scope"] == "story_assignment_only"
    assert atlas["assets"][0]["archive_disclosure_required_on_reuse"] is False

    print("VÂLCEA CLAR Photo Atlas self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    source = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
    atlas = build_atlas(source)
    rendered = _dump(atlas)

    if args.check:
        if not ATLAS_PATH.is_file():
            raise SystemExit("Photo Atlas check failed: committed photo_atlas.json is missing")
        if ATLAS_PATH.read_text(encoding="utf-8") != rendered:
            raise SystemExit("Photo Atlas check failed: committed atlas is stale")
        print(f"VÂLCEA CLAR Photo Atlas check: PASS ({len(atlas['assets'])} approved assets)")
        return 0

    ATLAS_PATH.write_text(rendered, encoding="utf-8")
    print(f"VÂLCEA CLAR Photo Atlas written: {ATLAS_PATH} ({len(atlas['assets'])} assets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
