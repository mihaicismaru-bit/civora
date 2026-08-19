#!/usr/bin/env python3
"""Provenance-bound local knowledge graph for LOCAL NEWS OS vNext.

The graph is site-owned runtime state. Generic core code knows entity semantics,
not any locality. Identity merges, relations, public-money records and public
profiles are fail-closed unless evidence is attached explicitly.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

from runtime_store import connect, create_story, initialize, register_instance, utc_now

ROOT = Path(__file__).resolve().parents[3]
KNOWLEDGE_SCHEMA = ROOT / "local-news-os" / "vnext" / "runtime" / "knowledge_schema.sql"

ENTITY_TYPES = {
    "PERSON",
    "ARTIST",
    "ORGANIZATION",
    "COMPANY",
    "INSTITUTION",
    "EVENT",
    "VENUE",
    "PLACE",
    "PROJECT",
    "PUBLIC_MONEY_ITEM",
    "DOCUMENT",
    "STORY",
    "MEDIA_ASSET",
}
EVIDENCE_STATUSES = {"CANDIDATE", "EVIDENCE_BACKED"}
RELATION_BASES = {"DIRECT_EVIDENCE", "DOCUMENTED_SOURCE"}
PROVENANCE_KEYS = {"source_url", "evidence_fingerprint", "observed_at"}
TOKEN_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


class KnowledgeGraphError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise KnowledgeGraphError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(prefix: str, *parts: str, length: int = 24) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _ascii_fold(value: str) -> str:
    return "".join(
        char for char in unicodedata.normalize("NFKD", value) if not unicodedata.combining(char)
    )


def normalize_alias(value: str) -> str:
    folded = _ascii_fold(_clean(value)).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", folded))


def slugify(value: str) -> str:
    normalized = normalize_alias(value).replace(" ", "-")
    _require(bool(normalized), "entity name cannot produce an empty slug")
    return normalized


def ensure_knowledge_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(KNOWLEDGE_SCHEMA.read_text(encoding="utf-8"))
    conn.commit()


def _normalize_provenance(provenance: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw in provenance:
        _require(isinstance(raw, dict), "provenance entries must be objects")
        item = {key: _clean(raw.get(key)) for key in PROVENANCE_KEYS}
        _require(all(item.values()), "provenance requires source_url, evidence_fingerprint and observed_at")
        _require(item["source_url"].startswith(("https://", "http://")), "provenance source_url must be HTTP(S)")
        _require(len(item["evidence_fingerprint"]) >= 16, "evidence fingerprint is too short")
        if raw.get("source_kind") is not None:
            item["source_kind"] = _clean(raw.get("source_kind"))
        if raw.get("note") is not None:
            item["note"] = _clean(raw.get("note"))
        normalized.append(item)
    _require(bool(normalized), "provenance is mandatory")
    unique = {json.dumps(item, ensure_ascii=False, sort_keys=True): item for item in normalized}
    return [unique[key] for key in sorted(unique)]


def _decode_entity(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["attributes"] = json.loads(value.pop("attributes_json"))
    value["provenance"] = json.loads(value.pop("provenance_json"))
    value["is_public"] = bool(value["is_public"])
    return value


def _decode_edge(row: sqlite3.Row) -> dict[str, Any]:
    value = dict(row)
    value["attributes"] = json.loads(value.pop("attributes_json"))
    value["provenance"] = json.loads(value.pop("provenance_json"))
    return value


def get_entity(conn: sqlite3.Connection, *, instance_id: str, entity_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM knowledge_entities WHERE instance_id=? AND entity_id=?",
        (instance_id, entity_id),
    ).fetchone()
    if row is None:
        raise KnowledgeGraphError("entity not found for instance")
    return _decode_entity(row)


def list_entities(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_type: str | None = None,
    public_only: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(1000, int(limit)))
    clauses = ["instance_id=?"]
    values: list[Any] = [instance_id]
    if entity_type:
        wanted = _clean(entity_type).upper()
        _require(wanted in ENTITY_TYPES, "unsupported entity type")
        clauses.append("entity_type=?")
        values.append(wanted)
    if public_only:
        clauses.extend(["is_public=1", "evidence_status='EVIDENCE_BACKED'"])
    values.append(bounded)
    rows = conn.execute(
        f"SELECT * FROM knowledge_entities WHERE {' AND '.join(clauses)} ORDER BY canonical_name, entity_id LIMIT ?",
        values,
    ).fetchall()
    return [_decode_entity(row) for row in rows]


def upsert_entity(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_type: str,
    canonical_name: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    summary: str = "",
    attributes: dict[str, Any] | None = None,
    evidence_status: str = "EVIDENCE_BACKED",
    is_public: bool = False,
    entity_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    kind = _clean(entity_type).upper()
    status = _clean(evidence_status).upper()
    name = _clean(canonical_name)
    _require(kind in ENTITY_TYPES, "unsupported entity type")
    _require(status in EVIDENCE_STATUSES, "unsupported evidence status")
    _require(bool(name), "canonical entity name is required")
    _require(not is_public or status == "EVIDENCE_BACKED", "public profiles require evidence-backed entities")
    sources = _normalize_provenance(provenance)
    slug = slugify(name)
    attrs = dict(attributes or {})
    identity_key = f"{kind}:{slug}"
    chosen_id = _clean(entity_id) or _hash_id("ent", instance_id, identity_key)
    fingerprint = _stable_hash(
        {
            "instance_id": instance_id,
            "entity_type": kind,
            "canonical_name": name,
            "summary": _clean(summary),
            "attributes": attrs,
            "evidence_status": status,
            "provenance": sources,
            "is_public": bool(is_public),
        }
    )
    existing = conn.execute(
        "SELECT * FROM knowledge_entities WHERE instance_id=? AND entity_type=? AND slug=?",
        (instance_id, kind, slug),
    ).fetchone()
    now = utc_now()
    if existing is not None:
        current = _decode_entity(existing)
        _require(
            normalize_alias(current["canonical_name"]) == normalize_alias(name),
            "entity slug collision requires explicit identity resolution",
        )
        changed = current["fingerprint"] != fingerprint
        if changed:
            conn.execute(
                """
                UPDATE knowledge_entities
                SET canonical_name=?, summary=?, attributes_json=?, evidence_status=?, provenance_json=?,
                    is_public=?, fingerprint=?, updated_at=?
                WHERE instance_id=? AND entity_id=?
                """,
                (
                    name,
                    _clean(summary),
                    json.dumps(attrs, ensure_ascii=False, sort_keys=True),
                    status,
                    json.dumps(sources, ensure_ascii=False, sort_keys=True),
                    1 if is_public else 0,
                    fingerprint,
                    now,
                    instance_id,
                    current["entity_id"],
                ),
            )
            conn.execute(
                """
                INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
                VALUES (?,'knowledge_entity',?,'KNOWLEDGE_ENTITY_UPSERTED','evidence-bound entity updated',?,?,?)
                """,
                (
                    current["entity_id"],
                    json.dumps({"entity_type": kind, "fingerprint": fingerprint}, sort_keys=True),
                    engine_version,
                    now,
                ),
            )
            conn.commit()
        return get_entity(conn, instance_id=instance_id, entity_id=current["entity_id"]), changed
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO knowledge_entities(
                instance_id,entity_id,entity_type,canonical_name,slug,summary,attributes_json,
                evidence_status,provenance_json,is_public,fingerprint,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                instance_id,
                chosen_id,
                kind,
                name,
                slug,
                _clean(summary),
                json.dumps(attrs, ensure_ascii=False, sort_keys=True),
                status,
                json.dumps(sources, ensure_ascii=False, sort_keys=True),
                1 if is_public else 0,
                fingerprint,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
            VALUES (?,'knowledge_entity',?,'KNOWLEDGE_ENTITY_UPSERTED','evidence-bound entity created',?,?,?)
            """,
            (
                instance_id,
                chosen_id,
                json.dumps({"entity_type": kind, "fingerprint": fingerprint}, sort_keys=True),
                engine_version,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_entity(conn, instance_id=instance_id, entity_id=chosen_id), True


def add_alias(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_id: str,
    alias: str,
    provenance: Iterable[dict[str, Any]],
) -> bool:
    ensure_knowledge_schema(conn)
    get_entity(conn, instance_id=instance_id, entity_id=entity_id)
    raw = _clean(alias)
    normalized = normalize_alias(raw)
    _require(bool(normalized), "alias is required")
    sources = _normalize_provenance(provenance)
    existing = conn.execute(
        "SELECT entity_id FROM knowledge_aliases WHERE instance_id=? AND normalized_alias=?",
        (instance_id, normalized),
    ).fetchone()
    if existing is not None:
        _require(existing["entity_id"] == entity_id, "ambiguous alias cannot be auto-merged")
        return False
    conn.execute(
        "INSERT INTO knowledge_aliases(instance_id,normalized_alias,entity_id,alias,provenance_json,created_at) VALUES (?,?,?,?,?,?)",
        (instance_id, normalized, entity_id, raw, json.dumps(sources, ensure_ascii=False, sort_keys=True), utc_now()),
    )
    conn.commit()
    return True


def resolve_alias(conn: sqlite3.Connection, *, instance_id: str, alias: str) -> dict[str, Any] | None:
    normalized = normalize_alias(alias)
    if not normalized:
        return None
    row = conn.execute(
        "SELECT entity_id FROM knowledge_aliases WHERE instance_id=? AND normalized_alias=?",
        (instance_id, normalized),
    ).fetchone()
    return get_entity(conn, instance_id=instance_id, entity_id=row["entity_id"]) if row else None


def record_edge(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str,
    relation_basis: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    attributes: dict[str, Any] | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    subject = get_entity(conn, instance_id=instance_id, entity_id=subject_entity_id)
    target = get_entity(conn, instance_id=instance_id, entity_id=object_entity_id)
    _require(subject["entity_id"] != target["entity_id"], "self-relations require an explicit domain-specific model")
    relation = _clean(predicate).upper()
    basis = _clean(relation_basis).upper()
    _require(bool(TOKEN_RE.fullmatch(relation)), "predicate must be an explicit normalized token")
    _require(basis in RELATION_BASES, "unsupported relation evidence basis")
    sources = _normalize_provenance(provenance)
    attrs = dict(attributes or {})
    edge_id = _hash_id(
        "edge",
        instance_id,
        subject_entity_id,
        relation,
        object_entity_id,
        _clean(valid_from),
        _clean(valid_to),
    )
    fingerprint = _stable_hash(
        {
            "subject": subject_entity_id,
            "predicate": relation,
            "object": object_entity_id,
            "relation_basis": basis,
            "attributes": attrs,
            "valid_from": _clean(valid_from),
            "valid_to": _clean(valid_to),
            "provenance": sources,
        }
    )
    existing = conn.execute(
        "SELECT * FROM knowledge_edges WHERE instance_id=? AND edge_id=?",
        (instance_id, edge_id),
    ).fetchone()
    now = utc_now()
    if existing is not None:
        current = _decode_edge(existing)
        changed = current["fingerprint"] != fingerprint
        if changed:
            conn.execute(
                """
                UPDATE knowledge_edges SET relation_basis=?,attributes_json=?,provenance_json=?,fingerprint=?,updated_at=?
                WHERE instance_id=? AND edge_id=?
                """,
                (
                    basis,
                    json.dumps(attrs, ensure_ascii=False, sort_keys=True),
                    json.dumps(sources, ensure_ascii=False, sort_keys=True),
                    fingerprint,
                    now,
                    instance_id,
                    edge_id,
                ),
            )
            conn.commit()
        return _decode_edge(
            conn.execute("SELECT * FROM knowledge_edges WHERE instance_id=? AND edge_id=?", (instance_id, edge_id)).fetchone()
        ), changed
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO knowledge_edges(
                instance_id,edge_id,subject_entity_id,predicate,object_entity_id,relation_basis,
                attributes_json,provenance_json,valid_from,valid_to,fingerprint,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                instance_id,
                edge_id,
                subject_entity_id,
                relation,
                object_entity_id,
                basis,
                json.dumps(attrs, ensure_ascii=False, sort_keys=True),
                json.dumps(sources, ensure_ascii=False, sort_keys=True),
                _clean(valid_from) or None,
                _clean(valid_to) or None,
                fingerprint,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
            VALUES (?,'knowledge_edge',?,'KNOWLEDGE_EDGE_UPSERTED','documented relation recorded',?,?,?)
            """,
            (
                instance_id,
                edge_id,
                json.dumps({"subject": subject_entity_id, "predicate": relation, "object": object_entity_id}, sort_keys=True),
                engine_version,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    row = conn.execute("SELECT * FROM knowledge_edges WHERE instance_id=? AND edge_id=?", (instance_id, edge_id)).fetchone()
    return _decode_edge(row), True


def bind_published_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    entity_id: str,
    role: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
) -> bool:
    ensure_knowledge_schema(conn)
    entity = get_entity(conn, instance_id=instance_id, entity_id=entity_id)
    _require(entity["evidence_status"] == "EVIDENCE_BACKED", "story links require evidence-backed entities")
    relation_role = _clean(role).upper()
    _require(bool(TOKEN_RE.fullmatch(relation_role)), "story entity role must be an explicit normalized token")
    try:
        published = conn.execute(
            "SELECT publication_id FROM story_publications WHERE instance_id=? AND story_id=?",
            (instance_id, story_id),
        ).fetchone()
    except sqlite3.OperationalError as exc:
        raise KnowledgeGraphError("site publication schema is required before story enrichment") from exc
    _require(published is not None, "story-to-entity enrichment requires a published story")
    sources = _normalize_provenance(provenance)
    fingerprint = _stable_hash(
        {"instance_id": instance_id, "story_id": story_id, "entity_id": entity_id, "role": relation_role, "provenance": sources}
    )
    existing = conn.execute(
        "SELECT fingerprint FROM story_entity_links WHERE instance_id=? AND story_id=? AND entity_id=? AND role=?",
        (instance_id, story_id, entity_id, relation_role),
    ).fetchone()
    if existing is not None:
        _require(existing["fingerprint"] == fingerprint, "story link evidence changed; create a reviewed revision instead")
        return False
    now = utc_now()
    conn.execute(
        "INSERT INTO story_entity_links(instance_id,story_id,entity_id,role,provenance_json,fingerprint,created_at) VALUES (?,?,?,?,?,?,?)",
        (instance_id, story_id, entity_id, relation_role, json.dumps(sources, ensure_ascii=False, sort_keys=True), fingerprint, now),
    )
    conn.execute(
        """
        INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
        VALUES (?,'story',?,'KNOWLEDGE_STORY_LINKED','published story enriched with evidence-backed entity',?,?,?)
        """,
        (instance_id, story_id, json.dumps({"entity_id": entity_id, "role": relation_role}, sort_keys=True), engine_version, now),
    )
    conn.commit()
    return True


def record_public_money(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    payer_entity_id: str,
    beneficiary_entity_id: str,
    amount_minor: int,
    currency: str,
    purpose: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    project_entity_id: str | None = None,
    event_entity_id: str | None = None,
    document_entity_id: str | None = None,
    story_id: str | None = None,
    effective_date: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    payer = get_entity(conn, instance_id=instance_id, entity_id=payer_entity_id)
    beneficiary = get_entity(conn, instance_id=instance_id, entity_id=beneficiary_entity_id)
    _require(payer["evidence_status"] == beneficiary["evidence_status"] == "EVIDENCE_BACKED", "public-money parties must be evidence-backed")
    for optional_id in (project_entity_id, event_entity_id, document_entity_id):
        if optional_id:
            get_entity(conn, instance_id=instance_id, entity_id=optional_id)
    if story_id:
        row = conn.execute("SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (instance_id, story_id)).fetchone()
        _require(row is not None, "public-money story is not part of the instance")
    _require(isinstance(amount_minor, int) and not isinstance(amount_minor, bool) and amount_minor >= 0, "amount_minor must be a non-negative integer")
    code = _clean(currency).upper()
    _require(bool(CURRENCY_RE.fullmatch(code)), "currency must be an ISO-like three-letter code")
    why = _clean(purpose)
    _require(bool(why), "public-money purpose is required")
    sources = _normalize_provenance(provenance)
    attrs = dict(attributes or {})
    money_item_id = _hash_id(
        "money",
        instance_id,
        payer_entity_id,
        beneficiary_entity_id,
        str(amount_minor),
        code,
        why,
        _clean(effective_date),
        _clean(project_entity_id),
        _clean(event_entity_id),
        _clean(document_entity_id),
    )
    fingerprint = _stable_hash(
        {
            "payer": payer_entity_id,
            "beneficiary": beneficiary_entity_id,
            "amount_minor": amount_minor,
            "currency": code,
            "purpose": why,
            "project": project_entity_id,
            "event": event_entity_id,
            "document": document_entity_id,
            "story_id": story_id,
            "effective_date": _clean(effective_date),
            "attributes": attrs,
            "provenance": sources,
        }
    )
    existing = conn.execute(
        "SELECT * FROM public_money_items WHERE instance_id=? AND money_item_id=?",
        (instance_id, money_item_id),
    ).fetchone()
    if existing is not None:
        _require(existing["fingerprint"] == fingerprint, "public-money evidence changed; create a reviewed record revision")
        value = dict(existing)
        value["attributes"] = json.loads(value.pop("attributes_json"))
        value["provenance"] = json.loads(value.pop("provenance_json"))
        return value, False
    now = utc_now()
    conn.execute(
        """
        INSERT INTO public_money_items(
            instance_id,money_item_id,payer_entity_id,beneficiary_entity_id,amount_minor,currency,purpose,
            project_entity_id,event_entity_id,document_entity_id,story_id,effective_date,attributes_json,
            provenance_json,fingerprint,created_at,updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            instance_id,
            money_item_id,
            payer_entity_id,
            beneficiary_entity_id,
            amount_minor,
            code,
            why,
            project_entity_id,
            event_entity_id,
            document_entity_id,
            story_id,
            _clean(effective_date) or None,
            json.dumps(attrs, ensure_ascii=False, sort_keys=True),
            json.dumps(sources, ensure_ascii=False, sort_keys=True),
            fingerprint,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
        VALUES (?,'public_money',?,'PUBLIC_MONEY_RECORDED','evidence-bound public-money item recorded',?,?,?)
        """,
        (
            instance_id,
            money_item_id,
            json.dumps({"payer": payer_entity_id, "beneficiary": beneficiary_entity_id, "amount_minor": amount_minor, "currency": code}, sort_keys=True),
            engine_version,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM public_money_items WHERE instance_id=? AND money_item_id=?", (instance_id, money_item_id)).fetchone()
    value = dict(row)
    value["attributes"] = json.loads(value.pop("attributes_json"))
    value["provenance"] = json.loads(value.pop("provenance_json"))
    return value, True


def record_timeline_event(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_id: str,
    event_date: str,
    event_kind: str,
    title: str,
    provenance: Iterable[dict[str, Any]],
    engine_version: str,
    summary: str = "",
    story_id: str | None = None,
) -> tuple[dict[str, Any], bool]:
    ensure_knowledge_schema(conn)
    get_entity(conn, instance_id=instance_id, entity_id=entity_id)
    date = _clean(event_date)
    kind = _clean(event_kind).upper()
    heading = _clean(title)
    _require(bool(date) and len(date) >= 4, "timeline event date is required")
    _require(bool(TOKEN_RE.fullmatch(kind)), "timeline event kind must be normalized")
    _require(bool(heading), "timeline title is required")
    if story_id:
        row = conn.execute("SELECT 1 FROM stories WHERE instance_id=? AND story_id=?", (instance_id, story_id)).fetchone()
        _require(row is not None, "timeline story is not part of the instance")
    sources = _normalize_provenance(provenance)
    event_id = _hash_id("time", instance_id, entity_id, date, kind, heading)
    fingerprint = _stable_hash(
        {"entity_id": entity_id, "event_date": date, "event_kind": kind, "title": heading, "summary": _clean(summary), "story_id": story_id, "provenance": sources}
    )
    existing = conn.execute(
        "SELECT * FROM knowledge_timeline_events WHERE instance_id=? AND timeline_event_id=?",
        (instance_id, event_id),
    ).fetchone()
    if existing is not None:
        _require(existing["fingerprint"] == fingerprint, "timeline evidence changed; create a reviewed revision")
        value = dict(existing)
        value["provenance"] = json.loads(value.pop("provenance_json"))
        return value, False
    now = utc_now()
    conn.execute(
        """
        INSERT INTO knowledge_timeline_events(
            instance_id,timeline_event_id,entity_id,event_date,event_kind,title,summary,story_id,
            provenance_json,fingerprint,created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """,
        (instance_id, event_id, entity_id, date, kind, heading, _clean(summary), story_id, json.dumps(sources, ensure_ascii=False, sort_keys=True), fingerprint, now),
    )
    conn.execute(
        """
        INSERT INTO runtime_events(instance_id,aggregate_type,aggregate_id,event_type,reason,payload_json,engine_version,created_at)
        VALUES (?,'knowledge_entity',?,'KNOWLEDGE_TIMELINE_RECORDED','evidence-bound timeline item recorded',?,?,?)
        """,
        (instance_id, entity_id, json.dumps({"timeline_event_id": event_id, "event_date": date, "event_kind": kind}, sort_keys=True), engine_version, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM knowledge_timeline_events WHERE instance_id=? AND timeline_event_id=?", (instance_id, event_id)).fetchone()
    value = dict(row)
    value["provenance"] = json.loads(value.pop("provenance_json"))
    return value, True


def profile_path(entity: dict[str, Any], *, prefix: str = "/profiles") -> str:
    root = "/" + prefix.strip("/")
    return f"{root}/{quote(str(entity['entity_type']).lower(), safe='')}/{quote(str(entity['slug']), safe='-._~')}/"


def _public_entity(conn: sqlite3.Connection, *, instance_id: str, entity_id: str) -> dict[str, Any]:
    entity = get_entity(conn, instance_id=instance_id, entity_id=entity_id)
    _require(entity["is_public"] and entity["evidence_status"] == "EVIDENCE_BACKED", "entity is not eligible for public profile projection")
    return entity


def get_public_entity_by_path(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    entity_type: str,
    slug: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM knowledge_entities
        WHERE instance_id=? AND entity_type=? AND slug=? AND is_public=1 AND evidence_status='EVIDENCE_BACKED'
        """,
        (instance_id, _clean(entity_type).upper(), _clean(slug)),
    ).fetchone()
    return _decode_entity(row) if row is not None else None


def project_public_profile(conn: sqlite3.Connection, *, instance_id: str, entity_id: str) -> dict[str, Any]:
    ensure_knowledge_schema(conn)
    entity = _public_entity(conn, instance_id=instance_id, entity_id=entity_id)
    aliases = [
        dict(row)
        for row in conn.execute(
            "SELECT alias, created_at FROM knowledge_aliases WHERE instance_id=? AND entity_id=? ORDER BY alias",
            (instance_id, entity_id),
        ).fetchall()
    ]
    edge_rows = conn.execute(
        """
        SELECT e.*, s.canonical_name AS subject_name, o.canonical_name AS object_name
        FROM knowledge_edges e
        JOIN knowledge_entities s ON s.instance_id=e.instance_id AND s.entity_id=e.subject_entity_id
        JOIN knowledge_entities o ON o.instance_id=e.instance_id AND o.entity_id=e.object_entity_id
        WHERE e.instance_id=? AND (e.subject_entity_id=? OR e.object_entity_id=?)
          AND s.evidence_status='EVIDENCE_BACKED' AND s.is_public=1
          AND o.evidence_status='EVIDENCE_BACKED' AND o.is_public=1
        ORDER BY e.predicate, e.edge_id
        """,
        (instance_id, entity_id, entity_id),
    ).fetchall()
    edges = []
    for row in edge_rows:
        value = dict(row)
        value["attributes"] = json.loads(value.pop("attributes_json"))
        value["provenance"] = json.loads(value.pop("provenance_json"))
        edges.append(value)
    timeline = []
    for row in conn.execute(
        "SELECT * FROM knowledge_timeline_events WHERE instance_id=? AND entity_id=? ORDER BY event_date DESC, timeline_event_id",
        (instance_id, entity_id),
    ).fetchall():
        value = dict(row)
        value["provenance"] = json.loads(value.pop("provenance_json"))
        timeline.append(value)
    money = []
    for row in conn.execute(
        """
        SELECT * FROM public_money_items
        WHERE instance_id=? AND (payer_entity_id=? OR beneficiary_entity_id=?)
        ORDER BY COALESCE(effective_date,'' ) DESC, money_item_id
        """,
        (instance_id, entity_id, entity_id),
    ).fetchall():
        value = dict(row)
        value["attributes"] = json.loads(value.pop("attributes_json"))
        value["provenance"] = json.loads(value.pop("provenance_json"))
        money.append(value)
    story_links = [
        dict(row)
        for row in conn.execute(
            """
            SELECT l.story_id,l.role,l.created_at,p.canonical_path,p.published_at
            FROM story_entity_links l
            JOIN story_publications p ON p.instance_id=l.instance_id AND p.story_id=l.story_id
            WHERE l.instance_id=? AND l.entity_id=?
            ORDER BY p.published_at DESC,l.story_id
            """,
            (instance_id, entity_id),
        ).fetchall()
    ]
    return {
        "entity": entity,
        "canonical_path": profile_path(entity),
        "aliases": aliases,
        "relations": edges,
        "timeline": timeline,
        "public_money": money,
        "stories": story_links,
    }


def _manifest(instance_id: str, domain: str, marker: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _source(label: str) -> list[dict[str, str]]:
    return [
        {
            "source_url": f"https://example.invalid/evidence/{label}",
            "evidence_fingerprint": hashlib.sha256(label.encode("utf-8")).hexdigest(),
            "observed_at": "2026-08-19T12:00:00Z",
            "source_kind": "PRIMARY",
        }
    ]


def self_test() -> None:
    from site_publication import ensure_publication_schema

    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_knowledge_schema(conn)
        engine = "vnext-p12-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b"), engine_version=engine)

        try:
            upsert_entity(
                conn,
                instance_id="alpha-local",
                entity_type="PERSON",
                canonical_name="Candidate Person",
                provenance=_source("candidate"),
                engine_version=engine,
                evidence_status="CANDIDATE",
                is_public=True,
            )
        except KnowledgeGraphError:
            pass
        else:
            raise AssertionError("candidate entity was exposed publicly")

        person, created = upsert_entity(
            conn,
            instance_id="alpha-local",
            entity_type="PERSON",
            canonical_name="Alex Example",
            provenance=_source("person"),
            engine_version=engine,
            summary="Evidence-backed public person.",
            attributes={"occupation": "Example role"},
            is_public=True,
        )
        assert created and person["is_public"]
        artist, _ = upsert_entity(
            conn,
            instance_id="alpha-local",
            entity_type="ARTIST",
            canonical_name="Dana Example",
            provenance=_source("artist"),
            engine_version=engine,
            is_public=True,
        )
        institution, _ = upsert_entity(
            conn,
            instance_id="alpha-local",
            entity_type="INSTITUTION",
            canonical_name="Example Authority",
            provenance=_source("authority"),
            engine_version=engine,
            is_public=True,
        )
        company, _ = upsert_entity(
            conn,
            instance_id="alpha-local",
            entity_type="COMPANY",
            canonical_name="Example Operator",
            provenance=_source("operator"),
            engine_version=engine,
            is_public=True,
        )
        beta_person, _ = upsert_entity(
            conn,
            instance_id="beta-local",
            entity_type="PERSON",
            canonical_name="Alex Example",
            provenance=_source("beta-person"),
            engine_version=engine,
            is_public=True,
        )
        assert person["entity_id"] != beta_person["entity_id"]
        assert add_alias(conn, instance_id="alpha-local", entity_id=person["entity_id"], alias="A. Example", provenance=_source("alias"))
        assert resolve_alias(conn, instance_id="alpha-local", alias="A Example")["entity_id"] == person["entity_id"]
        assert resolve_alias(conn, instance_id="beta-local", alias="A Example") is None
        try:
            add_alias(conn, instance_id="alpha-local", entity_id=artist["entity_id"], alias="A. Example", provenance=_source("alias-ambiguous"))
        except KnowledgeGraphError:
            pass
        else:
            raise AssertionError("ambiguous alias auto-merged")

        edge, edge_created = record_edge(
            conn,
            instance_id="alpha-local",
            subject_entity_id=person["entity_id"],
            predicate="WORKS_WITH",
            object_entity_id=institution["entity_id"],
            relation_basis="DOCUMENTED_SOURCE",
            provenance=_source("edge"),
            engine_version=engine,
        )
        assert edge_created and edge["predicate"] == "WORKS_WITH"
        try:
            record_edge(
                conn,
                instance_id="alpha-local",
                subject_entity_id=person["entity_id"],
                predicate="WORKS_WITH",
                object_entity_id=beta_person["entity_id"],
                relation_basis="DOCUMENTED_SOURCE",
                provenance=_source("cross-instance"),
                engine_version=engine,
            )
        except KnowledgeGraphError:
            pass
        else:
            raise AssertionError("cross-instance relation was accepted")

        money, money_created = record_public_money(
            conn,
            instance_id="alpha-local",
            payer_entity_id=institution["entity_id"],
            beneficiary_entity_id=company["entity_id"],
            amount_minor=1250000,
            currency="EUR",
            purpose="Documented project support",
            provenance=_source("money"),
            engine_version=engine,
            effective_date="2026-08-19",
        )
        assert money_created and money["amount_minor"] == 1250000
        timeline, timeline_created = record_timeline_event(
            conn,
            instance_id="alpha-local",
            entity_id=artist["entity_id"],
            event_date="2026-08-19",
            event_kind="APPEARANCE",
            title="Documented appearance",
            provenance=_source("timeline"),
            engine_version=engine,
        )
        assert timeline_created and timeline["event_kind"] == "APPEARANCE"

        create_story(
            conn,
            instance_id="alpha-local",
            story_id="published-story",
            fingerprint="published-story-fingerprint",
            engine_version=engine,
            headline="Published story",
        )
        conn.execute(
            "UPDATE stories SET state='PUBLISHED',canonical_path='/story/published-story/' WHERE instance_id='alpha-local' AND story_id='published-story'"
        )
        now = utc_now()
        conn.execute(
            """
            INSERT INTO story_publications(instance_id,story_id,publication_id,canonical_path,current_revision,current_content_fingerprint,published_at,updated_at)
            VALUES ('alpha-local','published-story','pub-test','/story/published-story/',1,'content-test',?,?)
            """,
            (now, now),
        )
        conn.commit()
        assert bind_published_story(
            conn,
            instance_id="alpha-local",
            story_id="published-story",
            entity_id=person["entity_id"],
            role="SUBJECT",
            provenance=_source("story-link"),
            engine_version=engine,
        )
        profile = project_public_profile(conn, instance_id="alpha-local", entity_id=person["entity_id"])
        assert profile["entity"]["canonical_name"] == "Alex Example"
        assert profile["stories"][0]["canonical_path"] == "/story/published-story/"
        assert any(item["predicate"] == "WORKS_WITH" for item in profile["relations"])
        beta_profile = project_public_profile(conn, instance_id="beta-local", entity_id=beta_person["entity_id"])
        assert beta_profile["stories"] == [] and beta_profile["relations"] == []
        assert profile_path(person).startswith("/profiles/person/")

        event_types = {
            row["event_type"]
            for row in conn.execute("SELECT event_type FROM runtime_events WHERE instance_id='alpha-local'").fetchall()
        }
        assert {
            "KNOWLEDGE_ENTITY_UPSERTED",
            "KNOWLEDGE_EDGE_UPSERTED",
            "KNOWLEDGE_STORY_LINKED",
            "PUBLIC_MONEY_RECORDED",
            "KNOWLEDGE_TIMELINE_RECORDED",
        }.issubset(event_types)
        conn.close()
    print("VNEXT_KNOWLEDGE_GRAPH_SELF_TEST_PASS")


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
