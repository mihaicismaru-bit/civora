#!/usr/bin/env python3
"""Site-owned Dynamic Primary Resolver for LOCAL NEWS OS vNext.

The resolver converts non-authoritative signal claim/entity hints into durable
verification tasks, registers curated primary sources from an instance source
pack, accepts dynamically discovered primary-target candidates, and routes
verification tasks only to validated targets. It never grants publication
authority and performs no repository-runtime writes or network transport.
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
from urllib.parse import urlparse

from runtime_store import connect, initialize, register_instance, utc_now
from signal_engine import get_signal, materialize_source_item
from source_adapters import SourceDefinition, SourceItem

PUBLICATION_AUTHORITY = "NONE"
TASK_STATES = {"PENDING", "TARGETS_READY", "NEEDS_DISCOVERY"}
TARGET_STATUSES = {"CANDIDATE", "VALIDATED", "DISABLED"}
TARGET_ORIGINS = {"SOURCE_PACK", "DYNAMIC_DISCOVERY"}
MAX_TERMS = 32


class PrimaryResolverError(RuntimeError):
    pass


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _terms(values: Iterable[Any]) -> tuple[str, ...]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value).casefold()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
        if len(output) >= MAX_TERMS:
            break
    return tuple(output)


def _verification_config(source: SourceDefinition) -> dict[str, Any]:
    raw = source.config.get("verification", {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise PrimaryResolverError("source config.verification must be an object")
    return raw


def _target_metadata(source: SourceDefinition) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    cfg = _verification_config(source)
    authority_class = _clean_text(cfg.get("authority_class")) or "PRIMARY_SOURCE"
    match_terms_raw = cfg.get("match_terms", [])
    claim_kinds_raw = cfg.get("claim_kinds", [])
    if not isinstance(match_terms_raw, list) or not isinstance(claim_kinds_raw, list):
        raise PrimaryResolverError("verification match_terms/claim_kinds must be arrays")
    return authority_class, _terms(match_terms_raw), tuple(x.upper() for x in _terms(claim_kinds_raw))


def _append_event(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    engine_version: str,
    from_state: str | None = None,
    to_state: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_events(
            instance_id, aggregate_type, aggregate_id, event_type,
            from_state, to_state, reason, payload_json, engine_version, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            instance_id,
            aggregate_type,
            aggregate_id,
            event_type,
            from_state,
            to_state,
            reason,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            engine_version,
            utc_now(),
        ),
    )


def register_source_pack_primary_targets(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    sources: Iterable[SourceDefinition],
    engine_version: str,
) -> list[dict[str, Any]]:
    """Register PRIMARY/BOTH source-pack entries as already curated targets."""
    targets: list[dict[str, Any]] = []
    for source in sources:
        if not source.enabled or source.role not in {"PRIMARY", "BOTH"}:
            continue
        authority_class, match_terms, claim_kinds = _target_metadata(source)
        target_id = _hash_id(instance_id, source.source_id, source.url)
        now = utc_now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM primary_targets WHERE instance_id=? AND target_id=?",
                (instance_id, target_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO primary_targets(
                        instance_id, target_id, source_id, url, intended_role,
                        origin, status, authority_class, match_terms_json,
                        claim_kinds_json, confidence, publication_authority,
                        validation_evidence_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'PRIMARY', 'SOURCE_PACK', 'VALIDATED', ?, ?, ?,
                              100, 'NONE', ?, ?, ?)
                    """,
                    (
                        instance_id,
                        target_id,
                        source.source_id,
                        source.url,
                        authority_class,
                        json.dumps(list(match_terms), ensure_ascii=False, sort_keys=True),
                        json.dumps(list(claim_kinds), ensure_ascii=False, sort_keys=True),
                        json.dumps(
                            {"source_pack_curated": True, "source_role": source.role},
                            sort_keys=True,
                        ),
                        now,
                        now,
                    ),
                )
                _append_event(
                    conn,
                    instance_id=instance_id,
                    aggregate_type="primary_target",
                    aggregate_id=target_id,
                    event_type="PRIMARY_TARGET_REGISTERED",
                    to_state="VALIDATED",
                    reason="curated source-pack primary target",
                    engine_version=engine_version,
                    payload={"source_id": source.source_id, "origin": "SOURCE_PACK"},
                )
            else:
                conn.execute(
                    """
                    UPDATE primary_targets
                    SET source_id=?, url=?, intended_role='PRIMARY', origin='SOURCE_PACK',
                        status='VALIDATED', authority_class=?, match_terms_json=?,
                        claim_kinds_json=?, confidence=100, publication_authority='NONE',
                        updated_at=?
                    WHERE instance_id=? AND target_id=?
                    """,
                    (
                        source.source_id,
                        source.url,
                        authority_class,
                        json.dumps(list(match_terms), ensure_ascii=False, sort_keys=True),
                        json.dumps(list(claim_kinds), ensure_ascii=False, sort_keys=True),
                        now,
                        instance_id,
                        target_id,
                    ),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        targets.append(get_primary_target(conn, instance_id=instance_id, target_id=target_id))
    return targets


def _discovery_request(signal: dict[str, Any], claim: dict[str, Any]) -> dict[str, Any]:
    entity_terms = [
        _clean_text(item.get("text"))
        for item in signal.get("entity_hints", [])
        if isinstance(item, dict) and _clean_text(item.get("text"))
    ]
    claim_text = _clean_text(claim.get("text"))
    query_terms = list(_terms([*entity_terms, claim_text]))
    return {
        "query_terms": query_terms,
        "claim_kind": _clean_text(claim.get("kind")).upper() or "UNCLASSIFIED",
        "required_role": "PRIMARY",
        "authority_required": True,
        "candidate_must_be_validated_before_routing": True,
    }


def materialize_verification_tasks(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str,
    engine_version: str,
) -> list[dict[str, Any]]:
    signal = get_signal(conn, instance_id=instance_id, signal_id=signal_id)
    if signal["publication_authority"] != "NONE":
        raise PrimaryResolverError("signal unexpectedly carries publication authority")
    if signal["material_fact_ready"] or signal["fact_kernel_ready"]:
        raise PrimaryResolverError("resolver accepts only pre-fact-kernel signals")

    claims = [
        item
        for item in signal.get("claim_hints", [])
        if isinstance(item, dict) and item.get("verification_required") is True
    ]
    if not claims:
        raise PrimaryResolverError("signal has no verifiable claim hints")
    entity_context = " | ".join(
        _clean_text(item.get("text"))
        for item in signal.get("entity_hints", [])
        if isinstance(item, dict) and _clean_text(item.get("text"))
    )
    output: list[dict[str, Any]] = []
    for claim in claims:
        claim_kind = _clean_text(claim.get("kind")).upper() or "UNCLASSIFIED"
        claim_text = _clean_text(claim.get("text"))
        if not claim_text:
            continue
        claim_key = hashlib.sha256(
            f"{claim_kind}\n{claim_text.casefold()}".encode("utf-8")
        ).hexdigest()
        task_id = _hash_id(instance_id, signal_id, claim_key)
        discovery = _discovery_request(signal, claim)
        now = utc_now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM verification_tasks WHERE instance_id=? AND task_id=?",
                (instance_id, task_id),
            ).fetchone()
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO verification_tasks(
                        instance_id, task_id, signal_id, claim_key, claim_kind,
                        claim_text, entity_context, state, required_role,
                        discovery_request_json, publication_authority,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 'PRIMARY', ?, 'NONE', ?, ?)
                    """,
                    (
                        instance_id,
                        task_id,
                        signal_id,
                        claim_key,
                        claim_kind,
                        claim_text,
                        entity_context,
                        json.dumps(discovery, ensure_ascii=False, sort_keys=True),
                        now,
                        now,
                    ),
                )
                _append_event(
                    conn,
                    instance_id=instance_id,
                    aggregate_type="verification_task",
                    aggregate_id=task_id,
                    event_type="VERIFICATION_TASK_CREATED",
                    to_state="PENDING",
                    reason="signal claim requires primary evidence",
                    engine_version=engine_version,
                    payload={"signal_id": signal_id, "claim_kind": claim_kind},
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        output.append(get_verification_task(conn, instance_id=instance_id, task_id=task_id))
    if not output:
        raise PrimaryResolverError("no verification tasks could be materialized")
    return output


def _decode_target_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["match_terms"] = json.loads(data.pop("match_terms_json"))
    data["claim_kinds"] = json.loads(data.pop("claim_kinds_json"))
    data["validation_evidence"] = json.loads(data.pop("validation_evidence_json"))
    return data


def _decode_task_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["discovery_request"] = json.loads(data.pop("discovery_request_json"))
    return data


def get_primary_target(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    target_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM primary_targets WHERE instance_id=? AND target_id=?",
        (instance_id, target_id),
    ).fetchone()
    if row is None:
        raise PrimaryResolverError("primary target not found for instance")
    return _decode_target_row(row)


def list_primary_targets(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    if status:
        rows = conn.execute(
            """
            SELECT * FROM primary_targets
            WHERE instance_id=? AND status=?
            ORDER BY updated_at DESC, target_id ASC LIMIT ?
            """,
            (instance_id, status, bounded),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM primary_targets
            WHERE instance_id=?
            ORDER BY updated_at DESC, target_id ASC LIMIT ?
            """,
            (instance_id, bounded),
        ).fetchall()
    return [_decode_target_row(row) for row in rows]


