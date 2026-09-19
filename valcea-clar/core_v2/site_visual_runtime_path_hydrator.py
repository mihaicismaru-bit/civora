from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit


MODE = "CORE_V2_SHADOW_VISUAL_RUNTIME_PATH_HYDRATION"
_ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
_WIKIMEDIA_THUMB_WIDTH = 960
_WIKIMEDIA_429_FALLBACK = "wikimedia_commons_source_page_identity_fallback_for_direct_429"


def _derived_path(direct_url: str) -> str:
    parsed = urlsplit(direct_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("verified HTTPS direct_source_url required")
    suffix = PurePosixPath(unquote(parsed.path)).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        suffix = ".img"
    digest = hashlib.sha256(direct_url.encode("utf-8")).hexdigest()[:20]
    return f"__core_v2_remote__/remote-{digest}{suffix}"


def _wikimedia_thumbnail_url(direct_url: str) -> str | None:
    """Return one deterministic thumbnail URL for the exact Wikimedia original.

    This is transport-only. The canonical original remains the provenance identity.
    """
    parsed = urlsplit(direct_url)
    if parsed.scheme != "https" or parsed.netloc.lower() != "upload.wikimedia.org":
        return None
    parts = parsed.path.split("/")
    if len(parts) != 6 or parts[:3] != ["", "wikipedia", "commons"]:
        return None
    shard_a, shard_b, encoded_filename = parts[3], parts[4], parts[5]
    suffix = PurePosixPath(unquote(encoded_filename)).suffix.lower()
    if not shard_a or not shard_b or not encoded_filename or suffix not in _ALLOWED_SUFFIXES:
        return None
    return (
        "https://upload.wikimedia.org/wikipedia/commons/thumb/"
        f"{shard_a}/{shard_b}/{encoded_filename}/"
        f"{_WIKIMEDIA_THUMB_WIDTH}px-{encoded_filename}"
    )


def _verified_wikimedia_429_thumbnail(row: dict[str, Any], image: dict[str, Any]) -> str | None:
    external = row.get("external_readback") or {}
    direct_probe = external.get("direct_source") or {}
    provenance = external.get("provenance_asset") or {}
    source_url = str(image.get("source_url") or "").strip()
    direct_url = str(image.get("direct_source_url") or "").strip()

    source_host = urlsplit(source_url).netloc.lower()
    if source_host != "commons.wikimedia.org":
        return None
    if external.get("readback_ok") is not True or external.get("direct_source_effective_ok") is not True:
        return None
    if str(external.get("direct_source_fallback") or "") != _WIKIMEDIA_429_FALLBACK:
        return None
    if int(direct_probe.get("http_status") or 0) != 429 or direct_probe.get("rate_limited") is not True:
        return None
    if provenance.get("asset_identity_ok") is not True or provenance.get("license_present") is not True:
        return None
    expected_filename = str(provenance.get("expected_filename") or "").strip()
    actual_filename = PurePosixPath(urlsplit(direct_url).path).name
    if not expected_filename or expected_filename != actual_filename:
        return None
    return _wikimedia_thumbnail_url(direct_url)


def hydrate_registry(registry: dict[str, Any], photo_truth: dict[str, Any]) -> dict[str, Any]:
    if registry.get("publication_authority") != "NONE":
        raise ValueError("visual registry publication_authority must be NONE")
    if photo_truth.get("publication_authority") != "NONE" or photo_truth.get("acceptance_ready") is True:
        raise ValueError("photo truth escaped shadow authority")
    stories = copy.deepcopy(registry.get("stories") or {})
    hydrated: list[str] = []
    preserved: list[str] = []
    transport_fallback: list[str] = []
    for row in photo_truth.get("rows") or []:
        if row.get("status") != "VISUAL_CANDIDATE_VERIFIED_SHADOW":
            continue
        if not bool((row.get("external_readback") or {}).get("readback_ok")):
            raise ValueError("verified visual candidate lacks external readback truth")
        story_id = str(row.get("story_id") or "").strip()
        assignment = stories.get(story_id)
        if not isinstance(assignment, dict):
            raise ValueError(f"verified visual assignment missing from registry: {story_id}")
        image = assignment.get("image") or {}
        if image.get("kind") != "photograph" or image.get("synthetic") is True:
            raise ValueError(f"non-photographic or synthetic visual cannot be hydrated: {story_id}")
        current = str(assignment.get("image_path") or "").strip()
        if current:
            preserved.append(story_id)
            continue
        direct = str(image.get("direct_source_url") or "").strip()
        assignment["image_path"] = _derived_path(direct)
        assignment["runtime_image_path_basis"] = "derived_filename_from_verified_canonical_direct_source_url"

        thumbnail = _verified_wikimedia_429_thumbnail(row, image)
        if thumbnail:
            image["canonical_direct_source_url"] = direct
            image["direct_source_url"] = thumbnail
            assignment["runtime_materialization_url"] = thumbnail
            assignment["runtime_materialization_canonical_direct_source_url"] = direct
            assignment["runtime_materialization_basis"] = (
                "wikimedia_960px_derivative_of_exact_provenance_asset_after_verified_original_429"
            )
            assignment["runtime_transport_override_only"] = True
            transport_fallback.append(story_id)
        else:
            assignment["runtime_materialization_basis"] = "verified_canonical_direct_source_url"
            assignment["runtime_transport_override_only"] = False
        hydrated.append(story_id)
    return {
        "schema_version": "1.1",
        "mode": MODE,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "hydrated_story_count": len(hydrated),
        "preserved_story_count": len(preserved),
        "transport_fallback_story_count": len(transport_fallback),
        "hydrated_story_ids": hydrated,
        "preserved_story_ids": preserved,
        "transport_fallback_story_ids": transport_fallback,
        "stories": stories,
        "truth_rule": (
            "This runtime adapter only provides deterministic temporary filenames for already verified real-photo assets. "
            "If the exact Wikimedia original is externally verified by its Commons ImageObject and the original binary probe is specifically rate-limited with HTTP 429, "
            "a deterministic 960px Wikimedia derivative of that exact asset may be used for shadow transport only. "
            "The canonical original URL is preserved explicitly; provenance, rights, semantic relevance, approval and delivery truth are unchanged, and no publication authority is granted."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Hydrate temporary shadow image paths for verified remote Core v2 visuals")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--photo-truth", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = hydrate_registry(
            json.loads(Path(args.registry).read_text(encoding="utf-8")),
            json.loads(Path(args.photo_truth).read_text(encoding="utf-8")),
        )
    except Exception as exc:
        report = {
            "schema_version": "1.1", "mode": MODE, "status": "BLOCKED", "publication_authority": "NONE",
            "acceptance_ready": False, "site_publish_allowed": False, "social_publish_allowed": False, "stories": {}, "reason": str(exc),
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "publication_authority": "NONE"}, ensure_ascii=False, sort_keys=True))
        return 1
    report["status"] = "PASS_SHADOW"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS_SHADOW",
        "hydrated_story_count": report["hydrated_story_count"],
        "preserved_story_count": report["preserved_story_count"],
        "transport_fallback_story_count": report["transport_fallback_story_count"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
