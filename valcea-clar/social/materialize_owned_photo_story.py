#!/usr/bin/env python3
"""Explicitly materialize an approved VÂLCEA CLAR-owned Drive photo to a story.

This script is deliberately NOT autonomous. It consumes explicit request rows
whose subject, rights, privacy, alt-text and editor gates are all confirmed.
It then downloads the selected Drive original, stores the JPEG under the
approved story-photo root and writes a normal story_visuals.json assignment.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from drive_owned_photo_ingest import bearer_token

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
REGISTRY = SOCIAL / "owned_photo_registry.json"
CANDIDATES = SOCIAL / "owned_photo_story_candidates.json"
REQUESTS = SOCIAL / "owned_photo_materialization_requests.json"
VISUALS = SOCIAL / "story_visuals.json"
ARCHIVE = ROOT / "valcea-clar" / "site" / "story_archive.json"
APPROVED_ROOT = (SOCIAL / "photos" / "approved").resolve()
RAW_BASE = "https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/"
DRIVE_MEDIA = "https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"


class MaterializeError(ValueError):
    pass


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise MaterializeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MaterializeError(f"expected object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def slug(value: object) -> str:
    text = str(value or "").casefold()
    text = text.translate(str.maketrans("ăâîșşțţ", "aaisstt"))
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:120]


def valid_jpeg(data: bytes) -> bool:
    return len(data) >= 50_000 and data.startswith(b"\xff\xd8\xff") and data.rstrip().endswith(b"\xff\xd9")


def validate_request_doc(doc: dict[str, Any]) -> None:
    if doc.get("publication_authority") != "EXPLICIT_EDITOR_REQUEST_ONLY":
        raise MaterializeError("materialization authority must be explicit-editor-request-only")
    if doc.get("automatic_materialization_allowed") is not False:
        raise MaterializeError("automatic materialization must remain disabled")
    if doc.get("automatic_story_assignment_allowed") is not False:
        raise MaterializeError("automatic story assignment must remain disabled")
    required = {
        "subject_match_confirmed",
        "editor_approved",
        "rights_reconfirmed",
        "privacy_reviewed",
        "alt_text_approved",
    }
    if not required.issubset(set(doc.get("required_gates") or [])):
        raise MaterializeError("request contract is missing mandatory gates")
    if not isinstance(doc.get("requests"), list):
        raise MaterializeError("requests must be an array")


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("publication_authority") != "NONE" or registry.get("candidate_only") is not True:
        raise MaterializeError("owned registry is not candidate-only")
    if registry.get("automatic_story_assignment_forbidden") is not True:
        raise MaterializeError("owned registry permits automatic story assignment")


def archive_ids(archive: dict[str, Any]) -> set[str]:
    rows = archive.get("stories") or []
    if not isinstance(rows, list):
        raise MaterializeError("story archive stories must be an array")
    return {str(row.get("id")) for row in rows if isinstance(row, dict) and row.get("id")}


def asset_index(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for asset in registry.get("assets") or []:
        if not isinstance(asset, dict) or not asset.get("asset_id"):
            continue
        aid = str(asset["asset_id"])
        if aid in out:
            raise MaterializeError(f"duplicate asset_id: {aid}")
        out[aid] = asset
    return out


def candidate_pairs(queue: dict[str, Any]) -> set[tuple[str, str]]:
    if queue.get("publication_authority") != "NONE" or queue.get("candidate_only") is not True:
        raise MaterializeError("owned candidate queue is not fail-closed")
    out: set[tuple[str, str]] = set()
    for sid, row in (queue.get("stories") or {}).items():
        if not isinstance(row, dict):
            continue
        for candidate in row.get("candidates") or []:
            if isinstance(candidate, dict) and candidate.get("asset_id"):
                out.add((str(sid), str(candidate["asset_id"])))
    return out


def active_requests(doc: dict[str, Any]) -> list[dict[str, Any]]:
    validate_request_doc(doc)
    return [row for row in doc["requests"] if isinstance(row, dict) and row.get("status") == "approved_for_materialization"]


def validate_request(
    row: dict[str, Any],
    *,
    stories: set[str],
    assets: dict[str, dict[str, Any]],
    pairs: set[tuple[str, str]],
    visuals: dict[str, Any],
) -> dict[str, Any]:
    request_id = str(row.get("request_id") or "").strip()
    story_id = str(row.get("story_id") or "").strip()
    asset_id = str(row.get("asset_id") or "").strip()
    if not request_id or not story_id or not asset_id:
        raise MaterializeError("active request requires request_id, story_id and asset_id")
    if story_id not in stories:
        raise MaterializeError(f"{request_id}: story is not in published archive: {story_id}")
    if asset_id not in assets:
        raise MaterializeError(f"{request_id}: unknown owned asset: {asset_id}")

    for gate in (
        "subject_match_confirmed",
        "editor_approved",
        "rights_reconfirmed",
        "privacy_reviewed",
        "alt_text_approved",
    ):
        if row.get(gate) is not True:
            raise MaterializeError(f"{request_id}: mandatory gate is not true: {gate}")

    alt_text = str(row.get("alt_text") or "").strip()
    if len(alt_text) < 15:
        raise MaterializeError(f"{request_id}: approved alt_text is too short")
    privacy_note = str(row.get("privacy_review_note") or "").strip()
    if not privacy_note:
        raise MaterializeError(f"{request_id}: privacy_review_note is required")

    contextual = row.get("contextual_archive") is True
    editorial_note = str(row.get("editorial_note") or "").strip()
    if contextual and not editorial_note:
        raise MaterializeError(f"{request_id}: contextual archive photo requires editorial_note")

    override = row.get("override_candidate_queue") is True
    if (story_id, asset_id) not in pairs:
        if not override or not str(row.get("override_reason") or "").strip():
            raise MaterializeError(
                f"{request_id}: asset/story pair is outside candidate queue; explicit override_reason required"
            )

    visual_rows = visuals.get("stories") or {}
    if not isinstance(visual_rows, dict):
        raise MaterializeError("story_visuals stories must be an object")
    existing = visual_rows.get(story_id)
    if existing is not None and row.get("replace_existing_visual") is not True:
        existing_asset = ((existing or {}).get("image") or {}).get("owned_asset_id") if isinstance(existing, dict) else None
        if existing_asset != asset_id:
            raise MaterializeError(f"{request_id}: story already has a visual; replacement was not explicitly approved")

    asset = assets[asset_id]
    if asset.get("kind") != "photograph" or asset.get("synthetic") is not False:
        raise MaterializeError(f"{request_id}: selected asset is not a verified real-photo candidate")
    if asset.get("rights_reconfirmation_required") is not True:
        raise MaterializeError(f"{request_id}: registry rights gate unexpectedly changed")

    return {
        "request_id": request_id,
        "story_id": story_id,
        "asset_id": asset_id,
        "asset": asset,
        "alt_text": alt_text,
        "privacy_review_note": privacy_note,
        "editorial_note": editorial_note,
        "contextual_archive": contextual,
        "replace_existing_visual": row.get("replace_existing_visual") is True,
        "override_candidate_queue": override,
        "override_reason": str(row.get("override_reason") or "").strip(),
        "credit": str(row.get("credit") or "Foto: VÂLCEA Clar").strip(),
        "captured_at": str(row.get("captured_at") or asset.get("captured_at_hint") or "").strip(),
    }


def build_plan(
    request_doc: dict[str, Any],
    registry: dict[str, Any],
    queue: dict[str, Any],
    archive: dict[str, Any],
    visuals: dict[str, Any],
) -> list[dict[str, Any]]:
    validate_registry(registry)
    stories = archive_ids(archive)
    assets = asset_index(registry)
    pairs = candidate_pairs(queue)
    seen_requests: set[str] = set()
    seen_stories: set[str] = set()
    plan: list[dict[str, Any]] = []
    for row in active_requests(request_doc):
        item = validate_request(row, stories=stories, assets=assets, pairs=pairs, visuals=visuals)
        if item["request_id"] in seen_requests:
            raise MaterializeError(f"duplicate request_id: {item['request_id']}")
        if item["story_id"] in seen_stories:
            raise MaterializeError(f"multiple active materializations for one story: {item['story_id']}")
        seen_requests.add(item["request_id"])
        seen_stories.add(item["story_id"])
        plan.append(item)
    return plan


def download_drive_jpeg(file_id: str, token: str) -> bytes:
    url = DRIVE_MEDIA.format(file_id=file_id)
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "image/jpeg,image/*"})
    with urllib.request.urlopen(request, timeout=90) as response:
        data = response.read(25_000_000)
    if not valid_jpeg(data):
        raise MaterializeError(f"Drive asset is not a valid >=50KB JPEG: {file_id} ({len(data)} bytes)")
    return data


def output_path(story_id: str, asset_id: str) -> Path:
    suffix = slug(asset_id.replace("owned-drive-", ""))[:20]
    filename = f"owned-{slug(story_id)}-{suffix}.jpg"
    target = (APPROVED_ROOT / filename).resolve()
    if target.parent != APPROVED_ROOT:
        raise MaterializeError("unsafe approved output path")
    return target


def materialize(plan: list[dict[str, Any]], request_doc: dict[str, Any], visuals: dict[str, Any], token: str) -> dict[str, Any]:
    story_rows = visuals.setdefault("stories", {})
    if not isinstance(story_rows, dict):
        raise MaterializeError("story_visuals stories must be an object")
    APPROVED_ROOT.mkdir(parents=True, exist_ok=True)
    now = utc_now()
    request_rows = request_doc.get("requests") or []
    request_by_id = {str(row.get("request_id")): row for row in request_rows if isinstance(row, dict) and row.get("request_id")}

    for item in plan:
        asset = item["asset"]
        data = download_drive_jpeg(str(asset["drive_file_id"]), token)
        target = output_path(item["story_id"], item["asset_id"])
        target.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        relative = target.relative_to(ROOT).as_posix()
        raw_url = RAW_BASE + relative
        image: dict[str, Any] = {
            "kind": "photograph",
            "synthetic": False,
            "subject_match": True,
            "editor_approved": True,
            "source_type": "owned",
            "source_url": str(asset["source_url"]),
            "direct_source_url": raw_url,
            "credit": item["credit"],
            "rights_basis": "owned",
            "rights_note": "Fotografie proprie VÂLCEA CLAR; drepturile de publicare au fost reconfirmate explicit înainte de materializare.",
            "alt_text": item["alt_text"],
            "owned_asset_id": item["asset_id"],
            "drive_file_id": str(asset["drive_file_id"]),
            "owned_category": str(asset.get("category") or ""),
            "privacy_reviewed": True,
            "privacy_review_note": item["privacy_review_note"],
            "materialized_at": now,
            "sha256": digest,
        }
        if item["captured_at"]:
            image["captured_at"] = item["captured_at"]
        if item["contextual_archive"]:
            image["contextual_archive"] = True
            image["editorial_note"] = item["editorial_note"]
        elif item["editorial_note"]:
            image["editorial_note"] = item["editorial_note"]

        story_rows[item["story_id"]] = {"image_path": relative, "image": image}
        request_row = request_by_id[item["request_id"]]
        request_row["status"] = "materialized"
        request_row["materialized_at"] = now
        request_row["materialized_path"] = relative
        request_row["materialized_sha256"] = digest

    return {"visuals": visuals, "requests": request_doc}


def self_test() -> None:
    registry = {
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_story_assignment_forbidden": True,
        "assets": [{
            "asset_id": "owned-drive-abc", "kind": "photograph", "synthetic": False,
            "drive_file_id": "drive-a", "filename": "a.jpg", "category": "ADMIN",
            "source_url": "https://drive.google.com/file/d/drive-a/view",
            "rights_reconfirmation_required": True, "captured_at_hint": "2026-08-19T06:00:00",
        }],
    }
    queue = {
        "publication_authority": "NONE", "candidate_only": True,
        "stories": {"story-a": {"candidates": [{"asset_id": "owned-drive-abc"}]}},
    }
    request_doc = {
        "publication_authority": "EXPLICIT_EDITOR_REQUEST_ONLY",
        "automatic_materialization_allowed": False,
        "automatic_story_assignment_allowed": False,
        "required_gates": ["subject_match_confirmed", "editor_approved", "rights_reconfirmed", "privacy_reviewed", "alt_text_approved"],
        "requests": [{
            "request_id": "r1", "status": "approved_for_materialization",
            "story_id": "story-a", "asset_id": "owned-drive-abc",
            "subject_match_confirmed": True, "editor_approved": True,
            "rights_reconfirmed": True, "privacy_reviewed": True, "alt_text_approved": True,
            "alt_text": "Fațada unei instituții publice din Râmnicu Vâlcea.",
            "privacy_review_note": "Cadru exterior; persoanele nu sunt subiectul imaginii.",
            "replace_existing_visual": False,
        }],
    }
    archive = {"stories": [{"id": "story-a"}]}
    plan = build_plan(request_doc, registry, queue, archive, {"stories": {}})
    assert len(plan) == 1 and plan[0]["story_id"] == "story-a"

    broken = json.loads(json.dumps(request_doc))
    broken["requests"][0]["subject_match_confirmed"] = False
    try:
        build_plan(broken, registry, queue, archive, {"stories": {}})
    except MaterializeError:
        pass
    else:
        raise AssertionError("unconfirmed subject match must fail closed")
    print({"status": "PASS", "planned": 1})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    request_doc = load_json(REQUESTS)
    registry = load_json(REGISTRY)
    queue = load_json(CANDIDATES)
    archive = load_json(ARCHIVE)
    visuals = load_json(VISUALS, {"schema_version": "1.2", "policy": {}, "stories": {}})
    plan = build_plan(request_doc, registry, queue, archive, visuals)

    if args.validate_only or not args.apply:
        print(json.dumps({
            "status": "PASS",
            "active_request_count": len(plan),
            "requests": [
                {"request_id": item["request_id"], "story_id": item["story_id"], "asset_id": item["asset_id"]}
                for item in plan
            ],
        }, ensure_ascii=False))
        return 0

    if not plan:
        print(json.dumps({"status": "NO_APPROVED_REQUESTS", "active_request_count": 0}))
        return 0

    # Authentication is intentionally resolved only after all explicit gates pass.
    config = load_json(SOCIAL / "owned_photo_drive_config.json")
    token = bearer_token(config)
    result = materialize(plan, request_doc, visuals, token)
    dump_json(VISUALS, result["visuals"])
    dump_json(REQUESTS, result["requests"])
    print(json.dumps({"status": "MATERIALIZED", "count": len(plan)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
