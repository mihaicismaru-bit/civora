#!/usr/bin/env python3
"""Expose VÂLCEA CLAR-owned Drive photos to Photo Atlas as candidates only.

The bridge joins the durable Drive metadata snapshot with the semantic-label
registry. It does not copy binaries, approve a story/photo pair, or grant
publication authority. Story-specific use still goes through
materialize_owned_photo_story.py and the explicit approval gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
SNAPSHOT = SOCIAL / "owned_photo_drive_snapshot.json"
LABELS = SOCIAL / "owned_photo_semantic_labels.json"
SOURCE = SOCIAL / "photo_atlas_owned_source.json"


class BridgeError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BridgeError(f"expected JSON object: {path}")
    return value


def asset_id(file_id: str) -> str:
    return "owned-drive-" + hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:20]


def _label_rows(labels: dict[str, Any]) -> dict[str, dict[str, Any]]:
    defaults = labels.get("defaults") or {}
    groups = labels.get("groups") or labels.get("labels") or []
    if not isinstance(groups, list):
        raise BridgeError("semantic label groups must be an array")
    out: dict[str, dict[str, Any]] = {}
    for group in groups:
        if not isinstance(group, dict):
            raise BridgeError("invalid semantic label group")
        files = group.get("files") if isinstance(group.get("files"), list) else [group.get("filename")]
        for filename in files:
            name = str(filename or "").strip()
            if not name or name in out:
                raise BridgeError(f"duplicate/missing semantic filename: {name!r}")
            out[name] = {
                "category": str(group.get("category") or ""),
                "semantic_scope": str(group.get("scope") or group.get("semantic_scope") or ""),
                "depicts": group.get("depicts") or [],
                "named_entities": group.get("entities") or group.get("named_entities") or [],
                "scene": group.get("scene") or [],
                "area": str(group.get("area") or defaults.get("area") or ""),
                "quality": str(group.get("quality") or defaults.get("quality") or "reserve"),
                "privacy_status": str(group.get("privacy") or defaults.get("privacy") or "review"),
                "semantic_confidence": float(
                    group.get("confidence")
                    if group.get("confidence") is not None
                    else defaults.get("confidence") or 0
                ),
                "review_status": str(group.get("review_status") or defaults.get("review_status") or ""),
                "rights_basis": str(group.get("rights_basis") or defaults.get("rights_basis") or ""),
            }
    return out


def build_view(snapshot: dict[str, Any], labels: dict[str, Any], source: dict[str, Any]) -> dict[str, Any]:
    if source.get("publication_authority") != "NONE":
        raise BridgeError("owned Photo Atlas source gained publication authority")
    if source.get("automatic_story_assignment_allowed") is not False:
        raise BridgeError("owned Photo Atlas source permits automatic story assignment")
    policy = source.get("policy") or {}
    for key in (
        "all_drive_assets_are_atlas_discoverable_candidates",
        "owned_candidate_is_not_approved_atlas_asset",
        "semantic_identity_is_not_story_subject_match",
        "subject_match_required_before_story_use",
        "rights_reconfirmation_required_before_story_use",
        "privacy_review_required_before_story_use",
        "editor_approval_required_before_story_use",
        "alt_text_required_before_story_use",
        "automatic_publication_forbidden",
        "no_photo_is_better_than_false_relevance",
    ):
        if policy.get(key) is not True:
            raise BridgeError(f"unsafe owned Photo Atlas source policy: {key}")

    if snapshot.get("publication_authority") != "NONE" or snapshot.get("candidate_only") is not True:
        raise BridgeError("Drive snapshot is not candidate-only")
    if labels.get("publication_authority") != "NONE":
        raise BridgeError("semantic labels gained publication authority")
    if labels.get("automatic_story_assignment_allowed") is not False:
        raise BridgeError("semantic labels permit story assignment")

    rows = snapshot.get("assets") or []
    if not isinstance(rows, list):
        raise BridgeError("snapshot assets must be an array")
    label_by_name = _label_rows(labels)
    snapshot_names = {str(row.get("filename") or "") for row in rows if isinstance(row, dict)}
    if snapshot_names != set(label_by_name):
        missing = sorted(snapshot_names - set(label_by_name))
        extra = sorted(set(label_by_name) - snapshot_names)
        raise BridgeError(f"owned Photo Atlas semantic coverage mismatch missing={missing} extra={extra}")

    seen_ids: set[str] = set()
    assets: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise BridgeError("invalid Drive snapshot asset")
        file_id = str(row.get("drive_file_id") or "").strip()
        filename = str(row.get("filename") or "").strip()
        if not file_id or file_id in seen_ids:
            raise BridgeError("Drive IDs must be present and unique")
        seen_ids.add(file_id)
        label = label_by_name[filename]
        status = label["review_status"]
        if status not in {"confirmed", "ambiguous", "reject"}:
            raise BridgeError(f"{filename}: invalid semantic review status")
        if label["rights_basis"] != "owned_by_valcea_clar":
            raise BridgeError(f"{filename}: unexpected rights basis")
        if status == "confirmed" and label["semantic_confidence"] < 0.85:
            raise BridgeError(f"{filename}: confirmed semantic confidence below 0.85")
        candidate_eligible = status == "confirmed"
        assets.append({
            "asset_id": asset_id(file_id),
            "kind": "photograph",
            "synthetic": False,
            "provider": "google_drive_owned",
            "drive_file_id": file_id,
            "filename": filename,
            "source_url": f"https://drive.google.com/file/d/{file_id}/view",
            "category": label["category"],
            "semantic_scope": label["semantic_scope"],
            "depicts": label["depicts"],
            "named_entities": label["named_entities"],
            "scene": label["scene"],
            "area": label["area"],
            "quality": label["quality"],
            "privacy_status": label["privacy_status"],
            "semantic_confidence": label["semantic_confidence"],
            "semantic_review_status": status,
            "atlas_candidate_eligible": candidate_eligible,
            "rights_basis": "owned_by_valcea_clar",
            "rights_reconfirmation_required": True,
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "automatic_story_assignment_allowed": False,
            "materialization_required_before_story_use": True,
            "original_binary_location": "google_drive",
        })

    assets.sort(key=lambda item: item["asset_id"])
    confirmed = sum(item["semantic_review_status"] == "confirmed" for item in assets)
    ambiguous = sum(item["semantic_review_status"] == "ambiguous" for item in assets)
    rejected = sum(item["semantic_review_status"] == "reject" for item in assets)
    bootstrap = source.get("bootstrap") or {}
    if len(assets) < int(bootstrap.get("asset_count") or 0):
        raise BridgeError("owned Photo Atlas asset count fell below migration bootstrap")
    if confirmed < int(bootstrap.get("confirmed_semantic_count") or 0):
        raise BridgeError("confirmed owned Photo Atlas count fell below migration bootstrap")

    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR PHOTO ATLAS OWNED CANDIDATE VIEW",
        "publication_authority": "NONE",
        "source_manifest": "valcea-clar/social/photo_atlas_owned_source.json",
        "original_binary_location": "google_drive",
        "summary": {
            "asset_count": len(assets),
            "confirmed_candidate_count": confirmed,
            "ambiguous_count": ambiguous,
            "rejected_count": rejected,
        },
        "assets": assets,
    }


def self_test() -> None:
    source = {
        "publication_authority": "NONE",
        "automatic_story_assignment_allowed": False,
        "bootstrap": {"asset_count": 1, "confirmed_semantic_count": 1},
        "policy": {key: True for key in (
            "all_drive_assets_are_atlas_discoverable_candidates",
            "owned_candidate_is_not_approved_atlas_asset",
            "semantic_identity_is_not_story_subject_match",
            "subject_match_required_before_story_use",
            "rights_reconfirmation_required_before_story_use",
            "privacy_review_required_before_story_use",
            "editor_approval_required_before_story_use",
            "alt_text_required_before_story_use",
            "automatic_publication_forbidden",
            "no_photo_is_better_than_false_relevance",
        )},
    }
    snapshot = {
        "publication_authority": "NONE", "candidate_only": True,
        "assets": [{"drive_file_id": "drive-1", "filename": "one.jpg"}],
    }
    labels = {
        "publication_authority": "NONE", "automatic_story_assignment_allowed": False,
        "defaults": {"review_status": "confirmed", "rights_basis": "owned_by_valcea_clar", "confidence": .96,
                     "quality": "strong", "privacy": "clear_contextual", "area": "Centru"},
        "groups": [{"files": ["one.jpg"], "category": "C", "scope": "exact_entity",
                    "depicts": ["ENTITY"], "entities": ["Entity"], "scene": ["building"]}],
    }
    view = build_view(snapshot, labels, source)
    assert view["summary"]["asset_count"] == 1
    item = view["assets"][0]
    assert item["subject_match"] is False
    assert item["editor_approved"] is False
    assert item["publication_eligible"] is False
    assert item["publication_authority"] == "NONE"
    assert item["atlas_candidate_eligible"] is True
    print({"status": "PASS", "asset_count": 1})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    view = build_view(load_json(SNAPSHOT), load_json(LABELS), load_json(SOURCE))
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        print({"status": "PASS", **view["summary"], "original_binary_location": "google_drive"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
