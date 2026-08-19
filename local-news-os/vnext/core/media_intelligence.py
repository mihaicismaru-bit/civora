#!/usr/bin/env python3
"""Site-owned Photo Atlas and media resolver for LOCAL NEWS OS vNext.

The generic core stores media, rights evidence, bindings, derivatives, selections
and photo debt in the site runtime database. It never reads repository runtime
state and contains no locality-specific source, entity or publication logic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Iterable

from knowledge_graph import ensure_knowledge_schema
from runtime_store import connect, create_story, get_story, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema

ROOT = Path(__file__).resolve().parents[3]
MEDIA_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "media_schema.sql"

MEDIA_KINDS = {"PHOTO", "DOCUMENT_VISUAL", "EDITORIAL_CARD"}
SOURCE_TYPES = {"USER_OWNED", "OFFICIAL", "OPEN_LICENSED", "EXPLICIT_LICENSED", "DOCUMENT_GENERATED", "EDITORIAL_CARD"}
RIGHTS_BASES = {"USER_OWNED", "OFFICIAL_PRESS_USE", "CC_BY", "CC_BY_SA", "CC0", "PUBLIC_DOMAIN", "EXPLICIT_LICENSE", "DOCUMENT_DERIVATIVE", "EDITORIAL_CARD"}
FRESHNESS_CLASSES = {"EVERGREEN", "SLOW_DECAY", "FAST_DECAY", "EVENT_ONLY"}
SPECIFICITY_ORDER = (
    "EVENT_DIRECT",
    "SUBJECT_DIRECT",
    "PLACE_DIRECT",
    "CONTEXT_CURRENT",
    "CONTEXT_ARCHIVE",
    "DOCUMENT_VISUAL",
)
DEFAULT_USAGE_SCOPES = {"SITE_HERO", "SITE_CARD", "SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM", "PROFILE", "ARCHIVE"}


class MediaIntelligenceError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MediaIntelligenceError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(prefix: str, *parts: str, length: int = 24) -> str:
    return f"{prefix}_{hashlib.sha256(chr(10).join(parts).encode('utf-8')).hexdigest()[:length]}"


def ensure_media_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(MEDIA_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def validate_media_policy(pack: dict[str, Any], *, instance_id: str) -> dict[str, Any]:
    _require(isinstance(pack, dict), "photo pack must be an object")
    _require(pack.get("schema_version") == "2.0", "photo pack schema mismatch")
    _require(pack.get("pack_type") == "photos", "not a photo pack")
    _require(pack.get("instance_id") == instance_id, "photo pack instance mismatch")
    raw = pack.get("resolver_policy") or {}
    _require(isinstance(raw, dict), "photo pack resolver_policy must be an object")
    scopes = {str(v).strip().upper() for v in raw.get("allowed_usage_scopes", DEFAULT_USAGE_SCOPES)}
    _require(bool(scopes) and scopes <= DEFAULT_USAGE_SCOPES, "invalid media usage scopes")
    rights = {str(v).strip().upper() for v in raw.get("allowed_rights_bases", RIGHTS_BASES)}
    _require(bool(rights) and rights <= RIGHTS_BASES, "invalid rights policy")
    fallback = str(raw.get("fallback") or "EDITORIAL_CARD").strip().upper()
    _require(fallback in {"EDITORIAL_CARD", "NO_VISUAL"}, "invalid media fallback")
    ladder = tuple(str(v).strip().upper() for v in raw.get("specificity_order", SPECIFICITY_ORDER))
    _require(ladder == SPECIFICITY_ORDER, "specificity order must preserve canonical resolver ladder")
    return {
        "allowed_usage_scopes": scopes,
        "allowed_rights_bases": rights,
        "fallback": fallback,
        "specificity_order": ladder,
    }


def _provenance(provenance: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {}
    for raw in provenance:
        _require(isinstance(raw, dict), "media provenance entries must be objects")
        item = {
            "source_url": _clean(raw.get("source_url")),
            "evidence_fingerprint": _clean(raw.get("evidence_fingerprint")),
            "observed_at": _clean(raw.get("observed_at")),
        }
        _require(all(item.values()), "media provenance requires source_url, evidence_fingerprint and observed_at")
        _require(item["source_url"].startswith(("http://", "https://")), "media provenance source_url must be HTTP(S)")
        _require(len(item["evidence_fingerprint"]) >= 16, "media provenance fingerprint is too short")
        if raw.get("note") is not None:
            item["note"] = _clean(raw.get("note"))
        values[json.dumps(item, ensure_ascii=False, sort_keys=True)] = item
    _require(bool(values), "media provenance is mandatory")
    return [values[k] for k in sorted(values)]


def _emit(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    reason: str,
    payload: dict[str, Any],
    engine_version: str,
    created_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_events(
            instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at
        ) VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            instance_id,
            aggregate_type,
            aggregate_id,
            event_type,
            reason,
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            engine_version,
            created_at,
        ),
    )


def _decode_asset(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["usage_scopes"] = json.loads(item.pop("usage_scopes_json"))
    item["metadata"] = json.loads(item.pop("metadata_json"))
    item["synthetic"] = bool(item["synthetic"])
    item["depicts_real_scene"] = bool(item["depicts_real_scene"])
    return item


def _decode_selection(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["fallback_payload"] = json.loads(item.pop("fallback_payload_json"))
    return item


def get_media_asset(conn: sqlite3.Connection, *, instance_id: str, asset_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM media_assets WHERE instance_id=? AND asset_id=?",
        (instance_id, asset_id),
    ).fetchone()
    if row is None:
        raise MediaIntelligenceError("media asset not found for instance")
    return _decode_asset(row)


def list_media_assets(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    status: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_media_schema(conn)
    bounded = max(1, min(2000, int(limit)))
    if status:
        wanted = _clean(status).upper()
        _require(wanted in {"READY", "HELD", "RETIRED"}, "unsupported media status")
        rows = conn.execute(
            "SELECT * FROM media_assets WHERE instance_id=? AND status=? ORDER BY updated_at DESC,asset_id LIMIT ?",
            (instance_id, wanted, bounded),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM media_assets WHERE instance_id=? ORDER BY updated_at DESC,asset_id LIMIT ?",
            (instance_id, bounded),
        ).fetchall()
    return [_decode_asset(row) for row in rows]


def register_media_asset(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    asset: dict[str, Any],
    media_policy: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    policy = validate_media_policy(media_policy, instance_id=instance_id)
    _require(isinstance(asset, dict), "media asset must be an object")
    kind = _clean(asset.get("media_kind")).upper()
    source_type = _clean(asset.get("source_type")).upper()
    rights_basis = _clean(asset.get("rights_basis")).upper()
    freshness = _clean(asset.get("freshness_class")).upper()
    storage_uri = _clean(asset.get("storage_uri"))
    source_url = _clean(asset.get("source_url"))
    license_code = _clean(asset.get("license_code"))
    credit = _clean(asset.get("credit"))
    rights_evidence = _clean(asset.get("rights_evidence"))
    content_fingerprint = _clean(asset.get("content_fingerprint")).lower()
    status = _clean(asset.get("status") or "READY").upper()
    synthetic = bool(asset.get("synthetic", False))
    depicts_real_scene = bool(asset.get("depicts_real_scene", kind == "PHOTO"))
    usage_scopes = sorted({_clean(v).upper() for v in asset.get("usage_scopes") or []})
    metadata = dict(asset.get("metadata") or {})
    provenance = _provenance(asset.get("provenance") or [])

    _require(kind in MEDIA_KINDS, "unsupported media kind")
    _require(source_type in SOURCE_TYPES, "unsupported media source type")
    _require(rights_basis in RIGHTS_BASES and rights_basis in policy["allowed_rights_bases"], "media rights basis is not allowed")
    _require(freshness in FRESHNESS_CLASSES, "unsupported media freshness class")
    _require(status in {"READY", "HELD", "RETIRED"}, "unsupported media status")
    _require(bool(storage_uri) and not storage_uri.startswith(("git://", "repo://")), "media must use site-owned storage, not repository runtime state")
    _require(bool(license_code) and bool(credit) and bool(rights_evidence), "rights/license/credit evidence is mandatory")
    _require(rights_evidence.startswith(("http://", "https://", "OWNERSHIP:", "LICENSE_DOC:")), "unsupported rights evidence reference")
    _require(len(content_fingerprint) >= 32 and all(c in "0123456789abcdef" for c in content_fingerprint), "content fingerprint must be hex")
    _require(bool(usage_scopes) and set(usage_scopes) <= policy["allowed_usage_scopes"], "invalid asset usage scopes")

    if source_type in {"OFFICIAL", "OPEN_LICENSED", "EXPLICIT_LICENSED"}:
        _require(source_url.startswith(("http://", "https://")), "external media requires source_url")
    if source_type == "USER_OWNED":
        _require(rights_basis == "USER_OWNED" and rights_evidence.startswith("OWNERSHIP:"), "user-owned media requires ownership evidence")
    if source_type == "OFFICIAL":
        _require(rights_basis in {"OFFICIAL_PRESS_USE", "EXPLICIT_LICENSE"}, "official source is not itself a reuse license")
    if source_type == "OPEN_LICENSED":
        _require(rights_basis in {"CC_BY", "CC_BY_SA", "CC0", "PUBLIC_DOMAIN"}, "open-licensed source requires an open rights basis")
    if kind == "PHOTO":
        _require(not synthetic, "synthetic media cannot be registered as factual photography")
        _require(depicts_real_scene, "PHOTO must depict a real scene")
    if kind == "DOCUMENT_VISUAL":
        _require(not synthetic and not depicts_real_scene, "document visual cannot masquerade as factual photography")
    if kind == "EDITORIAL_CARD":
        _require(source_type == "EDITORIAL_CARD" and rights_basis == "EDITORIAL_CARD", "editorial card rights mismatch")
        _require(not synthetic and not depicts_real_scene, "editorial card is a graphic, not factual photography")

    asset_id = _clean(asset.get("asset_id")) or _hash_id("media", instance_id, content_fingerprint)
    fingerprint = _stable_hash({
        "instance_id": instance_id,
        "asset_id": asset_id,
        "media_kind": kind,
        "storage_uri": storage_uri,
        "source_type": source_type,
        "source_url": source_url,
        "rights_basis": rights_basis,
        "license_code": license_code,
        "credit": credit,
        "rights_evidence": rights_evidence,
        "synthetic": synthetic,
        "depicts_real_scene": depicts_real_scene,
        "freshness_class": freshness,
        "captured_at": _clean(asset.get("captured_at")),
        "usage_scopes": usage_scopes,
        "metadata": metadata,
        "content_fingerprint": content_fingerprint,
        "status": status,
        "provenance": provenance,
    })
    existing = conn.execute(
        "SELECT asset_id FROM media_assets WHERE instance_id=? AND content_fingerprint=?",
        (instance_id, content_fingerprint),
    ).fetchone()
    if existing is not None:
        current = get_media_asset(conn, instance_id=instance_id, asset_id=str(existing["asset_id"]))
        _require(current["asset_id"] == asset_id, "content fingerprint already belongs to another asset id")
        return current, False

    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO media_assets(
                instance_id,asset_id,media_kind,storage_uri,source_type,source_url,rights_basis,license_code,
                credit,rights_evidence,synthetic,depicts_real_scene,freshness_class,captured_at,usage_scopes_json,
                metadata_json,content_fingerprint,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                instance_id, asset_id, kind, storage_uri, source_type, source_url or None, rights_basis, license_code,
                credit, rights_evidence, 1 if synthetic else 0, 1 if depicts_real_scene else 0, freshness,
                _clean(asset.get("captured_at")) or None, json.dumps(usage_scopes, ensure_ascii=False),
                json.dumps(metadata | {"provenance": provenance, "registration_fingerprint": fingerprint}, ensure_ascii=False, sort_keys=True),
                content_fingerprint, status, now, now,
            ),
        )
        _emit(
            conn,
            instance_id=instance_id,
            aggregate_type="media_asset",
            aggregate_id=asset_id,
            event_type="MEDIA_ASSET_REGISTERED",
            reason="rights-validated site-owned media registered",
            payload={"media_kind": kind, "rights_basis": rights_basis, "content_fingerprint": content_fingerprint},
            engine_version=engine_version,
            created_at=now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_media_asset(conn, instance_id=instance_id, asset_id=asset_id), True


def bind_media_asset(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    asset_id: str,
    target_type: str,
    target_id: str,
    specificity_class: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    context_disclosure: str = "",
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    ensure_knowledge_schema(conn)
    kind = _clean(target_type).upper()
    target = _clean(target_id)
    specificity = _clean(specificity_class).upper()
    disclosure = _clean(context_disclosure)
    sources = _provenance(provenance)
    _require(kind in {"STORY", "ENTITY"}, "unsupported media binding target")
    _require(specificity in SPECIFICITY_ORDER, "unsupported media specificity class")
    get_media_asset(conn, instance_id=instance_id, asset_id=asset_id)
    if specificity in {"CONTEXT_CURRENT", "CONTEXT_ARCHIVE"}:
        _require(bool(disclosure), "contextual media requires explicit context disclosure")
    if kind == "STORY":
        get_story(conn, instance_id=instance_id, story_id=target)
    else:
        found = conn.execute(
            "SELECT 1 FROM knowledge_entities WHERE instance_id=? AND entity_id=?",
            (instance_id, target),
        ).fetchone()
        _require(found is not None, "media entity binding target not found")
    fingerprint = _stable_hash({
        "instance_id": instance_id,
        "asset_id": asset_id,
        "target_type": kind,
        "target_id": target,
        "specificity_class": specificity,
        "context_disclosure": disclosure,
        "provenance": sources,
    })
    existing = conn.execute(
        "SELECT * FROM media_bindings WHERE instance_id=? AND fingerprint=?",
        (instance_id, fingerprint),
    ).fetchone()
    if existing is not None:
        return dict(existing), False
    binding_id = _hash_id("mbind", instance_id, fingerprint)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO media_bindings(
            instance_id,binding_id,asset_id,target_type,target_id,specificity_class,
            context_disclosure,provenance_json,fingerprint,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (instance_id, binding_id, asset_id, kind, target, specificity, disclosure, json.dumps(sources, ensure_ascii=False, sort_keys=True), fingerprint, now),
    )
    _emit(
        conn,
        instance_id=instance_id,
        aggregate_type="media_asset",
        aggregate_id=asset_id,
        event_type="MEDIA_ASSET_BOUND",
        reason="evidence-bound media subject relation registered",
        payload={"binding_id": binding_id, "target_type": kind, "target_id": target, "specificity_class": specificity},
        engine_version=engine_version,
        created_at=now,
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM media_bindings WHERE instance_id=? AND binding_id=?", (instance_id, binding_id)).fetchone()), True


def register_derivative(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    asset_id: str,
    variant: str,
    storage_uri: str,
    content_fingerprint: str,
    engine_version: str,
    width: int | None = None,
    height: int | None = None,
    crop: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_media_schema(conn)
    get_media_asset(conn, instance_id=instance_id, asset_id=asset_id)
    name = _clean(variant).upper()
    uri = _clean(storage_uri)
    digest = _clean(content_fingerprint).lower()
    _require(bool(name) and bool(uri), "derivative variant and storage URI are required")
    _require(not uri.startswith(("git://", "repo://")), "derivative must use site-owned storage")
    _require(len(digest) >= 32 and all(c in "0123456789abcdef" for c in digest), "derivative content fingerprint must be hex")
    if width is not None:
        _require(int(width) > 0, "derivative width must be positive")
    if height is not None:
        _require(int(height) > 0, "derivative height must be positive")
    existing = conn.execute(
        "SELECT * FROM media_derivatives WHERE instance_id=? AND asset_id=? AND variant=?",
        (instance_id, asset_id, name),
    ).fetchone()
    if existing is not None:
        _require(str(existing["content_fingerprint"]) == digest, "derivative variant already exists with different content")
        return dict(existing), False
    derivative_id = _hash_id("mder", instance_id, asset_id, name, digest)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO media_derivatives(instance_id,derivative_id,asset_id,variant,storage_uri,width,height,crop_json,content_fingerprint,created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?)
        """,
        (instance_id, derivative_id, asset_id, name, uri, width, height, json.dumps(crop or {}, ensure_ascii=False, sort_keys=True), digest, now),
    )
    _emit(
        conn,
        instance_id=instance_id,
        aggregate_type="media_asset",
        aggregate_id=asset_id,
        event_type="MEDIA_DERIVATIVE_REGISTERED",
        reason="site-owned crop or derivative registered",
        payload={"derivative_id": derivative_id, "variant": name, "content_fingerprint": digest},
        engine_version=engine_version,
        created_at=now,
    )
    conn.commit()
    return dict(conn.execute("SELECT * FROM media_derivatives WHERE instance_id=? AND derivative_id=?", (instance_id, derivative_id)).fetchone()), True


