from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def _story_key(value: str) -> str:
    return value[6:] if value.startswith("story-") else value


def build() -> dict[str, Any]:
    manifest = _load("valcea-clar/site/runtime/stiri/manifest.json")
    visuals = (_load("valcea-clar/social/story_visuals.json").get("stories") or {})
    fb = (_load("valcea-clar/social/facebook_state.json").get("published") or {})
    ig = (_load("valcea-clar/social/instagram_state.json").get("published") or {})

    fb_by_story = {_story_key(str(k)): v for k, v in fb.items() if isinstance(v, dict)}
    ig_by_story = {_story_key(str(k)): v for k, v in ig.items() if isinstance(v, dict)}
    rows = []
    for item in manifest.get("stories") or []:
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("id") or "").strip()
        if not story_id:
            continue
        if item.get("archive_status") == "published_archive":
            continue
        visual = visuals.get(story_id) if isinstance(visuals, dict) else None
        image = (visual or {}).get("image") if isinstance(visual, dict) else None
        image_path = (visual or {}).get("image_path") if isinstance(visual, dict) else None
        real_visual = bool(
            isinstance(image, dict)
            and image.get("kind") == "photograph"
            and image.get("synthetic") is False
            and image.get("subject_match") is True
            and image.get("editor_approved") is True
            and image.get("rights_basis")
            and image.get("source_url")
        )
        fb_row = fb_by_story.get(story_id) or {}
        ig_row = ig_by_story.get(story_id) or {}
        facebook_remote_id = fb_row.get("facebook_post_id")
        instagram_remote_id = ig_row.get("instagram_media_id")
        rows.append(
            {
                "story_id": story_id,
                "canonical_url": item.get("canonical"),
                "manifest_archive_status": item.get("archive_status"),
                "real_visual_internal_evidence": real_visual,
                "visual_image_path": image_path,
                "visual_filename": Path(str(image_path)).name if image_path else None,
                "visual_kind": image.get("kind") if isinstance(image, dict) else None,
                "visual_synthetic": image.get("synthetic") if isinstance(image, dict) else None,
                "visual_subject_match": image.get("subject_match") if isinstance(image, dict) else None,
                "visual_editor_approved": image.get("editor_approved") if isinstance(image, dict) else None,
                "visual_source_url": image.get("source_url") if isinstance(image, dict) else None,
                "visual_direct_source_url": image.get("direct_source_url") if isinstance(image, dict) else None,
                "visual_rights_basis": image.get("rights_basis") if isinstance(image, dict) else None,
                "visual_license_url": image.get("license_url") if isinstance(image, dict) else None,
                "visual_credit": image.get("credit") if isinstance(image, dict) else None,
                "visual_editorial_note": image.get("editorial_note") if isinstance(image, dict) else None,
                "visual_alt_text": image.get("alt_text") if isinstance(image, dict) else None,
                "facebook_remote_id_internal": facebook_remote_id,
                "instagram_remote_id_internal": instagram_remote_id,
                "site_external_readback": "PENDING",
                "visual_external_readback": "PENDING" if real_visual else "NOT_READY",
                "facebook_external_readback": "PENDING" if facebook_remote_id else "NOT_DELIVERED",
                "instagram_external_readback": "PENDING" if instagram_remote_id else "NOT_DELIVERED",
                "acceptance_state": "BLOCKED_EXTERNAL_READBACK",
            }
        )

    eligible_for_external_replay = [
        row for row in rows
        if row["canonical_url"]
        and row["real_visual_internal_evidence"]
        and row["facebook_remote_id_internal"]
        and row["instagram_remote_id_internal"]
    ]
    return {
        "schema_version": "1.1",
        "mode": "SHADOW_ONLY",
        "publication_authority": "NONE",
        "truth_rule": "internal IDs, internal visual metadata and state never equal external delivery",
        "current_manifest_story_count": len(rows),
        "eligible_for_external_replay_count": len(eligible_for_external_replay),
        "first_ten_candidate_ids": [row["story_id"] for row in eligible_for_external_replay[:10]],
        "acceptance_ready": False,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build non-authoritative Core v2 shadow replay candidates")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build()
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("current_manifest_story_count", "eligible_for_external_replay_count", "first_ten_candidate_ids", "acceptance_ready")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
