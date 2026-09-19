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


def _derived_path(direct_url: str) -> str:
    parsed = urlsplit(direct_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("verified HTTPS direct_source_url required")
    suffix = PurePosixPath(unquote(parsed.path)).suffix.lower()
    if suffix not in _ALLOWED_SUFFIXES:
        suffix = ".img"
    digest = hashlib.sha256(direct_url.encode("utf-8")).hexdigest()[:20]
    return f"__core_v2_remote__/remote-{digest}{suffix}"


def hydrate_registry(registry: dict[str, Any], photo_truth: dict[str, Any]) -> dict[str, Any]:
    if registry.get("publication_authority") != "NONE":
        raise ValueError("visual registry publication_authority must be NONE")
    if photo_truth.get("publication_authority") != "NONE" or photo_truth.get("acceptance_ready") is True:
        raise ValueError("photo truth escaped shadow authority")
    stories = copy.deepcopy(registry.get("stories") or {})
    hydrated: list[str] = []
    preserved: list[str] = []
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
        assignment["runtime_image_path_basis"] = "derived_filename_from_verified_direct_source_url"
        hydrated.append(story_id)
    return {
        "schema_version": "1.0",
        "mode": MODE,
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "hydrated_story_count": len(hydrated),
        "preserved_story_count": len(preserved),
        "hydrated_story_ids": hydrated,
        "preserved_story_ids": preserved,
        "stories": stories,
        "truth_rule": "This runtime adapter only provides deterministic temporary filenames for already verified real-photo direct source URLs. It does not alter provenance, rights, semantic relevance, approval or delivery truth and grants no publication authority.",
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
            "schema_version": "1.0", "mode": MODE, "status": "BLOCKED", "publication_authority": "NONE",
            "acceptance_ready": False, "site_publish_allowed": False, "social_publish_allowed": False, "stories": {}, "reason": str(exc),
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "publication_authority": "NONE"}, ensure_ascii=False, sort_keys=True))
        return 1
    report["status"] = "PASS_SHADOW"
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS_SHADOW", "hydrated_story_count": report["hydrated_story_count"], "preserved_story_count": report["preserved_story_count"], "publication_authority": "NONE", "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
