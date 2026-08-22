#!/usr/bin/env python3
"""Discover VÂLCEA CLAR-owned/curated real-photo candidates from Google Drive.

This is a candidate inventory only. It never assigns an image to a story and
never grants publication authority. Original binaries stay in Drive until a
separate explicit story-materialization decision.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
CONFIG = SOCIAL / "owned_photo_drive_config.json"
SNAPSHOT = SOCIAL / "owned_photo_drive_snapshot.json"
OUTPUT = SOCIAL / "owned_photo_registry.json"
DRIVE_API = "https://www.googleapis.com/drive/v3/files"


class IngestError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise IngestError(f"expected object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def asset_id(file_id: str) -> str:
    return "owned-drive-" + hashlib.sha256(file_id.encode("utf-8")).hexdigest()[:20]


def filename_timestamp_hint(name: str) -> str:
    match = re.search(r"PXL_(\d{8})_(\d{6})", name or "")
    if not match:
        return ""
    date, clock = match.groups()
    return f"{date[:4]}-{date[4:6]}-{date[6:]}T{clock[:2]}:{clock[2:4]}:{clock[4:]}"


def validate_config(config: dict[str, Any]) -> None:
    if config.get("publication_authority") != "NONE":
        raise IngestError("owned-photo ingest must have publication_authority NONE")
    policy = config.get("policy") or {}
    for key in (
        "real_photographs_only",
        "synthetic_assets_forbidden",
        "generic_substitution_forbidden",
        "candidate_only",
        "subject_match_required_before_promotion",
        "editor_approval_required_before_promotion",
        "rights_reconfirmation_required_before_first_publication",
        "original_binary_stays_in_drive_until_explicit_story_materialization",
        "no_photo_is_better_than_false_relevance",
    ):
        if policy.get(key) is not True:
            raise IngestError(f"unsafe config: {key} must be true")
    if policy.get("automatic_story_assignment_allowed") is not False:
        raise IngestError("automatic story assignment must remain false")
    categories = config.get("categories") or []
    if not categories or len({row.get('folder_id') for row in categories}) != len(categories):
        raise IngestError("categories must contain unique Drive folder IDs")


def normalize_rows(rows: list[dict[str, Any]], config: dict[str, Any], *, generated_at: str) -> dict[str, Any]:
    validate_config(config)
    categories = {str(row["folder_id"]): str(row["id"]) for row in config["categories"]}
    accepted = set(config.get("accepted_mime_types") or [])
    source = config.get("source") or {}
    assets: list[dict[str, Any]] = []
    seen: set[str] = set()
    counts = {category: 0 for category in categories.values()}

    for row in rows:
        file_id = str(row.get("drive_file_id") or row.get("id") or "").strip()
        name = str(row.get("filename") or row.get("name") or "").strip()
        folder_id = str(row.get("category_folder_id") or row.get("folder_id") or "").strip()
        mime = str(row.get("mime_type") or row.get("mimeType") or "").strip()
        if not file_id or not name or folder_id not in categories:
            continue
        if file_id in seen:
            raise IngestError(f"duplicate Drive file id: {file_id}")
        seen.add(file_id)
        if mime not in accepted:
            continue
        category = categories[folder_id]
        counts[category] += 1
        meta = row.get("imageMediaMetadata") if isinstance(row.get("imageMediaMetadata"), dict) else {}
        captured = str(meta.get("time") or row.get("filename_timestamp_hint") or filename_timestamp_hint(name)).strip()
        web = str(row.get("drive_web_url") or row.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view").strip()
        assets.append({
            "asset_id": asset_id(file_id),
            "kind": "photograph",
            "synthetic": False,
            "provider": "google_drive",
            "drive_file_id": file_id,
            "filename": name,
            "category": category,
            "source_type": source.get("source_type", "owned_archive_candidate"),
            "source_url": web,
            "creator_or_owner": source.get("creator_or_owner", "VÂLCEA CLAR"),
            "rights_basis": source.get("rights_basis", "owned_pending_story_assignment"),
            "rights_reconfirmation_required": True,
            "captured_at_hint": captured,
            "mime_type": mime,
            "size": str(row.get("size") or ""),
            "md5_checksum": str(row.get("md5Checksum") or row.get("md5_checksum") or ""),
            "width": meta.get("width"),
            "height": meta.get("height"),
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "original_binary_location": "google_drive",
            "blockers": ["rights_reconfirmation_required", "subject_match_not_verified", "editor_approval_required"],
        })

    assets.sort(key=lambda item: (item["category"], item["filename"], item["drive_file_id"]))
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR OWNED PHOTO REGISTRY",
        "generated_at_utc": generated_at,
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_story_assignment_forbidden": True,
        "source_of_truth_for_approved_story_visuals": "valcea-clar/social/story_visuals.json",
        "summary": {"asset_count": len(assets), "category_counts": counts},
        "assets": assets,
    }


def bearer_token(config: dict[str, Any]) -> str:
    credentials = config.get("credentials") or {}
    token = os.getenv(str(credentials.get("bearer_token_env") or "VALCEA_DRIVE_BEARER_TOKEN"), "").strip()
    if token:
        return token
    raw = os.getenv(str(credentials.get("service_account_json_env") or "VALCEA_DRIVE_SERVICE_ACCOUNT_JSON"), "").strip()
    if not raw:
        raise IngestError("Google Drive credential is not configured")
    try:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
    except ImportError as exc:
        raise IngestError("google-auth is required for service-account authentication") from exc
    info = json.loads(raw)
    creds = service_account.Credentials.from_service_account_info(
        info, scopes=[str(credentials.get("scope") or "https://www.googleapis.com/auth/drive.readonly")]
    )
    creds.refresh(Request())
    if not creds.token:
        raise IngestError("service-account token refresh returned no token")
    return str(creds.token)


def http_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        value = json.loads(response.read(8_000_000).decode("utf-8"))
    if not isinstance(value, dict):
        raise IngestError("Google Drive returned non-object JSON")
    return value


def list_folder(folder_id: str, token: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "pageSize": "1000",
            "fields": "nextPageToken,files(id,name,mimeType,size,modifiedTime,md5Checksum,webViewLink,imageMediaMetadata)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if page_token:
            params["pageToken"] = page_token
        payload = http_json(DRIVE_API + "?" + urllib.parse.urlencode(params), token)
        values = payload.get("files") or []
        if not isinstance(values, list):
            raise IngestError("Google Drive files payload is not an array")
        for row in values:
            if isinstance(row, dict):
                item = dict(row)
                item["folder_id"] = folder_id
                rows.append(item)
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            return rows


def live_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    token = bearer_token(config)
    rows: list[dict[str, Any]] = []
    for category in config["categories"]:
        rows.extend(list_folder(str(category["folder_id"]), token))
    return rows


def snapshot_from_live_rows(rows: list[dict[str, Any]], config: dict[str, Any], *, snapshot_at: str) -> dict[str, Any]:
    categories = {str(row["folder_id"]): str(row["id"]) for row in config["categories"]}
    assets: list[dict[str, Any]] = []
    counts = {category: 0 for category in categories.values()}
    for row in rows:
        folder_id = str(row.get("folder_id") or "")
        file_id = str(row.get("id") or "")
        name = str(row.get("name") or "")
        mime = str(row.get("mimeType") or "")
        if folder_id not in categories or not file_id or not name or mime not in set(config.get("accepted_mime_types") or []):
            continue
        category = categories[folder_id]
        counts[category] += 1
        meta = row.get("imageMediaMetadata") if isinstance(row.get("imageMediaMetadata"), dict) else {}
        assets.append({
            "drive_file_id": file_id,
            "filename": name,
            "category": category,
            "category_folder_id": folder_id,
            "mime_type": mime,
            "size": str(row.get("size") or ""),
            "md5_checksum": str(row.get("md5Checksum") or ""),
            "drive_web_url": str(row.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"),
            "filename_timestamp_hint": str(meta.get("time") or filename_timestamp_hint(name)),
        })
    assets.sort(key=lambda item: (item["category"], item["filename"], item["drive_file_id"]))
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR OWNED PHOTO DRIVE SNAPSHOT",
        "snapshot_source": "google_drive_api",
        "snapshot_at": snapshot_at,
        "publication_authority": "NONE",
        "candidate_only": True,
        "summary": {"asset_count": len(assets), "category_count": len(counts), "category_counts": counts},
        "assets": assets,
    }


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("publication_authority") != "NONE" or registry.get("candidate_only") is not True:
        raise IngestError("registry authority contract failed")
    if registry.get("automatic_story_assignment_forbidden") is not True:
        raise IngestError("registry must forbid automatic story assignment")
    ids: set[str] = set()
    for asset in registry.get("assets") or []:
        if asset.get("kind") != "photograph" or asset.get("synthetic") is not False:
            raise IngestError("non-real-photo asset entered owned registry")
        if asset.get("publication_eligible") is not False or asset.get("publication_authority") != "NONE":
            raise IngestError("candidate unexpectedly gained publication authority")
        if asset.get("subject_match") is not False or asset.get("editor_approved") is not False:
            raise IngestError("candidate unexpectedly gained editorial approval")
        if asset["asset_id"] in ids:
            raise IngestError("duplicate asset_id")
        ids.add(asset["asset_id"])


def self_test() -> None:
    config = {
        "publication_authority": "NONE",
        "policy": {
            "real_photographs_only": True,
            "synthetic_assets_forbidden": True,
            "generic_substitution_forbidden": True,
            "candidate_only": True,
            "automatic_story_assignment_allowed": False,
            "subject_match_required_before_promotion": True,
            "editor_approval_required_before_promotion": True,
            "rights_reconfirmation_required_before_first_publication": True,
            "original_binary_stays_in_drive_until_explicit_story_materialization": True,
            "no_photo_is_better_than_false_relevance": True,
        },
        "accepted_mime_types": ["image/jpeg"],
        "source": {},
        "categories": [{"id": "01_TEST", "folder_id": "folder"}],
    }
    rows = [{"drive_file_id": "abc", "filename": "PXL_20260819_063347994.jpg", "category_folder_id": "folder", "mime_type": "image/jpeg"}]
    registry = normalize_rows(rows, config, generated_at="2026-08-22T00:00:00Z")
    validate_registry(registry)
    assert registry["summary"]["asset_count"] == 1
    assert registry["assets"][0]["captured_at_hint"] == "2026-08-19T06:33:47"
    assert registry["assets"][0]["blockers"] == ["rights_reconfirmation_required", "subject_match_not_verified", "editor_approval_required"]
    print({"status": "PASS", "asset_count": 1})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--from-snapshot", action="store_true", help="rebuild registry from committed Drive metadata snapshot")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    config = load_json(CONFIG)
    validate_config(config)
    if args.validate_only:
        validate_registry(load_json(OUTPUT))
        print({"status": "PASS", "registry": str(OUTPUT)})
        return 0
    if args.from_snapshot:
        snapshot = load_json(SNAPSHOT)
        rows = snapshot.get("assets") or []
        if not isinstance(rows, list):
            raise IngestError("snapshot assets must be an array")
        generated_at = str(snapshot.get("snapshot_at") or "snapshot")
    else:
        rows = live_rows(config)
        now = utc_now()
        live_snapshot = snapshot_from_live_rows(rows, config, snapshot_at=now)
        if SNAPSHOT.exists():
            previous = load_json(SNAPSHOT)
            if previous.get("assets") == live_snapshot.get("assets"):
                live_snapshot["snapshot_at"] = previous.get("snapshot_at") or now
        generated_at = str(live_snapshot.get("snapshot_at") or now)
        dump_json(SNAPSHOT, live_snapshot)
    registry = normalize_rows(rows, config, generated_at=generated_at)
    validate_registry(registry)
    dump_json(OUTPUT, registry)
    print({"status": "PASS", "mode": "snapshot" if args.from_snapshot else "live", "summary": registry["summary"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