def _eligible_bindings(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    usage_scope: str,
    policy: dict[str, Any],
) -> list[dict[str, Any]]:
    entity_rows = conn.execute(
        "SELECT entity_id FROM story_entity_links WHERE instance_id=? AND story_id=?",
        (instance_id, story_id),
    ).fetchall()
    entity_ids = [str(row["entity_id"]) for row in entity_rows]
    rows = list(conn.execute(
        """
        SELECT b.*,a.* FROM media_bindings b
        JOIN media_assets a ON a.instance_id=b.instance_id AND a.asset_id=b.asset_id
        WHERE b.instance_id=? AND b.target_type='STORY' AND b.target_id=? AND a.status='READY'
        """,
        (instance_id, story_id),
    ).fetchall())
    if entity_ids:
        placeholders = ",".join("?" for _ in entity_ids)
        rows.extend(conn.execute(
            f"""
            SELECT b.*,a.* FROM media_bindings b
            JOIN media_assets a ON a.instance_id=b.instance_id AND a.asset_id=b.asset_id
            WHERE b.instance_id=? AND b.target_type='ENTITY' AND b.target_id IN ({placeholders}) AND a.status='READY'
            """,
            [instance_id, *entity_ids],
        ).fetchall())
    candidates: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        scopes = set(json.loads(item["usage_scopes_json"]))
        if usage_scope not in scopes:
            continue
        if item["rights_basis"] not in policy["allowed_rights_bases"]:
            continue
        if item["freshness_class"] == "EVENT_ONLY" and item["specificity_class"] != "EVENT_DIRECT":
            continue
        if item["specificity_class"] in {"CONTEXT_CURRENT", "CONTEXT_ARCHIVE"} and not _clean(item["context_disclosure"]):
            continue
        candidates.append(item)
    specificity_rank = {name: idx for idx, name in enumerate(policy["specificity_order"])}
    freshness_rank = {"EVENT_ONLY": 0, "FAST_DECAY": 1, "SLOW_DECAY": 2, "EVERGREEN": 3}
    source_rank = {"USER_OWNED": 0, "OFFICIAL": 1, "OPEN_LICENSED": 2, "EXPLICIT_LICENSED": 3, "DOCUMENT_GENERATED": 4, "EDITORIAL_CARD": 5}
    candidates.sort(key=lambda item: (
        specificity_rank[str(item["specificity_class"])],
        freshness_rank[str(item["freshness_class"])],
        source_rank[str(item["source_type"])],
        str(item["asset_id"]),
    ))
    return candidates


