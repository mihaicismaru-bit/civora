from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]


def _load(rel: str) -> dict[str, Any]:
    path = ROOT / rel
    if not path.is_file():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return doc if isinstance(doc, dict) else {}


def _story_key(value: str) -> str:
    return value[6:] if value.startswith("story-") else value


def _public_url_filename(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    name = Path(urlparse(text).path).name
    return name or None


def _canonical_visual_binding(
    *,
    expected_image_path: Any,
    visual_source_url: Any,
    visual_rights_basis: Any,
    real_visual: bool,
    manifest_image: Any,
) -> dict[str, Any]:
    expected_filename = Path(str(expected_image_path)).name if expected_image_path else None
    base = {
        "canonical_site_expected_visual_filename": expected_filename,
        "canonical_site_observed_visual_filename": None,
        "canonical_site_image_public_url": None,
        "canonical_site_image_source_url": None,
        "canonical_site_image_rights_basis": None,
        "canonical_site_image_provenance_status": None,
        "canonical_site_image_bound": False,
        "canonical_site_visual_filename_match": False,
        "canonical_site_visual_source_match": False,
        "canonical_site_visual_rights_match": False,
        "canonical_site_visual_provenance_verified": False,
    }
    if not real_visual:
        return {**base, "canonical_site_visual_binding_state": "NOT_READY"}
    if not isinstance(manifest_image, dict):
        return {**base, "canonical_site_visual_binding_state": "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND"}

    public_url = str(manifest_image.get("public_url") or "").strip() or None
    observed_filename = _public_url_filename(public_url)
    source_url = str(manifest_image.get("source_url") or "").strip() or None
    rights_basis = str(manifest_image.get("rights_basis") or "").strip() or None
    provenance_status = str(manifest_image.get("provenance_status") or "").strip() or None
    expected_source_url = str(visual_source_url or "").strip() or None
    expected_rights_basis = str(visual_rights_basis or "").strip() or None

    filename_match = bool(expected_filename and observed_filename and expected_filename == observed_filename)
    source_match = bool(expected_source_url and source_url and expected_source_url == source_url)
    rights_match = bool(expected_rights_basis and rights_basis and expected_rights_basis == rights_basis)
    provenance_verified = provenance_status == "VERIFIED"
    bound = bool(public_url and observed_filename)
    detail = {
        **base,
        "canonical_site_observed_visual_filename": observed_filename,
        "canonical_site_image_public_url": public_url,
        "canonical_site_image_source_url": source_url,
        "canonical_site_image_rights_basis": rights_basis,
        "canonical_site_image_provenance_status": provenance_status,
        "canonical_site_image_bound": bound,
        "canonical_site_visual_filename_match": filename_match,
        "canonical_site_visual_source_match": source_match,
        "canonical_site_visual_rights_match": rights_match,
        "canonical_site_visual_provenance_verified": provenance_verified,
    }

    if not bound:
        state = "SITE_BINDING_METADATA_INCOMPLETE"
    elif not filename_match:
        state = "SITE_BOUND_DIFFERENT_ASSET"
    elif not source_match:
        state = "SITE_BOUND_SOURCE_DRIFT"
    elif not rights_match:
        state = "SITE_BOUND_RIGHTS_DRIFT"
    elif not provenance_verified:
        state = "SITE_BOUND_UNVERIFIED_PROVENANCE"
    else:
        state = "CONSISTENT"
    return {**detail, "canonical_site_visual_binding_state": state}


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
        visual_binding = _canonical_visual_binding(
            expected_image_path=image_path,
            visual_source_url=image.get("source_url") if isinstance(image, dict) else None,
            visual_rights_basis=image.get("rights_basis") if isinstance(image, dict) else None,
            real_visual=real_visual,
            manifest_image=item.get("image"),
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
                **visual_binding,
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
    binding_state_counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("canonical_site_visual_binding_state") or "UNKNOWN")
        binding_state_counts[state] = binding_state_counts.get(state, 0) + 1
    return {
        "schema_version": "1.2",
        "mode": "SHADOW_ONLY",
        "publication_authority": "NONE",
        "truth_rule": "internal IDs, internal visual metadata and state never equal external delivery",
        "visual_cross_surface_truth_rule": "an approved social visual is not site-bound unless canonical manifest image metadata binds the same filename, source, rights basis and VERIFIED provenance",
        "current_manifest_story_count": len(rows),
        "eligible_for_external_replay_count": len(eligible_for_external_replay),
        "canonical_site_visual_binding_state_counts": binding_state_counts,
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
    print(json.dumps({k: result[k] for k in ("current_manifest_story_count", "eligible_for_external_replay_count", "canonical_site_visual_binding_state_counts", "first_ten_candidate_ids", "acceptance_ready")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
