#!/usr/bin/env python3
"""Site-owned channel product and delivery ledger for LOCAL NEWS OS vNext.

Distribution consumes only site-runtime publication/media state. The generic
core materializes deterministic channel-native products and durable delivery
state; account identifiers and credential references live only in instance
Channel Packs. External publication is never claimed until an independent
remote-readback receipt is recorded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from media_intelligence import ensure_media_schema, project_story_media
from runtime_store import connect, create_story, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema

ROOT = Path(__file__).resolve().parents[3]
DISTRIBUTION_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "distribution_schema.sql"
CHANNEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,39}$")
REF_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
CHANNEL_MODES = {"direct_capable", "outbox_only", "disabled"}
PRODUCT_TYPES = {"LINK_POST", "SINGLE_VISUAL", "TEXT_POST"}
ADAPTER_IDS = {"meta_facebook", "meta_instagram", "outbox_only", "disabled"}
DELIVERY_EVENT = "DISTRIBUTION_PRODUCT_MATERIALIZED"


class DistributionError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DistributionError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(prefix: str, *parts: str, length: int = 24) -> str:
    return f"{prefix}_{hashlib.sha256(chr(10).join(parts).encode('utf-8')).hexdigest()[:length]}"


def ensure_distribution_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(DISTRIBUTION_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


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


def validate_channels_pack(pack: dict[str, Any], *, instance_id: str) -> dict[str, dict[str, Any]]:
    _require(isinstance(pack, dict), "channels pack must be an object")
    _require(pack.get("schema_version") == "2.0", "channels pack schema mismatch")
    _require(pack.get("pack_type") == "channels", "not a channels pack")
    _require(pack.get("instance_id") == instance_id, "channels pack instance mismatch")
    raw_channels = pack.get("channels") or []
    _require(isinstance(raw_channels, list), "channels must be a list")
    channels: dict[str, dict[str, Any]] = {}
    for raw in raw_channels:
        _require(isinstance(raw, dict), "channel entries must be objects")
        channel_id = _clean(raw.get("id")).lower()
        _require(bool(CHANNEL_ID_RE.fullmatch(channel_id)), "invalid channel id")
        _require(channel_id not in channels, "duplicate channel id")
        mode = _clean(raw.get("mode") or "disabled").lower()
        _require(mode in CHANNEL_MODES, "invalid channel mode")
        enabled = bool(raw.get("enabled", mode != "disabled"))
        adapter_id = _clean(raw.get("adapter_id") or ("disabled" if mode == "disabled" else "outbox_only")).lower()
        _require(adapter_id in ADAPTER_IDS, "unsupported distribution adapter")
        if mode == "direct_capable":
            _require(adapter_id in {"meta_facebook", "meta_instagram"}, "direct-capable channel requires a bounded direct adapter")
        if mode == "outbox_only":
            _require(adapter_id == "outbox_only", "outbox-only channel must use outbox adapter")
        if mode == "disabled":
            _require(adapter_id == "disabled", "disabled channel must use disabled adapter")
        product_type = _clean(raw.get("product_type") or "LINK_POST").upper()
        _require(product_type in PRODUCT_TYPES, "unsupported channel product type")
        media_usage_scope = _clean(raw.get("media_usage_scope")).upper()
        require_visual = bool(raw.get("require_visual", product_type == "SINGLE_VISUAL"))
        if require_visual:
            _require(bool(media_usage_scope), "visual channel requires media_usage_scope")
        account = raw.get("account") or {}
        _require(isinstance(account, dict), "channel account config must be an object")
        account_id = _clean(account.get("id"))
        account_ref = _clean(account.get("id_ref"))
        _require(not (account_id and account_ref), "use account.id or account.id_ref, not both")
        if account_ref:
            _require(bool(REF_RE.fullmatch(account_ref)), "account.id_ref must be a runtime reference name")
        credential_refs = raw.get("credential_refs") or {}
        _require(isinstance(credential_refs, dict), "credential_refs must be an object")
        normalized_refs: dict[str, str] = {}
        for role, ref in credential_refs.items():
            role_name = _clean(role).lower()
            ref_name = _clean(ref)
            _require(bool(role_name) and bool(REF_RE.fullmatch(ref_name)), "credential values are forbidden; use reference names")
            normalized_refs[role_name] = ref_name
        apply_gate_ref = _clean(raw.get("apply_gate_ref"))
        if apply_gate_ref:
            _require(bool(REF_RE.fullmatch(apply_gate_ref)), "apply_gate_ref must be a runtime reference name")
        channels[channel_id] = {
            "id": channel_id,
            "mode": mode,
            "enabled": enabled,
            "adapter_id": adapter_id,
            "product_type": product_type,
            "media_usage_scope": media_usage_scope,
            "require_visual": require_visual,
            "account": {"id": account_id, "id_ref": account_ref},
            "credential_refs": normalized_refs,
            "apply_gate_ref": apply_gate_ref,
        }
    return channels


def _decode_product(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["payload"] = json.loads(item.pop("payload_json"))
    return item


def _decode_attempt(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["response"] = json.loads(item.pop("response_json"))
    return item


def _decode_receipt(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["evidence"] = json.loads(item.pop("evidence_json"))
    item["verified"] = bool(item["verified"])
    return item


def _publication_snapshot(conn: sqlite3.Connection, *, instance_id: str, story_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT p.publication_id,p.current_revision,p.canonical_path,p.current_content_fingerprint,
               p.published_at,p.updated_at,r.snapshot_json,i.canonical_domain
        FROM story_publications p
        JOIN publication_revisions r
          ON r.instance_id=p.instance_id AND r.publication_id=p.publication_id AND r.revision=p.current_revision
        JOIN publication_instances i ON i.instance_id=p.instance_id
        WHERE p.instance_id=? AND p.story_id=?
        """,
        (instance_id, story_id),
    ).fetchone()
    _require(row is not None, "distribution requires a site-owned published story")
    snapshot = json.loads(row["snapshot_json"])
    return dict(row) | {"snapshot": snapshot, "canonical_url": f"https://{row['canonical_domain']}{row['canonical_path']}"}


