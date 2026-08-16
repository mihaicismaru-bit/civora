#!/usr/bin/env python3
"""Fail-closed resolver for provenance-backed story photographs.

The resolver is deliberately instance-agnostic. It does not decide whether a
story is editorially publishable; callers must pass only stories that already
cleared their publication gate. It only decides whether an already-approved
visual record can safely be projected into a public static runtime.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse


def _https(value: object) -> str | None:
    text = str(value or "").strip()
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        return None
    return text


def resolve_verified_story_image(
    story_id: object,
    visual_registry: dict,
    asset_manifest: dict,
    *,
    runtime_asset_dir: Path,
    canonical_media_base_url: str,
) -> dict | None:
    """Return a public image record only when provenance is internally coherent.

    Missing or conflicting metadata returns ``None`` rather than weakening the
    story publication gate. Contextual/archive photographs are allowed only when
    the visual registry explicitly requires disclosure and the record contains a
    captured date plus an editorial disclosure note.
    """
    sid = str(story_id or "").strip()
    if not sid:
        return None

    policy = visual_registry.get("policy") or {}
    required_policy = (
        "real_photographs_only",
        "rights_metadata_required",
        "editor_approval_required",
        "archival_context_requires_explicit_disclosure",
    )
    if any(policy.get(key) is not True for key in required_policy):
        return None

    story = (visual_registry.get("stories") or {}).get(sid)
    if not isinstance(story, dict):
        return None
    image = story.get("image") or {}
    if not isinstance(image, dict):
        return None
    if image.get("kind") != "photograph" or image.get("synthetic") is not False:
        return None
    if image.get("editor_approved") is not True or image.get("subject_match") is not True:
        return None

    required = ("credit", "rights_basis", "source_url", "alt_text")
    if any(not str(image.get(key) or "").strip() for key in required):
        return None
    source_url = _https(image.get("source_url"))
    if not source_url:
        return None

    contextual = image.get("contextual_archive") is True
    if contextual:
        if not str(image.get("captured_at") or "").strip():
            return None
        if not str(image.get("editorial_note") or "").strip():
            return None

    image_path = str(story.get("image_path") or "").strip()
    filename = Path(image_path).name if image_path else ""
    if not filename or filename in {".", ".."}:
        return None

    asset = next(
        (
            row
            for row in (asset_manifest.get("assets") or [])
            if isinstance(row, dict) and str(row.get("filename") or "") == filename
        ),
        None,
    )
    if not asset:
        return None
    if asset.get("kind") != "source_photograph" or asset.get("synthetic") is not False:
        return None

    for key in ("credit", "rights_basis", "source_url"):
        if str(asset.get(key) or "").strip() != str(image.get(key) or "").strip():
            return None

    public_url = _https(asset.get("public_url"))
    media_base = _https(canonical_media_base_url)
    if not public_url or not media_base:
        return None
    media_base = media_base.rstrip("/") + "/"
    if not public_url.startswith(media_base):
        return None

    local = Path(runtime_asset_dir) / filename
    if not local.is_file():
        return None

    license_url = None
    if image.get("license_url") not in (None, ""):
        license_url = _https(image.get("license_url"))
        if not license_url:
            return None

    return {
        "filename": filename,
        "public_url": public_url,
        "relative_url": urlparse(public_url).path,
        "source_url": source_url,
        "credit": str(image["credit"]).strip(),
        "rights_basis": str(image["rights_basis"]).strip(),
        "license_url": license_url,
        "alt_text": str(image["alt_text"]).strip(),
        "contextual_archive": contextual,
        "captured_at": str(image.get("captured_at") or "").strip() or None,
        "editorial_note": str(image.get("editorial_note") or "").strip() or None,
        "synthetic": False,
        "provenance_status": "VERIFIED",
    }


def _self_test() -> None:
    registry = {
        "policy": {
            "real_photographs_only": True,
            "rights_metadata_required": True,
            "editor_approval_required": True,
            "archival_context_requires_explicit_disclosure": True,
        },
        "stories": {
            "story-a": {
                "image_path": "instance/social/photos/a.jpg",
                "image": {
                    "kind": "photograph",
                    "synthetic": False,
                    "subject_match": True,
                    "editor_approved": True,
                    "contextual_archive": True,
                    "captured_at": "2020-01-02",
                    "source_url": "https://commons.example/a",
                    "credit": "Example / Commons — CC BY 4.0",
                    "rights_basis": "creative_commons",
                    "license_url": "https://creativecommons.org/licenses/by/4.0/",
                    "editorial_note": "Foto de arhivă; nu surprinde evenimentul curent.",
                    "alt_text": "Locul fotografiat într-o imagine de arhivă.",
                },
            }
        },
    }
    assets = {
        "assets": [
            {
                "filename": "a.jpg",
                "kind": "source_photograph",
                "synthetic": False,
                "public_url": "https://local.example/media/social/a.jpg",
                "credit": "Example / Commons — CC BY 4.0",
                "rights_basis": "creative_commons",
                "source_url": "https://commons.example/a",
            }
        ]
    }
    with TemporaryDirectory() as tmp:
        asset_dir = Path(tmp)
        (asset_dir / "a.jpg").write_bytes(b"real-photo-fixture")
        resolved = resolve_verified_story_image(
            "story-a",
            registry,
            assets,
            runtime_asset_dir=asset_dir,
            canonical_media_base_url="https://local.example/media/social/",
        )
        assert resolved and resolved["provenance_status"] == "VERIFIED"
        assert resolved["relative_url"] == "/media/social/a.jpg"
        assert resolved["contextual_archive"] is True

        bad = {**assets, "assets": [{**assets["assets"][0], "credit": "Mismatch"}]}
        assert resolve_verified_story_image(
            "story-a",
            registry,
            bad,
            runtime_asset_dir=asset_dir,
            canonical_media_base_url="https://local.example/media/social/",
        ) is None

        (asset_dir / "a.jpg").unlink()
        assert resolve_verified_story_image(
            "story-a",
            registry,
            assets,
            runtime_asset_dir=asset_dir,
            canonical_media_base_url="https://local.example/media/social/",
        ) is None

    print("VERIFIED_STORY_MEDIA_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
