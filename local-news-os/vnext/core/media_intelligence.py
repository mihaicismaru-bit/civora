#!/usr/bin/env python3
"""Site-owned Media Intelligence and Photo Atlas for LOCAL NEWS OS vNext.

The core stores media metadata, rights evidence, target bindings, derivatives and
story assignments in the runtime database. It never stores editorial runtime
state in Git and it contains no locality-specific media seeds.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from knowledge_graph import ensure_knowledge_schema, get_entity
from runtime_store import connect, create_story, initialize, register_instance, utc_now

ROOT = Path(__file__).resolve().parents[3]
MEDIA_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "media_schema.sql"

ASSET_KINDS = {"REAL_PHOTO", "DOCUMENT_VISUAL", "EDITORIAL_CARD"}
ORIGIN_KINDS = {
    "USER_OWNED", "OFFICIAL", "CREATIVE_COMMONS", "PUBLIC_DOMAIN", "LICENSED",
    "GENERATED_EDITORIAL_CARD",
}
STATUSES = {"CANDIDATE", "RIGHTS_VERIFIED", "BLOCKED"}
FRESHNESS = {"EVERGREEN", "SLOW_DECAY", "FAST_DECAY", "EVENT_ONLY"}
SPECIFICITY = {
    "EVENT_DIRECT", "SUBJECT_DIRECT", "PLACE_DIRECT", "CONTEXT_CURRENT",
    "CONTEXT_ARCHIVE", "DOCUMENT_VISUAL",
}
RESOLVER_CLASSES = [
    "EVENT_DIRECT", "SUBJECT_DIRECT", "PLACE_DIRECT", "CONTEXT_CURRENT",
    "CONTEXT_ARCHIVE", "DOCUMENT_VISUAL", "EDITORIAL_CARD", "NO_VISUAL",
]
USAGE_SCOPES = {"SITE", "SOCIAL"}
DERIVATIVE_PURPOSES = {"SITE_HERO", "OPEN_GRAPH", "FACEBOOK", "INSTAGRAM", "THUMBNAIL"}
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MediaIntelligenceError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaIntelligenceError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _id(prefix: str, *parts: str) -> str:
    return f"{prefix}_{hashlib.sha256(chr(10).join(parts).encode('utf-8')).hexdigest()[:24]}"


def ensure_media_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MEDIA_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def _json_list(value: Any, *, allowed: set[str], field: str) -> list[str]:
    _require(isinstance(value, list) and value, f"{field} must be a non-empty list")
    normalized = sorted({_clean(item).upper() for item in value})
    _require(all(item in allowed for item in normalized), f"unsupported {field}")
    return normalized


def _provenance(value: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for raw in value:
        _require(isinstance(raw, dict), "media provenance entries must be objects")
        item = {
            "source_ref": _clean(raw.get("source_ref")),
            "observed_at": _clean(raw.get("observed_at")),
            "evidence_fingerprint": _clean(raw.get("evidence_fingerprint")),
        }
        _require(all(item.values()), "media provenance requires source_ref, observed_at and evidence_fingerprint")
        _require(
            item["source_ref"].startswith(("http://", "https://", "site-owned://")),
            "media provenance source_ref must be HTTP(S) or site-owned",
        )
        _require(len(item["evidence_fingerprint"]) >= 16, "media evidence fingerprint is too short")
        if raw.get("note") is not None:
            item["note"] = _clean(raw.get("note"))
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        output[key] = item
    _require(bool(output), "media provenance is mandatory")
    return [output[key] for key in sorted(output)]


def validate_photo_pack(pack: dict[str, Any], *, instance_id: str) -> dict[str, Any]:
    _require(isinstance(pack, dict), "photo pack must be an object")
    _require(pack.get("schema_version") == "2.0", "photo pack schema mismatch")
    _require(pack.get("pack_type") == "photos", "not a photo pack")
    _require(pack.get("instance_id") == instance_id, "photo pack instance mismatch")
    resolver = pack.get("resolver")
    _require(isinstance(resolver, dict), "photo pack requires resolver policy")
    ladder = [_clean(item).upper() for item in resolver.get("specificity_ladder") or []]
    _require(ladder == RESOLVER_CLASSES, "specificity ladder must use the canonical deterministic order")
    origins = _json_list(resolver.get("allowed_origins"), allowed=ORIGIN_KINDS, field="allowed_origins")
    _require("GENERATED_EDITORIAL_CARD" in origins, "editorial-card origin must remain available")
    _require(resolver.get("synthetic_factual_photo_forbidden") is True, "synthetic factual-photo guard must be enabled")
    _require(resolver.get("missing_photo_blocks_story") is False, "missing photography must not block a valid story")
    fallback = _clean(resolver.get("fallback")).upper()
    _require(fallback in {"EDITORIAL_CARD", "NO_VISUAL"}, "unsupported media fallback")
    min_relevance = resolver.get("min_relevance_score", 0)
    _require(isinstance(min_relevance, int) and not isinstance(min_relevance, bool) and 0 <= min_relevance <= 100, "invalid min relevance")
    return {
        "specificity_ladder": ladder,
        "allowed_origins": origins,
        "fallback": fallback,
        "min_relevance_score": int(min_relevance),
        "synthetic_factual_photo_forbidden": True,
        "missing_photo_blocks_story": False,
    }


def load_photo_pack(instance_id: str) -> dict[str, Any]:
    instance_path = ROOT / "local-news-os" / "vnext" / "instances" / instance_id / "instance.json"
    _require(instance_path.is_file(), f"unknown instance: {instance_id}")
    cfg = json.loads(instance_path.read_text(encoding="utf-8"))
    rel = (cfg.get("packs") or {}).get("photos")
    _require(isinstance(rel, str) and rel, "instance has no photos pack")
    path = (ROOT / rel).resolve()
    _require(ROOT.resolve() in path.parents and path.is_file(), "photo pack is outside repository or missing")
    pack = json.loads(path.read_text(encoding="utf-8"))
    validate_photo_pack(pack, instance_id=instance_id)
    return pack


def _decode_asset(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["usage_scope"] = json.loads(result.pop("usage_scope_json"))
    result["provenance"] = json.loads(result.pop("provenance_json"))
    result["attributes"] = json.loads(result.pop("attributes_json"))
    result["synthetic"] = bool(result["synthetic"])
    result["depicts_real_scene"] = bool(result["depicts_real_scene"])
    return result


def get_media_asset(conn: sqlite3.Connection, *, instance_id: str, media_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM media_assets WHERE instance_id=? AND media_id=?", (instance_id, media_id)
    ).fetchone()
    if row is None:
        raise MediaIntelligenceError("media asset not found for instance")
    return _decode_asset(row)


def list_media_assets(conn: sqlite3.Connection, *, instance_id: str, limit: int = 200) -> list[dict[str, Any]]:
    bounded = max(1, min(1000, int(limit)))
    return [
        _decode_asset(row)
        for row in conn.execute(
            "SELECT * FROM media_assets WHERE instance_id=? ORDER BY updated_at DESC,media_id LIMIT ?",
            (instance_id, bounded),
        ).fetchall()
    ]


def register_media_asset(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    asset_kind: str,
    origin_kind: str,
    storage_ref: str,
    credit: str,
    rights_basis: str,
    license_code: str,
    rights_evidence_ref: str,
    rights_evidence_fingerprint: str,
    content_fingerprint: str,
    mime_type: str,
    freshness_class: str,
    usage_scope: list[str],
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    title: str = "",
    source_url: str | None = None,
    source_asset_url: str | None = None,
    perceptual_hash: str | None = None,
    width: int | None = None,
    height: int | None = None,
    captured_at: str | None = None,
    synthetic: bool = False,
    depicts_real_scene: bool = False,
    status: str = "RIGHTS_VERIFIED",
    attributes: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    kind = _clean(asset_kind).upper()
    origin = _clean(origin_kind).upper()
    state = _clean(status).upper()
    freshness = _clean(freshness_class).upper()
    scopes = _json_list(usage_scope, allowed=USAGE_SCOPES, field="usage_scope")
    sources = _provenance(provenance)
    _require(kind in ASSET_KINDS, "unsupported asset kind")
    _require(origin in ORIGIN_KINDS, "unsupported media origin")
    _require(state in STATUSES, "unsupported media status")
    _require(freshness in FRESHNESS, "unsupported freshness class")
    _require(bool(_clean(storage_ref)), "storage_ref is required")
    _require(bool(_clean(credit)), "credit is required")
    _require(bool(_clean(rights_basis)), "rights_basis is required")
    _require(bool(_clean(license_code)), "license_code is required")
    _require(bool(_clean(rights_evidence_ref)), "rights_evidence_ref is required")
    _require(len(_clean(rights_evidence_fingerprint)) >= 16, "rights evidence fingerprint is too short")
    content_hash = _clean(content_fingerprint).lower()
    _require(bool(HEX64.fullmatch(content_hash)), "content_fingerprint must be sha256 hex")
    _require(bool(_clean(mime_type)), "mime_type is required")
    if source_url:
        _require(_clean(source_url).startswith(("http://", "https://")), "source_url must be HTTP(S)")
    if source_asset_url:
        _require(_clean(source_asset_url).startswith(("http://", "https://")), "source_asset_url must be HTTP(S)")
    if state == "RIGHTS_VERIFIED":
        _require(origin in ORIGIN_KINDS, "rights-verified asset origin is not allowed")
    if kind == "REAL_PHOTO":
        _require(not synthetic and depicts_real_scene, "real photos must be non-synthetic and depict a real scene")
        _require(origin != "GENERATED_EDITORIAL_CARD", "generated editorial cards cannot be real photos")
    if kind == "EDITORIAL_CARD":
        _require(synthetic and not depicts_real_scene, "editorial cards must be synthetic non-scene visuals")
        _require(origin == "GENERATED_EDITORIAL_CARD", "editorial cards require generated-card origin")
    if synthetic:
        _require(kind == "EDITORIAL_CARD", "synthetic media cannot masquerade as factual photography")
    if origin == "USER_OWNED":
        _require(_clean(rights_basis).upper() == "OWNED", "user-owned media requires OWNED rights basis")
    if origin == "PUBLIC_DOMAIN":
        _require("PUBLIC" in _clean(license_code).upper(), "public-domain origin requires explicit public-domain license code")
    if origin in {"OFFICIAL", "CREATIVE_COMMONS", "PUBLIC_DOMAIN", "LICENSED"}:
        _require(bool(_clean(source_url)), "external reusable media requires source_url")
    attrs = dict(attributes or {})
    media_id = _id("media", instance_id, content_hash)
    fingerprint = _hash({
        "asset_kind": kind,
        "origin_kind": origin,
        "storage_ref": _clean(storage_ref),
        "source_url": _clean(source_url),
        "source_asset_url": _clean(source_asset_url),
        "credit": _clean(credit),
        "rights_basis": _clean(rights_basis),
        "license_code": _clean(license_code),
        "rights_evidence_ref": _clean(rights_evidence_ref),
        "rights_evidence_fingerprint": _clean(rights_evidence_fingerprint),
        "content_fingerprint": content_hash,
        "perceptual_hash": _clean(perceptual_hash),
        "mime_type": _clean(mime_type),
        "width": width,
        "height": height,
        "captured_at": _clean(captured_at),
        "freshness_class": freshness,
        "synthetic": bool(synthetic),
        "depicts_real_scene": bool(depicts_real_scene),
        "status": state,
        "usage_scope": scopes,
        "provenance": sources,
        "attributes": attrs,
    })
    existing = conn.execute(
        "SELECT * FROM media_assets WHERE instance_id=? AND media_id=?", (instance_id, media_id)
    ).fetchone()
    now = utc_now()
    if existing is not None:
        current = _decode_asset(existing)
        changed = current["fingerprint"] != fingerprint
        if changed:
            conn.execute(
                """
                UPDATE media_assets SET title=?,storage_ref=?,source_url=?,source_asset_url=?,credit=?,rights_basis=?,
                    license_code=?,rights_evidence_ref=?,rights_evidence_fingerprint=?,perceptual_hash=?,mime_type=?,width=?,height=?,
                    captured_at=?,freshness_class=?,synthetic=?,depicts_real_scene=?,status=?,usage_scope_json=?,provenance_json=?,
                    attributes_json=?,fingerprint=?,updated_at=? WHERE instance_id=? AND media_id=?
                """,
                (
                    _clean(title), _clean(storage_ref), _clean(source_url) or None, _clean(source_asset_url) or None,
                    _clean(credit), _clean(rights_basis), _clean(license_code), _clean(rights_evidence_ref),
                    _clean(rights_evidence_fingerprint), _clean(perceptual_hash) or None, _clean(mime_type), width, height,
                    _clean(captured_at) or None, freshness, 1 if synthetic else 0, 1 if depicts_real_scene else 0, state,
                    json.dumps(scopes), json.dumps(sources, ensure_ascii=False, sort_keys=True),
                    json.dumps(attrs, ensure_ascii=False, sort_keys=True), fingerprint, now, instance_id, media_id,
                ),
            )
            _event(conn, instance_id, media_id, "MEDIA_ASSET_REGISTERED", "media metadata and rights evidence updated", {"status": state}, engine_version, now)
            conn.commit()
        return get_media_asset(conn, instance_id=instance_id, media_id=media_id), changed
    conn.execute(
        """
        INSERT INTO media_assets(
            instance_id,media_id,asset_kind,origin_kind,title,storage_ref,source_url,source_asset_url,credit,rights_basis,
            license_code,rights_evidence_ref,rights_evidence_fingerprint,content_fingerprint,perceptual_hash,mime_type,width,height,
            captured_at,freshness_class,synthetic,depicts_real_scene,status,usage_scope_json,provenance_json,attributes_json,
            fingerprint,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            instance_id, media_id, kind, origin, _clean(title), _clean(storage_ref), _clean(source_url) or None,
            _clean(source_asset_url) or None, _clean(credit), _clean(rights_basis), _clean(license_code), _clean(rights_evidence_ref),
            _clean(rights_evidence_fingerprint), content_hash, _clean(perceptual_hash) or None, _clean(mime_type), width, height,
            _clean(captured_at) or None, freshness, 1 if synthetic else 0, 1 if depicts_real_scene else 0, state,
            json.dumps(scopes), json.dumps(sources, ensure_ascii=False, sort_keys=True), json.dumps(attrs, ensure_ascii=False, sort_keys=True),
            fingerprint, now, now,
        ),
    )
    _event(conn, instance_id, media_id, "MEDIA_ASSET_REGISTERED", "media asset and rights evidence registered", {"asset_kind": kind, "status": state}, engine_version, now)
    conn.commit()
    return get_media_asset(conn, instance_id=instance_id, media_id=media_id), True