def _media_payload(conn: sqlite3.Connection, *, instance_id: str, story_id: str, usage_scope: str) -> tuple[str | None, dict[str, Any] | None]:
    if not usage_scope:
        return None, None
    projection = project_story_media(conn, instance_id=instance_id, story_id=story_id, usage_scope=usage_scope)
    if projection is None:
        return None, None
    selection = projection["selection"]
    payload: dict[str, Any] = {
        "selection_kind": selection["selection_kind"],
        "specificity_class": selection.get("specificity_class"),
        "context_disclosure": selection.get("context_disclosure") or "",
    }
    if selection["selection_kind"] == "ASSET" and projection.get("asset"):
        asset = projection["asset"]
        derivatives = projection.get("derivatives") or []
        payload["asset"] = {
            "asset_id": asset["asset_id"],
            "media_kind": asset["media_kind"],
            "storage_uri": asset["storage_uri"],
            "source_url": asset.get("source_url"),
            "rights_basis": asset["rights_basis"],
            "license_code": asset["license_code"],
            "credit": asset["credit"],
            "synthetic": asset["synthetic"],
            "depicts_real_scene": asset["depicts_real_scene"],
            "metadata": asset.get("metadata") or {},
        }
        payload["derivatives"] = [
            {
                "variant": item["variant"],
                "storage_uri": item["storage_uri"],
                "width": item["width"],
                "height": item["height"],
                "content_fingerprint": item["content_fingerprint"],
            }
            for item in derivatives
        ]
    elif selection["selection_kind"] == "EDITORIAL_CARD":
        payload["editorial_card"] = selection.get("fallback_payload") or {}
    return str(selection["selection_id"]), payload