def _fallback_payload(conn: sqlite3.Connection, *, instance_id: str, story_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT s.headline,p.canonical_path,r.snapshot_json
        FROM stories s
        JOIN story_publications p ON p.instance_id=s.instance_id AND p.story_id=s.story_id
        LEFT JOIN publication_revisions r
          ON r.instance_id=p.instance_id AND r.publication_id=p.publication_id AND r.revision=p.current_revision
        WHERE s.instance_id=? AND s.story_id=?
        """,
        (instance_id, story_id),
    ).fetchone()
    _require(row is not None, "media resolution requires a site-owned published story")
    snapshot = json.loads(row["snapshot_json"]) if row["snapshot_json"] else {}
    return {
        "story_id": story_id,
        "headline": _clean(snapshot.get("headline") or row["headline"]),
        "dek": _clean(snapshot.get("dek")),
        "section": _clean(snapshot.get("section")),
        "canonical_path": _clean(row["canonical_path"]),
        "visual_policy": "editorial_text_card_no_synthetic_depiction",
    }


def get_story_media_selection(
    conn: sqlite3.Connection, *, instance_id: str, story_id: str, usage_scope: str
) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM story_media_selections WHERE instance_id=? AND story_id=? AND usage_scope=?",
        (instance_id, story_id, _clean(usage_scope).upper()),
    ).fetchone()
    return _decode_selection(row) if row is not None else None


def resolve_story_media(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    usage_scope: str,
    media_policy: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    ensure_publication_schema(conn)
    ensure_knowledge_schema(conn)
    ensure_media_schema(conn)
    policy = validate_media_policy(media_policy, instance_id=instance_id)
    scope = _clean(usage_scope).upper()
    _require(scope in policy["allowed_usage_scopes"], "usage scope not allowed by instance media policy")
    publication = conn.execute(
        "SELECT 1 FROM story_publications WHERE instance_id=? AND story_id=?",
        (instance_id, story_id),
    ).fetchone()
    _require(publication is not None, "media resolution requires a published story")
    get_story(conn, instance_id=instance_id, story_id=story_id)

    candidates = _eligible_bindings(conn, instance_id=instance_id, story_id=story_id, usage_scope=scope, policy=policy)
    chosen = candidates[0] if candidates else None
    if chosen is not None:
        selection_kind = "ASSET"
        asset_id: str | None = str(chosen["asset_id"])
        specificity: str | None = str(chosen["specificity_class"])
        disclosure = _clean(chosen["context_disclosure"])
        fallback: dict[str, Any] = {}
    else:
        selection_kind = policy["fallback"]
        asset_id = None
        specificity = None
        disclosure = ""
        fallback = _fallback_payload(conn, instance_id=instance_id, story_id=story_id) if selection_kind == "EDITORIAL_CARD" else {}

    resolver_fingerprint = _stable_hash({
        "instance_id": instance_id,
        "story_id": story_id,
        "usage_scope": scope,
        "selection_kind": selection_kind,
        "asset_id": asset_id,
        "specificity_class": specificity,
        "context_disclosure": disclosure,
        "fallback": fallback,
        "candidate_asset_ids": [str(item["asset_id"]) for item in candidates],
        "policy": {"fallback": policy["fallback"], "specificity_order": policy["specificity_order"]},
    })
    existing = get_story_media_selection(conn, instance_id=instance_id, story_id=story_id, usage_scope=scope)
    if existing is not None and existing["resolver_fingerprint"] == resolver_fingerprint:
        return existing, False

    selection_id = existing["selection_id"] if existing is not None else _hash_id("msel", instance_id, story_id, scope)
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        if existing is None:
            conn.execute(
                """
                INSERT INTO story_media_selections(
                    instance_id,selection_id,story_id,usage_scope,selection_kind,asset_id,specificity_class,
                    context_disclosure,fallback_payload_json,resolver_fingerprint,revision,created_at,updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)
                """,
                (instance_id, selection_id, story_id, scope, selection_kind, asset_id, specificity, disclosure,
                 json.dumps(fallback, ensure_ascii=False, sort_keys=True), resolver_fingerprint, now, now),
            )
            event_type = "STORY_MEDIA_SELECTED"
        else:
            conn.execute(
                """
                UPDATE story_media_selections
                SET selection_kind=?,asset_id=?,specificity_class=?,context_disclosure=?,fallback_payload_json=?,
                    resolver_fingerprint=?,revision=revision+1,updated_at=?
                WHERE instance_id=? AND selection_id=?
                """,
                (selection_kind, asset_id, specificity, disclosure, json.dumps(fallback, ensure_ascii=False, sort_keys=True),
                 resolver_fingerprint, now, instance_id, selection_id),
            )
            event_type = "STORY_MEDIA_SELECTION_UPGRADED" if existing["selection_kind"] != "ASSET" and selection_kind == "ASSET" else "STORY_MEDIA_SELECTION_UPDATED"

        debt_id = _hash_id("mdebt", instance_id, story_id, scope)
        if selection_kind == "ASSET":
            conn.execute(
                """
                UPDATE media_debt SET status='RESOLVED',resolved_at=?,updated_at=?
                WHERE instance_id=? AND story_id=? AND usage_scope=? AND status='OPEN'
                """,
                (now, now, instance_id, story_id, scope),
            )
        else:
            reason = "no rights-safe relevant real asset; editorial-card fallback used" if selection_kind == "EDITORIAL_CARD" else "no rights-safe relevant visual available"
            conn.execute(
                """
                INSERT INTO media_debt(instance_id,debt_id,story_id,usage_scope,status,reason,selection_id,opened_at,resolved_at,updated_at)
                VALUES (?,?,?,?, 'OPEN',?,?,?,NULL,?)
                ON CONFLICT(instance_id,story_id,usage_scope) DO UPDATE SET
                    status='OPEN',reason=excluded.reason,selection_id=excluded.selection_id,resolved_at=NULL,updated_at=excluded.updated_at
                """,
                (instance_id, debt_id, story_id, scope, reason, selection_id, now, now),
            )
        _emit(
            conn,
            instance_id=instance_id,
            aggregate_type="story",
            aggregate_id=story_id,
            event_type=event_type,
            reason="deterministic media resolver completed",
            payload={
                "selection_id": selection_id,
                "usage_scope": scope,
                "selection_kind": selection_kind,
                "asset_id": asset_id,
                "specificity_class": specificity,
                "resolver_fingerprint": resolver_fingerprint,
            },
            engine_version=engine_version,
            created_at=now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_story_media_selection(conn, instance_id=instance_id, story_id=story_id, usage_scope=scope) or {}, True


def project_story_media(
    conn: sqlite3.Connection, *, instance_id: str, story_id: str, usage_scope: str
) -> dict[str, Any] | None:
    ensure_media_schema(conn)
    selection = get_story_media_selection(conn, instance_id=instance_id, story_id=story_id, usage_scope=usage_scope)
    if selection is None:
        return None
    result: dict[str, Any] = {"selection": selection, "asset": None, "derivatives": []}
    if selection["selection_kind"] == "ASSET" and selection["asset_id"]:
        asset = get_media_asset(conn, instance_id=instance_id, asset_id=str(selection["asset_id"]))
        derivatives = [
            dict(row) | {"crop": json.loads(row["crop_json"])}
            for row in conn.execute(
                "SELECT * FROM media_derivatives WHERE instance_id=? AND asset_id=? ORDER BY variant",
                (instance_id, asset["asset_id"]),
            ).fetchall()
        ]
        result["asset"] = asset
        result["derivatives"] = derivatives
    return result


def list_media_debt(conn: sqlite3.Connection, *, instance_id: str, status: str = "OPEN", limit: int = 200) -> list[dict[str, Any]]:
    ensure_media_schema(conn)
    wanted = _clean(status).upper()
    _require(wanted in {"OPEN", "RESOLVED"}, "unsupported media debt status")
    rows = conn.execute(
        "SELECT * FROM media_debt WHERE instance_id=? AND status=? ORDER BY updated_at DESC,debt_id LIMIT ?",
        (instance_id, wanted, max(1, min(2000, int(limit)))),
    ).fetchall()
    return [dict(row) for row in rows]


def import_photo_pack(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    photo_pack: dict[str, Any],
    engine_version: str,
) -> dict[str, int]:
    validate_media_policy(photo_pack, instance_id=instance_id)
    created_assets = 0
    created_bindings = 0
    for raw in photo_pack.get("assets") or []:
        _require(isinstance(raw, dict), "photo pack assets must be objects")
        asset, created = register_media_asset(
            conn,
            instance_id=instance_id,
            asset=raw,
            media_policy=photo_pack,
            engine_version=engine_version,
        )
        created_assets += int(created)
        for binding in raw.get("bindings") or []:
            _, bound = bind_media_asset(
                conn,
                instance_id=instance_id,
                asset_id=asset["asset_id"],
                target_type=str(binding.get("target_type") or ""),
                target_id=str(binding.get("target_id") or ""),
                specificity_class=str(binding.get("specificity_class") or ""),
                context_disclosure=str(binding.get("context_disclosure") or ""),
                provenance=binding.get("provenance") or raw.get("provenance") or [],
                engine_version=engine_version,
            )
            created_bindings += int(bound)
    return {"assets_created": created_assets, "bindings_created": created_bindings}


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _source(label: str) -> list[dict[str, str]]:
    digest = hashlib.sha256(label.encode("utf-8")).hexdigest()
    return [{"source_url": f"https://example.invalid/{label}", "evidence_fingerprint": digest, "observed_at": "2026-08-19T12:00:00Z"}]


def _policy(instance_id: str) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "photos",
        "instance_id": instance_id,
        "migration": {"status": "NONE"},
        "resolver_policy": {
            "allowed_usage_scopes": sorted(DEFAULT_USAGE_SCOPES),
            "allowed_rights_bases": sorted(RIGHTS_BASES),
            "specificity_order": list(SPECIFICITY_ORDER),
            "fallback": "EDITORIAL_CARD",
        },
        "assets": [],
    }


def _publish_fixture(conn: sqlite3.Connection, *, instance_id: str, story_id: str, headline: str) -> None:
    create_story(conn, instance_id=instance_id, story_id=story_id, fingerprint=_stable_hash([instance_id, story_id]), engine_version="p13-test", headline=headline)
    now = utc_now()
    conn.execute("UPDATE stories SET state='PUBLISHED',canonical_path=?,updated_at=? WHERE instance_id=? AND story_id=?", (f"/story/{story_id}/", now, instance_id, story_id))
    conn.execute(
        """
        INSERT INTO story_publications(instance_id,story_id,publication_id,canonical_path,current_revision,current_content_fingerprint,published_at,updated_at)
        VALUES (?,?,?,?,1,?,?,?)
        """,
        (instance_id, story_id, f"pub-{story_id}", f"/story/{story_id}/", _stable_hash([story_id, "published"]), now, now),
    )
    conn.commit()


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_knowledge_schema(conn)
        ensure_media_schema(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version="p13-test")
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b"), engine_version="p13-test")
        _publish_fixture(conn, instance_id="alpha-local", story_id="story-one", headline="Verified local story")
        _publish_fixture(conn, instance_id="alpha-local", story_id="story-two", headline="Story without a photo")
        _publish_fixture(conn, instance_id="beta-local", story_id="story-one", headline="Independent second instance")

        direct_raw = {
            "asset_id": "photo-direct",
            "media_kind": "PHOTO",
            "storage_uri": "https://media.invalid/direct.jpg",
            "source_type": "USER_OWNED",
            "source_url": "",
            "rights_basis": "USER_OWNED",
            "license_code": "OWNED",
            "credit": "Local newsroom",
            "rights_evidence": "OWNERSHIP:asset-ledger-1",
            "synthetic": False,
            "depicts_real_scene": True,
            "freshness_class": "EVENT_ONLY",
            "captured_at": "2026-08-19T11:00:00Z",
            "usage_scopes": ["SITE_HERO", "SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM"],
            "metadata": {"alt": "Documented event"},
            "content_fingerprint": hashlib.sha256(b"direct-photo").hexdigest(),
            "status": "READY",
            "provenance": _source("direct-photo"),
        }
        archive_raw = dict(direct_raw)
        archive_raw.update({
            "asset_id": "photo-archive",
            "storage_uri": "https://media.invalid/archive.jpg",
            "freshness_class": "EVERGREEN",
            "content_fingerprint": hashlib.sha256(b"archive-photo").hexdigest(),
            "provenance": _source("archive-photo"),
        })
        direct, created = register_media_asset(conn, instance_id="alpha-local", asset=direct_raw, media_policy=_policy("alpha-local"), engine_version="p13-test")
        assert created
        archive, _ = register_media_asset(conn, instance_id="alpha-local", asset=archive_raw, media_policy=_policy("alpha-local"), engine_version="p13-test")
        bind_media_asset(conn, instance_id="alpha-local", asset_id=archive["asset_id"], target_type="STORY", target_id="story-one", specificity_class="CONTEXT_ARCHIVE", context_disclosure="Imagine de arhivă; nu surprinde evenimentul curent.", provenance=_source("archive-binding"), engine_version="p13-test")
        bind_media_asset(conn, instance_id="alpha-local", asset_id=direct["asset_id"], target_type="STORY", target_id="story-one", specificity_class="EVENT_DIRECT", provenance=_source("direct-binding"), engine_version="p13-test")
        selection, changed = resolve_story_media(conn, instance_id="alpha-local", story_id="story-one", usage_scope="SITE_HERO", media_policy=_policy("alpha-local"), engine_version="p13-test")
        assert changed and selection["selection_kind"] == "ASSET" and selection["asset_id"] == "photo-direct"
        selection2, changed2 = resolve_story_media(conn, instance_id="alpha-local", story_id="story-one", usage_scope="SITE_HERO", media_policy=_policy("alpha-local"), engine_version="p13-test")
        assert not changed2 and selection2["resolver_fingerprint"] == selection["resolver_fingerprint"]

        derivative, d_created = register_derivative(conn, instance_id="alpha-local", asset_id="photo-direct", variant="SITE_HERO_1600X900", storage_uri="https://media.invalid/direct-1600x900.jpg", width=1600, height=900, crop={"x": 0, "y": 0, "w": 1, "h": 1}, content_fingerprint=hashlib.sha256(b"direct-photo-derivative").hexdigest(), engine_version="p13-test")
        assert d_created and derivative["width"] == 1600
        projection = project_story_media(conn, instance_id="alpha-local", story_id="story-one", usage_scope="SITE_HERO")
        assert projection and projection["asset"]["rights_basis"] == "USER_OWNED" and projection["derivatives"][0]["variant"] == "SITE_HERO_1600X900"

        fallback, _ = resolve_story_media(conn, instance_id="alpha-local", story_id="story-two", usage_scope="SITE_HERO", media_policy=_policy("alpha-local"), engine_version="p13-test")
        assert fallback["selection_kind"] == "EDITORIAL_CARD" and list_media_debt(conn, instance_id="alpha-local")[0]["story_id"] == "story-two"
        upgrade_raw = dict(archive_raw)
        upgrade_raw.update({
            "asset_id": "photo-story-two",
            "storage_uri": "https://media.invalid/story-two.jpg",
            "content_fingerprint": hashlib.sha256(b"story-two-photo").hexdigest(),
            "provenance": _source("story-two-photo"),
        })
        upgrade, _ = register_media_asset(conn, instance_id="alpha-local", asset=upgrade_raw, media_policy=_policy("alpha-local"), engine_version="p13-test")
        bind_media_asset(conn, instance_id="alpha-local", asset_id=upgrade["asset_id"], target_type="STORY", target_id="story-two", specificity_class="SUBJECT_DIRECT", provenance=_source("story-two-binding"), engine_version="p13-test")
        upgraded, changed = resolve_story_media(conn, instance_id="alpha-local", story_id="story-two", usage_scope="SITE_HERO", media_policy=_policy("alpha-local"), engine_version="p13-test")
        assert changed and upgraded["selection_kind"] == "ASSET" and not list_media_debt(conn, instance_id="alpha-local")
        assert list_media_debt(conn, instance_id="alpha-local", status="RESOLVED")[0]["story_id"] == "story-two"

        bad_synthetic = dict(direct_raw)
        bad_synthetic.update({"asset_id": "bad-synthetic", "synthetic": True, "content_fingerprint": hashlib.sha256(b"bad-synthetic").hexdigest()})
        try:
            register_media_asset(conn, instance_id="alpha-local", asset=bad_synthetic, media_policy=_policy("alpha-local"), engine_version="p13-test")
        except MediaIntelligenceError as exc:
            assert "synthetic" in str(exc)
        else:
            raise AssertionError("synthetic factual photo was accepted")

        try:
            bind_media_asset(conn, instance_id="alpha-local", asset_id="photo-archive", target_type="STORY", target_id="story-one", specificity_class="CONTEXT_ARCHIVE", provenance=_source("bad-context"), engine_version="p13-test")
        except MediaIntelligenceError as exc:
            assert "disclosure" in str(exc)
        else:
            raise AssertionError("archive context without disclosure was accepted")

        assert project_story_media(conn, instance_id="beta-local", story_id="story-one", usage_scope="SITE_HERO") is None
        beta_pack = _policy("beta-local") | {"assets": [{
            "asset_id": "beta-owned",
            "media_kind": "PHOTO",
            "storage_uri": "media://beta/owned.jpg",
            "source_type": "USER_OWNED",
            "source_url": "",
            "rights_basis": "USER_OWNED",
            "license_code": "OWNED",
            "credit": "Beta newsroom",
            "rights_evidence": "OWNERSHIP:beta-ledger",
            "synthetic": False,
            "depicts_real_scene": True,
            "freshness_class": "EVERGREEN",
            "usage_scopes": ["ARCHIVE"],
            "content_fingerprint": hashlib.sha256(b"beta-owned").hexdigest(),
            "status": "READY",
            "provenance": _source("beta-owned"),
        }]}
        imported = import_photo_pack(conn, instance_id="beta-local", photo_pack=beta_pack, engine_version="p13-test")
        assert imported["assets_created"] == 1 and len(list_media_assets(conn, instance_id="beta-local")) == 1
        assert len(list_media_assets(conn, instance_id="alpha-local")) == 3
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_MEDIA_INTELLIGENCE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test; production invocation is owned by the site runtime")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