def _event(conn: sqlite3.Connection, instance_id: str, aggregate_id: str, event_type: str, reason: str, payload: dict[str, Any], engine_version: str, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
        VALUES (?,'media',?,?,?,?,?,?)
        """,
        (instance_id, aggregate_id, event_type, reason, json.dumps(payload, ensure_ascii=False, sort_keys=True), engine_version, created_at),
    )


def _validate_target(conn: sqlite3.Connection, *, instance_id: str, target_type: str, target_id: str) -> None:
    if target_type == "STORY":
        _require(conn.execute("SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (instance_id, target_id)).fetchone() is not None, "media story target not found")
        return
    ensure_knowledge_schema(conn)
    entity = get_entity(conn, instance_id=instance_id, entity_id=target_id)
    if target_type == "EVENT":
        _require(entity["entity_type"] == "EVENT", "EVENT media binding requires event entity")
    elif target_type == "PLACE":
        _require(entity["entity_type"] in {"PLACE", "VENUE"}, "PLACE media binding requires place or venue entity")


def bind_media(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    media_id: str,
    target_type: str,
    target_id: str,
    specificity_class: str,
    relevance_score: int,
    usage_scope: list[str],
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    context_disclosure: str = "",
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    asset = get_media_asset(conn, instance_id=instance_id, media_id=media_id)
    target = _clean(target_type).upper()
    specificity = _clean(specificity_class).upper()
    _require(target in {"STORY", "ENTITY", "EVENT", "PLACE"}, "unsupported media target type")
    _require(specificity in SPECIFICITY, "unsupported specificity class")
    _require(isinstance(relevance_score, int) and not isinstance(relevance_score, bool) and 0 <= relevance_score <= 100, "invalid relevance score")
    scopes = _json_list(usage_scope, allowed=USAGE_SCOPES, field="binding usage_scope")
    _require(set(scopes).issubset(set(asset["usage_scope"])), "binding usage exceeds asset rights scope")
    if specificity == "CONTEXT_ARCHIVE":
        _require(bool(_clean(context_disclosure)), "archive context requires explicit disclosure")
    _validate_target(conn, instance_id=instance_id, target_type=target, target_id=target_id)
    sources = _provenance(provenance)
    binding_id = _id("bind", instance_id, media_id, target, target_id, specificity)
    fingerprint = _hash({
        "media_id": media_id, "target_type": target, "target_id": target_id, "specificity": specificity,
        "relevance_score": relevance_score, "context_disclosure": _clean(context_disclosure), "usage_scope": scopes,
        "provenance": sources,
    })
    existing = conn.execute("SELECT * FROM media_bindings WHERE instance_id=? AND binding_id=?", (instance_id, binding_id)).fetchone()
    now = utc_now()
    if existing is not None:
        changed = existing["fingerprint"] != fingerprint
        if changed:
            conn.execute(
                """
                UPDATE media_bindings SET relevance_score=?,context_disclosure=?,usage_scope_json=?,provenance_json=?,fingerprint=?,updated_at=?
                WHERE instance_id=? AND binding_id=?
                """,
                (relevance_score, _clean(context_disclosure), json.dumps(scopes), json.dumps(sources, ensure_ascii=False, sort_keys=True), fingerprint, now, instance_id, binding_id),
            )
            conn.commit()
        row = conn.execute("SELECT * FROM media_bindings WHERE instance_id=? AND binding_id=?", (instance_id, binding_id)).fetchone()
        return _decode_binding(row), changed
    conn.execute(
        """
        INSERT INTO media_bindings(instance_id,binding_id,media_id,target_type,target_id,specificity_class,relevance_score,context_disclosure,usage_scope_json,provenance_json,fingerprint,created_at,updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (instance_id, binding_id, media_id, target, target_id, specificity, relevance_score, _clean(context_disclosure), json.dumps(scopes), json.dumps(sources, ensure_ascii=False, sort_keys=True), fingerprint, now, now),
    )
    _event(conn, instance_id, media_id, "MEDIA_BOUND", "media relevance binding recorded", {"binding_id": binding_id, "target_type": target, "target_id": target_id, "specificity": specificity}, engine_version, now)
    conn.commit()
    row = conn.execute("SELECT * FROM media_bindings WHERE instance_id=? AND binding_id=?", (instance_id, binding_id)).fetchone()
    return _decode_binding(row), True


def _decode_binding(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["usage_scope"] = json.loads(result.pop("usage_scope_json"))
    result["provenance"] = json.loads(result.pop("provenance_json"))
    return result


def register_derivative(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    media_id: str,
    purpose: str,
    storage_ref: str,
    content_fingerprint: str,
    width: int,
    height: int,
    crop: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    asset = get_media_asset(conn, instance_id=instance_id, media_id=media_id)
    _require(asset["status"] == "RIGHTS_VERIFIED", "derivatives require rights-verified media")
    use = _clean(purpose).upper()
    _require(use in DERIVATIVE_PURPOSES, "unsupported derivative purpose")
    content_hash = _clean(content_fingerprint).lower()
    _require(bool(HEX64.fullmatch(content_hash)), "derivative content fingerprint must be sha256 hex")
    _require(width > 0 and height > 0, "derivative dimensions must be positive")
    derivative_id = _id("deriv", instance_id, media_id, use, content_hash)
    existing = conn.execute("SELECT * FROM media_derivatives WHERE instance_id=? AND derivative_id=?", (instance_id, derivative_id)).fetchone()
    if existing is not None:
        return dict(existing), False
    now = utc_now()
    conn.execute(
        "INSERT INTO media_derivatives(instance_id,derivative_id,media_id,purpose,storage_ref,content_fingerprint,width,height,crop_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (instance_id, derivative_id, media_id, use, _clean(storage_ref), content_hash, width, height, json.dumps(crop or {}, ensure_ascii=False, sort_keys=True), now),
    )
    _event(conn, instance_id, media_id, "MEDIA_DERIVATIVE_REGISTERED", "media crop/derivative registered", {"derivative_id": derivative_id, "purpose": use}, engine_version, now)
    conn.commit()
    row = conn.execute("SELECT * FROM media_derivatives WHERE instance_id=? AND derivative_id=?", (instance_id, derivative_id)).fetchone()
    result = dict(row)
    result["crop"] = json.loads(result.pop("crop_json"))
    return result, True


def _targets_for_story(conn: sqlite3.Connection, *, instance_id: str, story_id: str) -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = [("STORY", story_id)]
    try:
        rows = conn.execute(
            "SELECT entity_id FROM story_entity_links WHERE instance_id=? AND story_id=? ORDER BY entity_id",
            (instance_id, story_id),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    for row in rows:
        targets.append(("ENTITY", str(row["entity_id"])))
    return targets


def resolve_story_media(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    photo_pack: dict[str, Any],
    usage_scope: str,
    engine_version: str,
) -> dict[str, Any]:
    ensure_media_schema(conn)
    scope = _clean(usage_scope).upper()
    _require(scope in USAGE_SCOPES, "unsupported resolver usage scope")
    _require(conn.execute("SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (instance_id, story_id)).fetchone() is not None, "story not found for media resolution")
    policy = validate_photo_pack(photo_pack, instance_id=instance_id)
    targets = _targets_for_story(conn, instance_id=instance_id, story_id=story_id)
    candidates: list[dict[str, Any]] = []
    for target_type, target_id in targets:
        rows = conn.execute(
            """
            SELECT b.*,a.asset_kind,a.origin_kind,a.storage_ref,a.source_url,a.source_asset_url,a.credit,
                   a.rights_basis,a.license_code,a.freshness_class,a.synthetic,a.depicts_real_scene,a.status,
                   a.usage_scope_json AS asset_usage_scope_json,a.content_fingerprint AS asset_content_fingerprint
            FROM media_bindings b JOIN media_assets a
              ON a.instance_id=b.instance_id AND a.media_id=b.media_id
            WHERE b.instance_id=? AND b.target_type=? AND b.target_id=? AND a.status='RIGHTS_VERIFIED'
            """,
            (instance_id, target_type, target_id),
        ).fetchall()
        for row in rows:
            value = dict(row)
            asset_scopes = set(json.loads(value.pop("asset_usage_scope_json")))
            binding_scopes = set(json.loads(value["usage_scope_json"]))
            if scope not in asset_scopes or scope not in binding_scopes:
                continue
            if value["origin_kind"] not in policy["allowed_origins"]:
                continue
            if int(value["relevance_score"]) < policy["min_relevance_score"]:
                continue
            if bool(value["synthetic"]) or value["asset_kind"] == "EDITORIAL_CARD":
                continue
            if value["asset_kind"] == "REAL_PHOTO" and not bool(value["depicts_real_scene"]):
                continue
            candidates.append(value)
    rank = {name: index for index, name in enumerate(policy["specificity_ladder"])}
    candidates.sort(
        key=lambda item: (
            rank[item["specificity_class"]],
            -int(item["relevance_score"]),
            str(item["media_id"]),
        )
    )
    if candidates:
        chosen = candidates[0]
        assignment_status = "MEDIA_READY"
        specificity = str(chosen["specificity_class"])
        media_id = str(chosen["media_id"])
        reason = "highest-ranked rights-verified relevant media"
        disclosure = _clean(chosen.get("context_disclosure"))
    else:
        fallback = policy["fallback"]
        media_id = None
        specificity = fallback
        assignment_status = "EDITORIAL_CARD_REQUIRED" if fallback == "EDITORIAL_CARD" else "NO_VISUAL"
        reason = "no rights-verified relevant media; non-blocking fallback applied"
        disclosure = ""
    fingerprint = _hash({
        "story_id": story_id,
        "usage_scope": scope,
        "targets": targets,
        "media_id": media_id,
        "assignment_status": assignment_status,
        "specificity": specificity,
        "reason": reason,
        "policy": policy,
    })
    now = utc_now()
    conn.execute(
        """
        INSERT INTO story_media_assignments(
            instance_id,story_id,usage_scope,media_id,derivative_id,assignment_status,specificity_class,
            context_disclosure,resolver_fingerprint,reason,created_at,updated_at
        ) VALUES (?,?,?,?,NULL,?,?,?,?,?,?,?)
        ON CONFLICT(instance_id,story_id,usage_scope) DO UPDATE SET
            media_id=excluded.media_id,derivative_id=NULL,assignment_status=excluded.assignment_status,
            specificity_class=excluded.specificity_class,context_disclosure=excluded.context_disclosure,
            resolver_fingerprint=excluded.resolver_fingerprint,reason=excluded.reason,updated_at=excluded.updated_at
        """,
        (instance_id, story_id, scope, media_id, assignment_status, specificity, disclosure, fingerprint, reason, now, now),
    )
    _event(conn, instance_id, story_id, "STORY_MEDIA_RESOLVED", "deterministic media resolver completed", {"usage_scope": scope, "media_id": media_id, "status": assignment_status, "specificity": specificity}, engine_version, now)
    conn.commit()
    row = conn.execute("SELECT * FROM story_media_assignments WHERE instance_id=? AND story_id=? AND usage_scope=?", (instance_id, story_id, scope)).fetchone()
    return dict(row)


def get_story_media_projection(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    usage_scope: str,
    require_public_story: bool = False,
) -> dict[str, Any] | None:
    ensure_media_schema(conn)
    scope = _clean(usage_scope).upper()
    if require_public_story:
        try:
            published = conn.execute("SELECT canonical_path,published_at FROM story_publications WHERE instance_id=? AND story_id=?", (instance_id, story_id)).fetchone()
        except sqlite3.OperationalError as exc:
            raise MediaIntelligenceError("publication schema required for public media projection") from exc
        if published is None:
            return None
    row = conn.execute(
        "SELECT * FROM story_media_assignments WHERE instance_id=? AND story_id=? AND usage_scope=?",
        (instance_id, story_id, scope),
    ).fetchone()
    if row is None:
        return None
    assignment = dict(row)
    result: dict[str, Any] = {"assignment": assignment, "asset": None, "derivative": None}
    if assignment["media_id"]:
        result["asset"] = get_media_asset(conn, instance_id=instance_id, media_id=assignment["media_id"])
    if assignment["derivative_id"]:
        derivative = conn.execute("SELECT * FROM media_derivatives WHERE instance_id=? AND derivative_id=?", (instance_id, assignment["derivative_id"])).fetchone()
        if derivative:
            result["derivative"] = dict(derivative)
    return result


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _pack(instance_id: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "photos",
        "instance_id": instance_id,
        "migration": {"status": "NONE"},
        "resolver": {
            "specificity_ladder": RESOLVER_CLASSES,
            "allowed_origins": sorted(ORIGIN_KINDS),
            "synthetic_factual_photo_forbidden": True,
            "missing_photo_blocks_story": False,
            "fallback": "EDITORIAL_CARD",
            "min_relevance_score": 50,
        },
        "assets": [],
    }


def _prov(label: str) -> list[dict[str, str]]:
    return [{"source_ref": f"https://example.invalid/{label}", "observed_at": "2026-08-19T12:00:00Z", "evidence_fingerprint": hashlib.sha256(label.encode()).hexdigest()}]


def self_test() -> None:
    from site_publication import ensure_publication_schema

    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "runtime.sqlite3")
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_knowledge_schema(conn)
        ensure_media_schema(conn)
        engine = "vnext-p13-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b"), engine_version=engine)
        validate_photo_pack(_pack("alpha-local"), instance_id="alpha-local")
        validate_photo_pack(_pack("beta-local"), instance_id="beta-local")
        create_story(conn, instance_id="alpha-local", story_id="story-a", fingerprint="story-a-fp", engine_version=engine, headline="Story A")
        create_story(conn, instance_id="alpha-local", story_id="story-no-photo", fingerprint="story-b-fp", engine_version=engine, headline="Story B")
        create_story(conn, instance_id="beta-local", story_id="story-a", fingerprint="story-beta-fp", engine_version=engine, headline="Story A beta")

        try:
            register_media_asset(
                conn, instance_id="alpha-local", asset_kind="REAL_PHOTO", origin_kind="LICENSED",
                storage_ref="site-owned://media/bad.jpg", source_url="https://example.invalid/bad", credit="Example",
                rights_basis="LICENSE", license_code="CUSTOM", rights_evidence_ref="https://example.invalid/rights",
                rights_evidence_fingerprint=hashlib.sha256(b"rights").hexdigest(), content_fingerprint=hashlib.sha256(b"bad").hexdigest(),
                mime_type="image/jpeg", freshness_class="EVERGREEN", usage_scope=["SITE"], provenance=_prov("bad"),
                engine_version=engine, synthetic=True, depicts_real_scene=True,
            )
        except MediaIntelligenceError:
            pass
        else:
            raise AssertionError("synthetic factual photo was accepted")

        photo, created = register_media_asset(
            conn, instance_id="alpha-local", asset_kind="REAL_PHOTO", origin_kind="CREATIVE_COMMONS",
            storage_ref="site-owned://media/photo.jpg", source_url="https://example.invalid/photo", credit="Example Author",
            rights_basis="OPEN_LICENSE", license_code="CC-BY-4.0", rights_evidence_ref="https://example.invalid/license",
            rights_evidence_fingerprint=hashlib.sha256(b"cc-rights").hexdigest(), content_fingerprint=hashlib.sha256(b"photo-bytes").hexdigest(),
            mime_type="image/jpeg", width=1600, height=1000, captured_at="2026-08-19", freshness_class="SLOW_DECAY",
            usage_scope=["SITE", "SOCIAL"], provenance=_prov("photo"), engine_version=engine, synthetic=False, depicts_real_scene=True,
        )
        assert created and photo["status"] == "RIGHTS_VERIFIED"
        beta_photo, _ = register_media_asset(
            conn, instance_id="beta-local", asset_kind="REAL_PHOTO", origin_kind="USER_OWNED",
            storage_ref="site-owned://media/beta.jpg", credit="Owner", rights_basis="OWNED", license_code="OWNED",
            rights_evidence_ref="site-owned://rights/beta", rights_evidence_fingerprint=hashlib.sha256(b"beta-rights").hexdigest(),
            content_fingerprint=hashlib.sha256(b"beta-photo").hexdigest(), mime_type="image/jpeg", freshness_class="EVERGREEN",
            usage_scope=["SITE"], provenance=[{"source_ref": "site-owned://upload/beta", "observed_at": "2026-08-19T12:00:00Z", "evidence_fingerprint": hashlib.sha256(b"beta-prov").hexdigest()}],
            engine_version=engine, synthetic=False, depicts_real_scene=True,
        )
        assert beta_photo["media_id"] != photo["media_id"]
        bind_media(
            conn, instance_id="alpha-local", media_id=photo["media_id"], target_type="STORY", target_id="story-a",
            specificity_class="EVENT_DIRECT", relevance_score=95, usage_scope=["SITE", "SOCIAL"], provenance=_prov("binding"), engine_version=engine,
        )
        try:
            bind_media(
                conn, instance_id="beta-local", media_id=photo["media_id"], target_type="STORY", target_id="story-a",
                specificity_class="EVENT_DIRECT", relevance_score=95, usage_scope=["SITE"], provenance=_prov("cross"), engine_version=engine,
            )
        except MediaIntelligenceError:
            pass
        else:
            raise AssertionError("cross-instance media binding was accepted")
        assignment = resolve_story_media(conn, instance_id="alpha-local", story_id="story-a", photo_pack=_pack("alpha-local"), usage_scope="SITE", engine_version=engine)
        assert assignment["assignment_status"] == "MEDIA_READY" and assignment["media_id"] == photo["media_id"]
        fallback = resolve_story_media(conn, instance_id="alpha-local", story_id="story-no-photo", photo_pack=_pack("alpha-local"), usage_scope="SITE", engine_version=engine)
        assert fallback["assignment_status"] == "EDITORIAL_CARD_REQUIRED" and fallback["media_id"] is None
        assert resolve_story_media(conn, instance_id="beta-local", story_id="story-a", photo_pack=_pack("beta-local"), usage_scope="SITE", engine_version=engine)["assignment_status"] == "EDITORIAL_CARD_REQUIRED"
        assert get_story_media_projection(conn, instance_id="alpha-local", story_id="story-a", usage_scope="SITE")["asset"]["credit"] == "Example Author"
        conn.close()
    print("VNEXT_MEDIA_INTELLIGENCE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test or import the module from the site runtime")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