def _build_channel_payload(publication: dict[str, Any], channel: dict[str, Any], media: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = publication["snapshot"]
    headline = _clean(snapshot.get("headline"))
    dek = _clean(snapshot.get("dek"))
    _require(bool(headline) and bool(publication["canonical_url"]), "published story lacks distribution identity")
    payload: dict[str, Any] = {
        "story_id": str(snapshot.get("story_id") or ""),
        "headline": headline,
        "dek": dek,
        "section": _clean(snapshot.get("section")),
        "canonical_url": publication["canonical_url"],
        "publication_revision": int(publication["current_revision"]),
        "publication_fingerprint": publication["current_content_fingerprint"],
        "channel_id": channel["id"],
        "product_type": channel["product_type"],
    }
    if channel["product_type"] == "LINK_POST":
        payload["message"] = "\n\n".join(value for value in (headline, dek, publication["canonical_url"]) if value)
    elif channel["product_type"] == "TEXT_POST":
        payload["message"] = "\n\n".join(value for value in (headline, dek) if value)
    elif channel["product_type"] == "SINGLE_VISUAL":
        payload["caption"] = "\n\n".join(value for value in (headline, dek, publication["canonical_url"]) if value)
    if media is not None:
        payload["media"] = media
    return payload


def materialize_story_distribution(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    channels_pack: dict[str, Any],
    engine_version: str,
) -> list[dict[str, Any]]:
    ensure_publication_schema(conn)
    ensure_media_schema(conn)
    ensure_distribution_schema(conn)
    channels = validate_channels_pack(channels_pack, instance_id=instance_id)
    publication = _publication_snapshot(conn, instance_id=instance_id, story_id=story_id)
    results: list[dict[str, Any]] = []
    for channel_id in sorted(channels):
        channel = channels[channel_id]
        if not channel["enabled"] or channel["mode"] == "disabled":
            continue
        selection_id, media = _media_payload(
            conn,
            instance_id=instance_id,
            story_id=story_id,
            usage_scope=channel["media_usage_scope"],
        )
        hold_reason = ""
        status = "READY"
        if channel["require_visual"] and media is None:
            status = "HELD"
            hold_reason = "required_media_selection_missing"
        payload = _build_channel_payload(publication, channel, media)
        identity = {
            "instance_id": instance_id,
            "story_id": story_id,
            "channel_id": channel_id,
            "desired_revision": int(publication["current_revision"]),
            "product_type": channel["product_type"],
            "payload": payload,
            "media_selection_id": selection_id,
            "status": status,
            "hold_reason": hold_reason,
        }
        fingerprint = _stable_hash(identity)
        existing = conn.execute(
            """
            SELECT * FROM channel_products
            WHERE instance_id=? AND story_id=? AND channel_id=? AND desired_revision=? AND product_fingerprint=?
            """,
            (instance_id, story_id, channel_id, int(publication["current_revision"]), fingerprint),
        ).fetchone()
        if existing is not None:
            product = _decode_product(existing)
        else:
            product_id = _hash_id("cprod", instance_id, story_id, channel_id, str(publication["current_revision"]), fingerprint)
            now = utc_now()
            try:
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    UPDATE channel_products SET status='SUPERSEDED',updated_at=?
                    WHERE instance_id=? AND story_id=? AND channel_id=? AND desired_revision<? AND status!='SUPERSEDED'
                    """,
                    (now, instance_id, story_id, channel_id, int(publication["current_revision"])),
                )
                conn.execute(
                    """
                    UPDATE delivery_ledger SET status='SUPERSEDED',updated_at=?
                    WHERE instance_id=? AND story_id=? AND channel_id=? AND desired_revision<?
                      AND status NOT IN ('PUBLISHED','SUPERSEDED')
                    """,
                    (now, instance_id, story_id, channel_id, int(publication["current_revision"])),
                )
                conn.execute(
                    """
                    INSERT INTO channel_products(
                        instance_id,product_id,story_id,channel_id,desired_revision,product_type,payload_json,
                        media_selection_id,product_fingerprint,status,hold_reason,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        instance_id, product_id, story_id, channel_id, int(publication["current_revision"]), channel["product_type"],
                        json.dumps(payload, ensure_ascii=False, sort_keys=True), selection_id, fingerprint, status, hold_reason, now, now,
                    ),
                )
                delivery_id = _hash_id("delivery", instance_id, story_id, channel_id, str(publication["current_revision"]))
                initial_delivery_status = "HELD" if status == "HELD" or channel["mode"] == "outbox_only" else "READY"
                delivery_error = hold_reason or ("outbox_only_channel" if channel["mode"] == "outbox_only" else "")
                conn.execute(
                    """
                    INSERT INTO delivery_ledger(
                        instance_id,delivery_id,story_id,channel_id,desired_revision,product_id,status,attempts,
                        external_object_id,remote_verified,last_error,next_retry_at,created_at,updated_at
                    ) VALUES (?,?,?,?,?,?,?,0,NULL,0,?,NULL,?,?)
                    """,
                    (instance_id, delivery_id, story_id, channel_id, int(publication["current_revision"]), product_id, initial_delivery_status, delivery_error, now, now),
                )
                _emit(
                    conn,
                    instance_id=instance_id,
                    aggregate_type="story",
                    aggregate_id=story_id,
                    event_type=DELIVERY_EVENT,
                    reason="site-owned channel-native distribution product materialized",
                    payload={
                        "product_id": product_id,
                        "delivery_id": delivery_id,
                        "channel_id": channel_id,
                        "desired_revision": int(publication["current_revision"]),
                        "status": initial_delivery_status,
                        "product_fingerprint": fingerprint,
                    },
                    engine_version=engine_version,
                    created_at=now,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            product = get_channel_product(conn, instance_id=instance_id, product_id=product_id)
        delivery = get_delivery(
            conn,
            instance_id=instance_id,
            story_id=story_id,
            channel_id=channel_id,
            desired_revision=int(publication["current_revision"]),
        )
        results.append({"channel": channel, "product": product, "delivery": delivery})
    return results


def get_channel_product(conn: sqlite3.Connection, *, instance_id: str, product_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM channel_products WHERE instance_id=? AND product_id=?",
        (instance_id, product_id),
    ).fetchone()
    if row is None:
        raise DistributionError("channel product not found for instance")
    return _decode_product(row)


def get_delivery(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    channel_id: str,
    desired_revision: int,
) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT * FROM delivery_ledger
        WHERE instance_id=? AND story_id=? AND channel_id=? AND desired_revision=?
        """,
        (instance_id, story_id, channel_id, int(desired_revision)),
    ).fetchone()
    if row is None:
        raise DistributionError("delivery not found for instance/revision")
    item = dict(row)
    item["remote_verified"] = bool(item["remote_verified"])
    return item


def list_deliveries(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    status: str | None = None,
    story_id: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    ensure_distribution_schema(conn)
    clauses = ["instance_id=?"]
    params: list[Any] = [instance_id]
    if status:
        clauses.append("status=?")
        params.append(_clean(status).upper())
    if story_id:
        clauses.append("story_id=?")
        params.append(story_id)
    params.append(max(1, min(2000, int(limit))))
    rows = conn.execute(
        f"SELECT * FROM delivery_ledger WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC,delivery_id LIMIT ?",
        params,
    ).fetchall()
    return [dict(row) | {"remote_verified": bool(row["remote_verified"])} for row in rows]


def build_adapter_request(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    delivery_id: str,
    channels_pack: dict[str, Any],
) -> dict[str, Any]:
    ensure_distribution_schema(conn)
    channels = validate_channels_pack(channels_pack, instance_id=instance_id)
    row = conn.execute(
        "SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?",
        (instance_id, delivery_id),
    ).fetchone()
    _require(row is not None, "delivery not found for adapter request")
    delivery = dict(row)
    channel = channels.get(str(delivery["channel_id"]))
    _require(channel is not None and channel["enabled"], "channel is not enabled in current instance pack")
    _require(channel["mode"] == "direct_capable", "channel is not direct-capable")
    _require(delivery["status"] in {"READY", "ERROR", "BLOCKED_EXTERNAL"}, "delivery is not eligible for a direct attempt")
    product = get_channel_product(conn, instance_id=instance_id, product_id=str(delivery["product_id"]))
    _require(product["status"] == "READY", "held/superseded product cannot be delivered")
    return {
        "contract": "LOCAL_NEWS_OS_VNEXT_DISTRIBUTION_ADAPTER_REQUEST_V1",
        "instance_id": instance_id,
        "delivery_id": delivery_id,
        "channel_id": channel["id"],
        "adapter_id": channel["adapter_id"],
        "account": dict(channel["account"]),
        "credential_refs": dict(channel["credential_refs"]),
        "apply_gate_ref": channel["apply_gate_ref"],
        "product_id": product["product_id"],
        "product_fingerprint": product["product_fingerprint"],
        "payload": product["payload"],
    }


def record_delivery_attempt(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    delivery_id: str,
    adapter_id: str,
    outcome: str,
    engine_version: str,
    response: dict[str, Any] | None = None,
    error: str = "",
    next_retry_at: str | None = None,
) -> dict[str, Any]:
    ensure_distribution_schema(conn)
    result = _clean(outcome).upper()
    _require(result in {"SUCCESS_UNVERIFIED", "ERROR", "BLOCKED_EXTERNAL"}, "unsupported delivery attempt outcome")
    row = conn.execute(
        "SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?",
        (instance_id, delivery_id),
    ).fetchone()
    _require(row is not None, "delivery not found")
    _require(row["status"] in {"READY", "ERROR", "BLOCKED_EXTERNAL", "DELIVERING"}, "delivery attempt not allowed from current state")
    attempt_number = int(row["attempts"]) + 1
    attempt_id = _hash_id("attempt", instance_id, delivery_id, str(attempt_number))
    now = utc_now()
    next_status = "DELIVERING" if result == "SUCCESS_UNVERIFIED" else result
    last_error = "" if result == "SUCCESS_UNVERIFIED" else (_clean(error) or result.lower())
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO delivery_attempts(
                instance_id,attempt_id,delivery_id,attempt_number,adapter_id,outcome,response_json,error,attempted_at
            ) VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (instance_id, attempt_id, delivery_id, attempt_number, _clean(adapter_id), result, json.dumps(response or {}, ensure_ascii=False, sort_keys=True), last_error, now),
        )
        conn.execute(
            """
            UPDATE delivery_ledger
            SET status=?,attempts=?,last_error=?,next_retry_at=?,updated_at=?
            WHERE instance_id=? AND delivery_id=?
            """,
            (next_status, attempt_number, last_error, next_retry_at, now, instance_id, delivery_id),
        )
        _emit(
            conn,
            instance_id=instance_id,
            aggregate_type="delivery",
            aggregate_id=delivery_id,
            event_type="DELIVERY_ATTEMPT_RECORDED",
            reason="bounded channel adapter attempt recorded",
            payload={"attempt_id": attempt_id, "attempt_number": attempt_number, "outcome": result, "next_status": next_status},
            engine_version=engine_version,
            created_at=now,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?", (instance_id, delivery_id)).fetchone())


def record_remote_receipt(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    delivery_id: str,
    external_object_id: str,
    verified: bool,
    verification_method: str,
    evidence: dict[str, Any],
    verified_at: str,
    engine_version: str,
    remote_url: str | None = None,
) -> dict[str, Any]:
    ensure_distribution_schema(conn)
    ext = _clean(external_object_id)
    method = _clean(verification_method)
    _require(bool(ext) and bool(method) and bool(verified_at), "remote receipt identity is incomplete")
    _require(isinstance(evidence, dict) and evidence, "remote receipt requires independent evidence")
    _require(_clean(evidence.get("provider_readback_fingerprint")) != "", "remote receipt requires provider readback fingerprint")
    row = conn.execute(
        "SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?",
        (instance_id, delivery_id),
    ).fetchone()
    _require(row is not None, "delivery not found")
    _require(int(row["attempts"]) >= 1, "remote receipt requires a recorded delivery attempt")
    receipt_id = _hash_id("receipt", instance_id, delivery_id, ext, verified_at, _stable_hash(evidence))
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO delivery_remote_receipts(
                instance_id,receipt_id,delivery_id,external_object_id,remote_url,verified,
                verification_method,evidence_json,verified_at,created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            """,
            (instance_id, receipt_id, delivery_id, ext, _clean(remote_url) or None, 1 if verified else 0, method, json.dumps(evidence, ensure_ascii=False, sort_keys=True), verified_at, now),
        )
        if verified:
            conn.execute(
                """
                UPDATE delivery_ledger
                SET status='PUBLISHED',external_object_id=?,remote_verified=1,last_error='',next_retry_at=NULL,updated_at=?
                WHERE instance_id=? AND delivery_id=?
                """,
                (ext, now, instance_id, delivery_id),
            )
            _emit(
                conn,
                instance_id=instance_id,
                aggregate_type="delivery",
                aggregate_id=delivery_id,
                event_type="DELIVERY_REMOTE_VERIFIED",
                reason="external publication promoted to PUBLISHED only after remote readback",
                payload={"receipt_id": receipt_id, "external_object_id": ext, "verification_method": method},
                engine_version=engine_version,
                created_at=now,
            )
        else:
            conn.execute(
                "UPDATE delivery_ledger SET status='ERROR',remote_verified=0,last_error='remote_readback_not_verified',updated_at=? WHERE instance_id=? AND delivery_id=?",
                (now, instance_id, delivery_id),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return dict(conn.execute("SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?", (instance_id, delivery_id)).fetchone())


def delivery_record(conn: sqlite3.Connection, *, instance_id: str, delivery_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM delivery_ledger WHERE instance_id=? AND delivery_id=?",
        (instance_id, delivery_id),
    ).fetchone()
    if row is None:
        raise DistributionError("delivery not found")
    attempts = [
        _decode_attempt(item)
        for item in conn.execute(
            "SELECT * FROM delivery_attempts WHERE instance_id=? AND delivery_id=? ORDER BY attempt_number",
            (instance_id, delivery_id),
        ).fetchall()
    ]
    receipts = [
        _decode_receipt(item)
        for item in conn.execute(
            "SELECT * FROM delivery_remote_receipts WHERE instance_id=? AND delivery_id=? ORDER BY verified_at",
            (instance_id, delivery_id),
        ).fetchall()
    ]
    product = get_channel_product(conn, instance_id=instance_id, product_id=str(row["product_id"]))
    return {"delivery": dict(row) | {"remote_verified": bool(row["remote_verified"])}, "product": product, "attempts": attempts, "remote_receipts": receipts}


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _channels(instance_id: str, *, channel_id: str, require_visual: bool = False) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "channels",
        "instance_id": instance_id,
        "channels": [{
            "id": channel_id,
            "mode": "direct_capable",
            "enabled": True,
            "adapter_id": "meta_instagram" if require_visual else "meta_facebook",
            "product_type": "SINGLE_VISUAL" if require_visual else "LINK_POST",
            "media_usage_scope": "SOCIAL_INSTAGRAM" if require_visual else "SOCIAL_FACEBOOK",
            "require_visual": require_visual,
            "account": {"id_ref": "EXAMPLE_ACCOUNT_ID"},
            "credential_refs": {"access_token": "EXAMPLE_ACCESS_TOKEN"},
            "apply_gate_ref": "EXAMPLE_LIVE_ENABLED",
        }],
    }