def get_verification_task(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    task_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM verification_tasks WHERE instance_id=? AND task_id=?",
        (instance_id, task_id),
    ).fetchone()
    if row is None:
        raise PrimaryResolverError("verification task not found for instance")
    data = _decode_task_row(row)
    candidates = conn.execute(
        """
        SELECT t.*, l.score, l.match_reason
        FROM verification_task_targets l
        JOIN primary_targets t
          ON t.instance_id=l.instance_id AND t.target_id=l.target_id
        WHERE l.instance_id=? AND l.task_id=?
        ORDER BY l.score DESC, l.target_id ASC
        """,
        (instance_id, task_id),
    ).fetchall()
    decoded: list[dict[str, Any]] = []
    for candidate in candidates:
        item = _decode_target_row(candidate)
        item["score"] = int(candidate["score"])
        item["match_reason"] = candidate["match_reason"]
        decoded.append(item)
    data["target_candidates"] = decoded
    return data


def list_verification_tasks(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    if state:
        rows = conn.execute(
            """
            SELECT task_id FROM verification_tasks
            WHERE instance_id=? AND state=?
            ORDER BY updated_at DESC, task_id ASC LIMIT ?
            """,
            (instance_id, state, bounded),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT task_id FROM verification_tasks
            WHERE instance_id=?
            ORDER BY updated_at DESC, task_id ASC LIMIT ?
            """,
            (instance_id, bounded),
        ).fetchall()
    return [
        get_verification_task(conn, instance_id=instance_id, task_id=str(row["task_id"]))
        for row in rows
    ]


def _target_score(task: dict[str, Any], target: dict[str, Any]) -> tuple[int, str] | None:
    if target["status"] != "VALIDATED" or target["publication_authority"] != "NONE":
        return None
    claim_kind = str(task["claim_kind"]).upper()
    target_claim_kinds = {str(x).upper() for x in target.get("claim_kinds", [])}
    if target_claim_kinds and claim_kind not in target_claim_kinds:
        return None
    score = 10
    reasons: list[str] = ["validated_primary"]
    if target_claim_kinds:
        score += 50
        reasons.append("claim_kind")
    else:
        score += 5
        reasons.append("generic_claim_scope")
    haystack = f"{task['claim_text']} {task.get('entity_context') or ''}".casefold()
    match_terms = [str(x).casefold() for x in target.get("match_terms", [])]
    if match_terms:
        matched = [term for term in match_terms if term and term in haystack]
        if not matched:
            return None
        score += min(30, 10 + 5 * len(matched))
        reasons.append("terms=" + ",".join(matched[:4]))
    else:
        score += 5
        reasons.append("generic_entity_scope")
    if target.get("origin") == "SOURCE_PACK":
        score += 5
        reasons.append("source_pack")
    return min(score, 100), ";".join(reasons)


def route_verification_task(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    task_id: str,
    engine_version: str,
) -> dict[str, Any]:
    task = get_verification_task(conn, instance_id=instance_id, task_id=task_id)
    if task["publication_authority"] != "NONE":
        raise PrimaryResolverError("verification task unexpectedly carries publication authority")
    targets = list_primary_targets(conn, instance_id=instance_id, status="VALIDATED", limit=500)
    matches: list[tuple[str, int, str]] = []
    for target in targets:
        scored = _target_score(task, target)
        if scored is not None:
            score, reason = scored
            if score >= 20:
                matches.append((str(target["target_id"]), score, reason))
    matches.sort(key=lambda item: (-item[1], item[0]))
    new_state = "TARGETS_READY" if matches else "NEEDS_DISCOVERY"
    old_state = str(task["state"])
    existing_ids = {
        str(row["target_id"])
        for row in conn.execute(
            "SELECT target_id FROM verification_task_targets WHERE instance_id=? AND task_id=?",
            (instance_id, task_id),
        ).fetchall()
    }
    new_ids = {item[0] for item in matches}
    changed = old_state != new_state or existing_ids != new_ids
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "DELETE FROM verification_task_targets WHERE instance_id=? AND task_id=?",
            (instance_id, task_id),
        )
        now = utc_now()
        for target_id, score, reason in matches:
            conn.execute(
                """
                INSERT INTO verification_task_targets(
                    instance_id, task_id, target_id, score, match_reason, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (instance_id, task_id, target_id, score, reason, now),
            )
        conn.execute(
            """
            UPDATE verification_tasks
            SET state=?, updated_at=?
            WHERE instance_id=? AND task_id=?
            """,
            (new_state, now, instance_id, task_id),
        )
        if changed:
            _append_event(
                conn,
                instance_id=instance_id,
                aggregate_type="verification_task",
                aggregate_id=task_id,
                event_type=(
                    "VERIFICATION_TARGETS_RESOLVED"
                    if matches
                    else "PRIMARY_TARGET_DISCOVERY_REQUIRED"
                ),
                from_state=old_state,
                to_state=new_state,
                reason=(
                    "validated primary targets matched"
                    if matches
                    else "no validated primary target matched"
                ),
                engine_version=engine_version,
                payload={
                    "target_ids": [item[0] for item in matches],
                    "discovery_request": task["discovery_request"],
                },
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_verification_task(conn, instance_id=instance_id, task_id=task_id)


def resolve_signal(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str,
    source_definitions: Iterable[SourceDefinition],
    engine_version: str,
) -> list[dict[str, Any]]:
    definitions = list(source_definitions)
    register_source_pack_primary_targets(
        conn,
        instance_id=instance_id,
        sources=definitions,
        engine_version=engine_version,
    )
    tasks = materialize_verification_tasks(
        conn,
        instance_id=instance_id,
        signal_id=signal_id,
        engine_version=engine_version,
    )
    return [
        route_verification_task(
            conn,
            instance_id=instance_id,
            task_id=str(task["task_id"]),
            engine_version=engine_version,
        )
        for task in tasks
    ]


def _validate_candidate_url(url: str) -> str:
    text = _clean_text(url)
    parsed = urlparse(text)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise PrimaryResolverError("dynamic target url must be absolute http(s)")
    if parsed.username or parsed.password:
        raise PrimaryResolverError("dynamic target url must not contain credentials")
    return text


def propose_dynamic_primary_target(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    url: str,
    engine_version: str,
    discovered_for_task_id: str,
    authority_class: str = "UNCLASSIFIED_PRIMARY",
    match_terms: Iterable[str] = (),
    claim_kinds: Iterable[str] = (),
) -> dict[str, Any]:
    get_verification_task(conn, instance_id=instance_id, task_id=discovered_for_task_id)
    clean_url = _validate_candidate_url(url)
    target_id = _hash_id(instance_id, "dynamic", clean_url)
    now = utc_now()
    terms = _terms(match_terms)
    kinds = tuple(x.upper() for x in _terms(claim_kinds))
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM primary_targets WHERE instance_id=? AND target_id=?",
            (instance_id, target_id),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO primary_targets(
                    instance_id, target_id, source_id, url, intended_role,
                    origin, status, authority_class, match_terms_json,
                    claim_kinds_json, confidence, publication_authority,
                    validation_evidence_json, created_at, updated_at
                ) VALUES (?, ?, NULL, ?, 'PRIMARY', 'DYNAMIC_DISCOVERY', 'CANDIDATE', ?, ?, ?,
                          0, 'NONE', '{}', ?, ?)
                """,
                (
                    instance_id,
                    target_id,
                    clean_url,
                    _clean_text(authority_class) or "UNCLASSIFIED_PRIMARY",
                    json.dumps(list(terms), ensure_ascii=False, sort_keys=True),
                    json.dumps(list(kinds), ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )
            _append_event(
                conn,
                instance_id=instance_id,
                aggregate_type="primary_target",
                aggregate_id=target_id,
                event_type="PRIMARY_TARGET_PROPOSED",
                to_state="CANDIDATE",
                reason="dynamic primary target discovery",
                engine_version=engine_version,
                payload={"task_id": discovered_for_task_id, "url": clean_url},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_primary_target(conn, instance_id=instance_id, target_id=target_id)


def validate_dynamic_primary_target(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    target_id: str,
    engine_version: str,
    validation_evidence: dict[str, Any],
    source_id: str | None = None,
) -> dict[str, Any]:
    target = get_primary_target(conn, instance_id=instance_id, target_id=target_id)
    if target["origin"] != "DYNAMIC_DISCOVERY":
        raise PrimaryResolverError("only dynamically discovered targets use this validation path")
    if target["status"] == "DISABLED":
        raise PrimaryResolverError("disabled target cannot be validated")
    if not isinstance(validation_evidence, dict):
        raise PrimaryResolverError("validation_evidence must be an object")
    if validation_evidence.get("authority_confirmed") is not True:
        raise PrimaryResolverError("authority_confirmed evidence is required")
    if validation_evidence.get("canonical_url_confirmed") is not True:
        raise PrimaryResolverError("canonical_url_confirmed evidence is required")
    clean_source_id = _clean_text(source_id) or None
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            UPDATE primary_targets
            SET source_id=?, status='VALIDATED', confidence=100,
                validation_evidence_json=?, updated_at=?
            WHERE instance_id=? AND target_id=?
            """,
            (
                clean_source_id,
                json.dumps(validation_evidence, ensure_ascii=False, sort_keys=True),
                now,
                instance_id,
                target_id,
            ),
        )
        if target["status"] != "VALIDATED":
            _append_event(
                conn,
                instance_id=instance_id,
                aggregate_type="primary_target",
                aggregate_id=target_id,
                event_type="PRIMARY_TARGET_VALIDATED",
                from_state=str(target["status"]),
                to_state="VALIDATED",
                reason="authority and canonical URL evidence passed",
                engine_version=engine_version,
                payload={"source_id": clean_source_id},
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_primary_target(conn, instance_id=instance_id, target_id=target_id)


def _manifest(instance_id: str, domain: str, config_sha: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": config_sha,
        "runtime": {
            "owner": "site_application",
            "repository_runtime_state_enabled": False,
        },
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "resolver.sqlite3"
        conn = connect(db)
        initialize(conn)
        engine = "vnext-primary-resolver-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a" * 64), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b" * 64), engine_version=engine)

        discovery = SourceDefinition.from_dict(
            {
                "source_id": "neutral-discovery",
                "adapter": "RSS_ATOM",
                "role": "DISCOVERY",
                "url": "https://news.example.test/feed.xml",
                "config": {},
            }
        )
        primary = SourceDefinition.from_dict(
            {
                "source_id": "neutral-primary",
                "adapter": "JSON_API",
                "role": "PRIMARY",
                "url": "https://authority.example.test/notices",
                "config": {
                    "item_path": "results",
                    "fields": {"id": "id", "url": "url", "title": "title"},
                    "verification": {
                        "authority_class": "OFFICIAL_REGISTER",
                        "claim_kinds": ["MONEY", "PERCENT"],
                        "match_terms": ["increase", "eur"],
                    },
                },
            }
        )
        item = SourceItem(
            source_id="neutral-discovery",
            external_id="1",
            url="https://news.example.test/story",
            title="City Board Approves 12.5% Increase Worth 20,000 EUR",
            summary="Decision dated 19.08.2026.",
            fingerprint="neutral-source-item",
        )
        alpha_signal, _ = materialize_source_item(
            conn,
            instance_id="alpha-local",
            source=discovery,
            item=item,
            engine_version=engine,
        )
        tasks = resolve_signal(
            conn,
            instance_id="alpha-local",
            signal_id=str(alpha_signal["signal_id"]),
            source_definitions=[discovery, primary],
            engine_version=engine,
        )
        assert tasks
        money = next(task for task in tasks if task["claim_kind"] == "MONEY")
        headline = next(task for task in tasks if task["claim_kind"] == "HEADLINE_ASSERTION")
        assert money["state"] == "TARGETS_READY"
        assert money["target_candidates"][0]["origin"] == "SOURCE_PACK"
        assert money["target_candidates"][0]["publication_authority"] == "NONE"
        assert headline["state"] == "NEEDS_DISCOVERY"
        assert headline["target_candidates"] == []
        assert headline["discovery_request"]["required_role"] == "PRIMARY"

        beta_signal, _ = materialize_source_item(
            conn,
            instance_id="beta-local",
            source=discovery,
            item=item,
            engine_version=engine,
        )
        beta_tasks = resolve_signal(
            conn,
            instance_id="beta-local",
            signal_id=str(beta_signal["signal_id"]),
            source_definitions=[discovery],
            engine_version=engine,
        )
        assert all(task["state"] == "NEEDS_DISCOVERY" for task in beta_tasks)
        assert list_primary_targets(conn, instance_id="beta-local") == []

        candidate = propose_dynamic_primary_target(
            conn,
            instance_id="alpha-local",
            url="https://records.example.test/decisions",
            engine_version=engine,
            discovered_for_task_id=str(headline["task_id"]),
            authority_class="OFFICIAL_DECISION_REGISTER",
            match_terms=["city board"],
            claim_kinds=["HEADLINE_ASSERTION"],
        )
        assert candidate["status"] == "CANDIDATE"
        still_unrouted = route_verification_task(
            conn,
            instance_id="alpha-local",
            task_id=str(headline["task_id"]),
            engine_version=engine,
        )
        assert still_unrouted["state"] == "NEEDS_DISCOVERY"

        try:
            validate_dynamic_primary_target(
                conn,
                instance_id="alpha-local",
                target_id=str(candidate["target_id"]),
                engine_version=engine,
                validation_evidence={"authority_confirmed": True},
            )
        except PrimaryResolverError:
            pass
        else:
            raise AssertionError("dynamic target accepted without canonical URL evidence")

        validated = validate_dynamic_primary_target(
            conn,
            instance_id="alpha-local",
            target_id=str(candidate["target_id"]),
            engine_version=engine,
            validation_evidence={
                "authority_confirmed": True,
                "canonical_url_confirmed": True,
                "evidence_type": "provider_readback",
            },
            source_id="dynamic-official-register",
        )
        assert validated["status"] == "VALIDATED"
        routed = route_verification_task(
            conn,
            instance_id="alpha-local",
            task_id=str(headline["task_id"]),
            engine_version=engine,
        )
        assert routed["state"] == "TARGETS_READY"
        assert [x["target_id"] for x in routed["target_candidates"]] == [candidate["target_id"]]
        assert all(task["publication_authority"] == "NONE" for task in list_verification_tasks(conn, instance_id="alpha-local"))
        assert all(target["publication_authority"] == "NONE" for target in list_primary_targets(conn, instance_id="alpha-local"))
        assert not any(
            target["url"] == candidate["url"]
            for target in list_primary_targets(conn, instance_id="beta-local")
        )

        resolver_events = conn.execute(
            """
            SELECT event_type FROM runtime_events
            WHERE instance_id='alpha-local'
              AND aggregate_type IN ('verification_task', 'primary_target')
            ORDER BY event_id
            """
        ).fetchall()
        event_types = [str(row["event_type"]) for row in resolver_events]
        assert "VERIFICATION_TASK_CREATED" in event_types
        assert "PRIMARY_TARGET_DISCOVERY_REQUIRED" in event_types
        assert "PRIMARY_TARGET_PROPOSED" in event_types
        assert "PRIMARY_TARGET_VALIDATED" in event_types
        assert "VERIFICATION_TARGETS_RESOLVED" in event_types
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_PRIMARY_RESOLVER_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("primary_resolver is a library; use --self-test for validation")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
