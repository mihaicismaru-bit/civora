#!/usr/bin/env python3
"""Resolve VÂLCEA CLAR owned-photo semantic labels against the Drive snapshot.

This layer describes what an owned photograph depicts. It never decides that
the image depicts the event in a news story and never grants publication
authority. Exact semantic identity and story-level subject match are separate
gates by design.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
SNAPSHOT = SOCIAL / "owned_photo_drive_snapshot.json"
LABELS = SOCIAL / "owned_photo_semantic_labels.json"
REGISTRY = SOCIAL / "owned_photo_semantic_registry.json"
AMBIGUOUS = SOCIAL / "owned_photo_ambiguous_review_queue.json"

ALLOWED_STATUS = {"confirmed", "ambiguous", "reject"}
ALLOWED_SCOPE = {"exact_entity", "exact_place", "exact_scene", "ambiguous_entity"}
ALLOWED_QUALITY = {"hero", "strong", "context", "reserve", "reject"}
ALLOWED_PRIVACY = {"clear_contextual", "review_people_visible", "review_people_or_plates", "review"}
EVIDENCE_ALIASES = {
    "visual": "visual_review",
    "exif": "raw_jpeg_exif",
    "sign": "visible_signage",
    "facade": "distinctive_facade",
    "cross_frame": "cross_frame_landmark_confirmation",
    "address_web": "public_address_crosscheck",
    "secure_context": "secured_compound_context",
    "business_web": "public_business_crosscheck",
    "project_banner": "visible_project_banner",
    "project_web": "public_project_crosscheck",
    "parking_sign": "parking_signage",
}


class SemanticError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SemanticError(f"expected object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_top_level(labels: dict[str, Any]) -> None:
    if labels.get("publication_authority") != "NONE":
        raise SemanticError("semantic labels must have publication_authority NONE")
    if labels.get("automatic_story_assignment_allowed") is not False:
        raise SemanticError("semantic labels may not assign stories")
    if labels.get("semantic_label_is_not_story_assignment") is not True:
        raise SemanticError("semantic identity must be separated from story assignment")
    policy = labels.get("policy") or {}
    for key in (
        "every_snapshot_asset_requires_one_label",
        "confirmed_label_does_not_imply_story_subject_match",
        "raw_jpeg_exif_may_support_place_identity_but_not_event_identity",
        "owned_rights_basis_does_not_bypass_privacy_or_story_review",
    ):
        if policy.get(key) is not True:
            raise SemanticError(f"unsafe semantic policy: {key}")


def expanded_label(row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    status = str(row.get("review_status") or defaults.get("review_status") or "")
    scope = str(row.get("scope") or row.get("semantic_scope") or "")
    return {
        "filename": str(row.get("filename") or "").strip(),
        "category": str(row.get("category") or "").strip(),
        "semantic_scope": scope,
        "depicts": row.get("depicts") or [],
        "named_entities": row.get("entities") or row.get("named_entities") or [],
        "location": {
            "locality": str(row.get("locality") or defaults.get("locality") or ""),
            "county": str(row.get("county") or defaults.get("county") or ""),
            "area": str(row.get("area") or defaults.get("area") or ""),
        },
        "scene": row.get("scene") or [],
        "editorial_use": row.get("editorial_use") or defaults.get("editorial_use") or [],
        "not_for": row.get("not_for") or defaults.get("not_for") or [],
        "privacy": {"status": str(row.get("privacy") or defaults.get("privacy") or "review")},
        "quality": str(row.get("quality") or defaults.get("quality") or "reserve"),
        "rights_basis": str(row.get("rights_basis") or defaults.get("rights_basis") or ""),
        "semantic_confidence": float(
            row.get("confidence")
            if row.get("confidence") is not None
            else (
                row.get("semantic_confidence")
                if row.get("semantic_confidence") is not None
                else defaults.get("confidence") or 0
            )
        ),
        "review_status": status,
        "evidence": [
            EVIDENCE_ALIASES.get(str(item), str(item))
            for item in (row.get("evidence") or defaults.get("evidence") or [])
        ],
        "notes": str(row.get("notes") or ""),
    }


def validate_label(row: dict[str, Any]) -> None:
    filename = row["filename"]
    if not filename or not row["category"]:
        raise SemanticError("semantic label missing filename/category")
    if row["review_status"] not in ALLOWED_STATUS:
        raise SemanticError(f"{filename}: invalid review_status")
    if row["semantic_scope"] not in ALLOWED_SCOPE:
        raise SemanticError(f"{filename}: invalid semantic_scope")
    if row["rights_basis"] != "owned_by_valcea_clar":
        raise SemanticError(f"{filename}: unexpected rights basis")
    if row["quality"] not in ALLOWED_QUALITY:
        raise SemanticError(f"{filename}: invalid quality")
    if row["privacy"]["status"] not in ALLOWED_PRIVACY:
        raise SemanticError(f"{filename}: invalid privacy status")
    if not isinstance(row["depicts"], list) or not row["depicts"]:
        raise SemanticError(f"{filename}: depicts must be non-empty")
    if not isinstance(row["scene"], list) or not row["scene"]:
        raise SemanticError(f"{filename}: scene must be non-empty")
    conf = float(row["semantic_confidence"])
    if not 0 <= conf <= 1:
        raise SemanticError(f"{filename}: invalid semantic_confidence")
    if row["review_status"] == "confirmed" and conf < 0.85:
        raise SemanticError(f"{filename}: confirmed confidence below 0.85")
    if row["review_status"] == "ambiguous" and row["semantic_scope"] != "ambiguous_entity":
        raise SemanticError(f"{filename}: ambiguous row must use ambiguous_entity")
    ev = set(row["evidence"])
    if "visual_review" not in ev or "raw_jpeg_exif" not in ev:
        raise SemanticError(f"{filename}: visual + raw EXIF review evidence required")


def build(snapshot: dict[str, Any], labels: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_top_level(labels)
    snapshot_rows = snapshot.get("assets") or []
    raw_labels = labels.get("groups") or labels.get("labels") or []
    defaults = labels.get("defaults") or {}
    if not isinstance(snapshot_rows, list) or not isinstance(raw_labels, list):
        raise SemanticError("snapshot assets / labels must be arrays")

    snap_by_name: dict[str, dict[str, Any]] = {}
    ids: set[str] = set()
    for row in snapshot_rows:
        if not isinstance(row, dict):
            raise SemanticError("invalid Drive snapshot row")
        name = str(row.get("filename") or "").strip()
        file_id = str(row.get("drive_file_id") or "").strip()
        if not name or not file_id:
            raise SemanticError("Drive snapshot row missing filename/file id")
        if name in snap_by_name or file_id in ids:
            raise SemanticError("Drive snapshot filename/file id must be unique")
        snap_by_name[name] = row
        ids.add(file_id)

    labels_by_name: dict[str, dict[str, Any]] = {}
    for raw in raw_labels:
        if not isinstance(raw, dict):
            raise SemanticError("invalid semantic label row")
        files = raw.get("files") if isinstance(raw.get("files"), list) else [raw.get("filename")]
        if not files or any(not str(name or "").strip() for name in files):
            raise SemanticError("semantic group missing files")
        for name in files:
            expanded_raw = dict(raw)
            expanded_raw["filename"] = str(name)
            row = expanded_label(expanded_raw, defaults)
            validate_label(row)
            if row["filename"] in labels_by_name:
                raise SemanticError(f"duplicate semantic label: {row['filename']}")
            labels_by_name[row["filename"]] = row

    missing = sorted(set(snap_by_name) - set(labels_by_name))
    extra = sorted(set(labels_by_name) - set(snap_by_name))
    if missing or extra:
        raise SemanticError(f"semantic coverage mismatch missing={missing} extra={extra}")

    resolved: list[dict[str, Any]] = []
    for filename in sorted(snap_by_name):
        snap = snap_by_name[filename]
        label = labels_by_name[filename]
        snap_category = str(snap.get("category") or "")
        if snap_category and snap_category != label["category"]:
            raise SemanticError(f"{filename}: category drift")
        resolved.append({
            "drive_file_id": str(snap["drive_file_id"]),
            "filename": filename,
            "category": label["category"],
            "source_url": str(
                snap.get("drive_web_url")
                or f"https://drive.google.com/file/d/{snap['drive_file_id']}/view"
            ),
            "captured_at_hint": str(snap.get("filename_timestamp_hint") or ""),
            **label,
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "automatic_story_assignment": False,
        })

    confirmed = sum(row["review_status"] == "confirmed" for row in resolved)
    ambiguous_rows = [row for row in resolved if row["review_status"] == "ambiguous"]
    rejected = sum(row["review_status"] == "reject" for row in resolved)
    registry = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR OWNED PHOTO SEMANTIC REGISTRY",
        "publication_authority": "NONE",
        "automatic_story_assignment_allowed": False,
        "semantic_label_is_not_story_assignment": True,
        "story_subject_match_inherited_from_semantics": False,
        "source_snapshot": "valcea-clar/social/owned_photo_drive_snapshot.json",
        "source_labels": "valcea-clar/social/owned_photo_semantic_labels.json",
        "summary": {
            "asset_count": len(resolved),
            "confirmed": confirmed,
            "ambiguous": len(ambiguous_rows),
            "rejected": rejected,
            "exact_entity": sum(row["semantic_scope"] == "exact_entity" for row in resolved),
            "exact_place_or_scene": sum(
                row["semantic_scope"] in {"exact_place", "exact_scene"} for row in resolved
            ),
        },
        "assets": resolved,
    }
    queue = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR OWNED PHOTO AMBIGUOUS REVIEW QUEUE",
        "publication_authority": "NONE",
        "automatic_story_assignment_allowed": False,
        "summary": {"ambiguous_count": len(ambiguous_rows)},
        "items": [{
            "drive_file_id": row["drive_file_id"],
            "filename": row["filename"],
            "category": row["category"],
            "depicts": row["depicts"],
            "named_entities": row["named_entities"],
            "semantic_confidence": row["semantic_confidence"],
            "notes": row["notes"],
            "next_gate": "manual_identity_resolution",
        } for row in ambiguous_rows],
    }
    return registry, queue


def validate_output(registry: dict[str, Any], queue: dict[str, Any]) -> None:
    if registry.get("publication_authority") != "NONE":
        raise SemanticError("semantic registry gained publication authority")
    if registry.get("automatic_story_assignment_allowed") is not False:
        raise SemanticError("semantic registry permits story assignment")
    seen: set[str] = set()
    for row in registry.get("assets") or []:
        file_id = str(row.get("drive_file_id") or "")
        if not file_id or file_id in seen:
            raise SemanticError("duplicate/missing resolved drive_file_id")
        seen.add(file_id)
        if row.get("subject_match") is not False or row.get("editor_approved") is not False:
            raise SemanticError("semantic identity inherited story/editor approval")
        if row.get("publication_eligible") is not False or row.get("publication_authority") != "NONE":
            raise SemanticError("semantic asset gained publication eligibility")
    if int((queue.get("summary") or {}).get("ambiguous_count") or 0) != int(
        (registry.get("summary") or {}).get("ambiguous") or 0
    ):
        raise SemanticError("ambiguous queue drift")


def self_test() -> None:
    snapshot = {"assets": [
        {"drive_file_id": "a", "filename": "a.jpg", "category": "C"},
        {"drive_file_id": "b", "filename": "b.jpg", "category": "C"},
    ]}
    labels = {
        "publication_authority": "NONE",
        "automatic_story_assignment_allowed": False,
        "semantic_label_is_not_story_assignment": True,
        "defaults": {
            "locality": "X", "county": "Y", "area": "Z",
            "rights_basis": "owned_by_valcea_clar", "review_status": "confirmed",
        },
        "policy": {
            "every_snapshot_asset_requires_one_label": True,
            "confirmed_label_does_not_imply_story_subject_match": True,
            "raw_jpeg_exif_may_support_place_identity_but_not_event_identity": True,
            "owned_rights_basis_does_not_bypass_privacy_or_story_review": True,
        },
        "labels": [
            {"filename": "a.jpg", "category": "C", "scope": "exact_place", "depicts": ["A"], "scene": ["street"],
             "entities": [], "privacy": "clear_contextual", "quality": "strong", "confidence": .95,
             "evidence": ["visual", "exif"]},
            {"filename": "b.jpg", "category": "C", "scope": "exact_entity", "depicts": ["B"], "scene": ["building"],
             "entities": ["B"], "privacy": "clear_contextual", "quality": "hero", "confidence": .95,
             "evidence": ["visual", "exif", "sign"]},
        ],
    }
    registry, queue = build(snapshot, labels)
    validate_output(registry, queue)
    assert registry["summary"]["asset_count"] == 2
    assert registry["summary"]["confirmed"] == 2
    assert queue["summary"]["ambiguous_count"] == 0
    assert all(row["subject_match"] is False for row in registry["assets"])
    broken = json.loads(json.dumps(labels))
    broken["labels"].pop()
    try:
        build(snapshot, broken)
    except SemanticError:
        pass
    else:
        raise AssertionError("missing semantic label must fail closed")
    print({"status": "PASS", "asset_count": 2, "ambiguous": 0})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    registry, queue = build(load_json(SNAPSHOT), load_json(LABELS))
    validate_output(registry, queue)
    if args.write:
        dump_json(REGISTRY, registry)
        dump_json(AMBIGUOUS, queue)
    print(json.dumps({
        "status": "PASS",
        "summary": registry["summary"],
        "ambiguous_queue": queue["summary"]["ambiguous_count"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