def _publish_fixture(conn: sqlite3.Connection, *, instance_id: str, story_id: str, headline: str) -> None:
    create_story(conn, instance_id=instance_id, story_id=story_id, fingerprint=_stable_hash([instance_id, story_id]), engine_version="p14-test", headline=headline)
    now = utc_now()
    conn.execute("UPDATE stories SET state='PUBLISHED',canonical_path=?,updated_at=? WHERE instance_id=? AND story_id=?", (f"/story/{story_id}/", now, instance_id, story_id))
    snapshot = {
        "story_id": story_id,
        "headline": headline,
        "dek": "Grounded summary.",
        "body_blocks": [{"text": "Verified fact."}],
        "factbox": [],
        "context": {},
        "source_references": [],
        "follow_up": {},
        "section": "LOCAL",
        "tags": [],
    }
    publication_id = f"pub-{story_id}"
    fingerprint = _stable_hash(snapshot)
    conn.execute(
        """
        INSERT INTO story_publications(instance_id,story_id,publication_id,canonical_path,current_revision,current_content_fingerprint,published_at,updated_at)
        VALUES (?,?,?,?,1,?,?,?)
        """,
        (instance_id, story_id, publication_id, f"/story/{story_id}/", fingerprint, now, now),
    )
    conn.execute(
        """
        INSERT INTO publication_revisions(
            instance_id,publication_revision_id,publication_id,story_id,revision,qa_decision_id,draft_fingerprint,
            content_fingerprint,snapshot_json,created_at
        ) VALUES (?,?,?,?,1,?,?,?,?,?)
        """,
        (instance_id, f"pubrev-{story_id}", publication_id, story_id, f"qa-{story_id}", f"draft-{story_id}", fingerprint, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now),
    )
    conn.commit()


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_media_schema(conn)
        ensure_distribution_schema(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version="p14-test")
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b"), engine_version="p14-test")
        _publish_fixture(conn, instance_id="alpha-local", story_id="story-one", headline="Verified local story")
        _publish_fixture(conn, instance_id="beta-local", story_id="story-one", headline="Independent second instance")

        facebook = materialize_story_distribution(conn, instance_id="alpha-local", story_id="story-one", channels_pack=_channels("alpha-local", channel_id="facebook"), engine_version="p14-test")
        assert len(facebook) == 1 and facebook[0]["delivery"]["status"] == "READY"
        request = build_adapter_request(conn, instance_id="alpha-local", delivery_id=facebook[0]["delivery"]["delivery_id"], channels_pack=_channels("alpha-local", channel_id="facebook"))
        assert request["adapter_id"] == "meta_facebook"
        serialized_request = json.dumps(request, sort_keys=True)
        assert "EXAMPLE_ACCESS_TOKEN" in serialized_request and "secret-value" not in serialized_request
        same = materialize_story_distribution(conn, instance_id="alpha-local", story_id="story-one", channels_pack=_channels("alpha-local", channel_id="facebook"), engine_version="p14-test")
        assert same[0]["product"]["product_id"] == facebook[0]["product"]["product_id"]
        assert len(list_deliveries(conn, instance_id="alpha-local")) == 1

        delivery_id = facebook[0]["delivery"]["delivery_id"]
        attempted = record_delivery_attempt(conn, instance_id="alpha-local", delivery_id=delivery_id, adapter_id="meta_facebook", outcome="SUCCESS_UNVERIFIED", response={"candidate_external_id": "remote-1"}, engine_version="p14-test")
        assert attempted["status"] == "DELIVERING" and not bool(attempted["remote_verified"])
        before = delivery_record(conn, instance_id="alpha-local", delivery_id=delivery_id)
        assert before["delivery"]["status"] != "PUBLISHED"
        published = record_remote_receipt(
            conn,
            instance_id="alpha-local",
            delivery_id=delivery_id,
            external_object_id="remote-1",
            verified=True,
            verification_method="provider_get_by_id",
            evidence={"provider_readback_fingerprint": hashlib.sha256(b"remote-readback").hexdigest(), "story_identity_confirmed": True},
            verified_at="2026-08-19T15:00:00Z",
            engine_version="p14-test",
            remote_url="https://social.invalid/remote-1",
        )
        assert published["status"] == "PUBLISHED" and bool(published["remote_verified"])
        assert len(delivery_record(conn, instance_id="alpha-local", delivery_id=delivery_id)["remote_receipts"]) == 1

        instagram = materialize_story_distribution(conn, instance_id="alpha-local", story_id="story-one", channels_pack=_channels("alpha-local", channel_id="instagram", require_visual=True), engine_version="p14-test")
        assert instagram[0]["delivery"]["status"] == "HELD"
        assert instagram[0]["delivery"]["last_error"] == "required_media_selection_missing"
        assert facebook[0]["delivery"]["delivery_id"] != instagram[0]["delivery"]["delivery_id"]

        beta = materialize_story_distribution(conn, instance_id="beta-local", story_id="story-one", channels_pack=_channels("beta-local", channel_id="facebook"), engine_version="p14-test")
        assert beta[0]["delivery"]["status"] == "READY"
        assert len(list_deliveries(conn, instance_id="beta-local")) == 1
        assert len(list_deliveries(conn, instance_id="alpha-local")) == 2

        outbox_pack = {
            "schema_version": "2.0",
            "pack_type": "channels",
            "instance_id": "alpha-local",
            "channels": [{"id": "archive-feed", "mode": "outbox_only", "adapter_id": "outbox_only", "product_type": "TEXT_POST", "enabled": True}],
        }
        outbox = materialize_story_distribution(conn, instance_id="alpha-local", story_id="story-one", channels_pack=outbox_pack, engine_version="p14-test")
        assert outbox[0]["product"]["status"] == "READY" and outbox[0]["delivery"]["status"] == "HELD"
        try:
            build_adapter_request(conn, instance_id="alpha-local", delivery_id=outbox[0]["delivery"]["delivery_id"], channels_pack=outbox_pack)
        except DistributionError as exc:
            assert "direct-capable" in str(exc)
        else:
            raise AssertionError("outbox-only delivery was accepted for direct adapter execution")

        bad_pack = _channels("alpha-local", channel_id="facebook")
        bad_pack["channels"][0]["credential_refs"]["access_token"] = "actual-secret-value"
        try:
            validate_channels_pack(bad_pack, instance_id="alpha-local")
        except DistributionError:
            pass
        else:
            raise AssertionError("credential value was accepted instead of a reference")
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_DISTRIBUTION_ENGINE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test; production execution is owned by the site runtime")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
