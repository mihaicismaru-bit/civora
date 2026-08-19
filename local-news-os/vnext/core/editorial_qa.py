#!/usr/bin/env python3
"""Fail-closed Editorial QA for LOCAL NEWS OS vNext.

Evaluates structured story drafts entirely from the site-owned runtime database.
A low-risk draft may advance only to QA_PASSED; this module never publishes.
Risky or unclassified material is isolated in HUMAN_REVIEW and failed integrity
checks are isolated in HOLD without blocking unrelated stories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fact_kernel_engine import get_fact_kernel
from newsworthiness_engine import get_latest_newsworthiness, score_fact_kernel
from runtime_store import connect, get_story, initialize, register_instance, utc_now
from signal_engine import get_signal
from story_engine import (
    compose_structured_draft,
    get_story_draft,
    materialize_story_draft,
)

PUBLICATION_AUTHORITY = "NONE"
OUTCOMES = {"QA_PASSED", "HUMAN_REVIEW", "HOLD"}
EVENT_TYPE = "EDITORIAL_QA_DECIDED"


class EditorialQAError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise EditorialQAError(message)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def validate_qa_policy(editorial_pack: dict[str, Any], *, instance_id: str) -> dict[str, Any]:
    _require(isinstance(editorial_pack, dict), "editorial pack must be an object")
    _require(editorial_pack.get("schema_version") == "2.0", "editorial pack schema mismatch")
    _require(editorial_pack.get("pack_type") == "editorial", "not an editorial pack")
    _require(editorial_pack.get("instance_id") == instance_id, "editorial pack instance mismatch")
    auto_classes = editorial_pack.get("auto_publish_classes")
    review_classes = editorial_pack.get("human_review_classes")
    _require(isinstance(auto_classes, list) and auto_classes, "auto_publish_classes must be non-empty")
    _require(isinstance(review_classes, list) and review_classes, "human_review_classes must be non-empty")
    auto = {_clean(item) for item in auto_classes if _clean(item)}
    review = {_clean(item) for item in review_classes if _clean(item)}
    _require(auto and review and auto.isdisjoint(review), "auto and human-review classes must be disjoint")

    policy = editorial_pack.get("editorial_qa")
    _require(isinstance(policy, dict), "editorial pack requires editorial_qa policy")
    default_class = _clean(policy.get("default_editorial_class"))
    _require(default_class, "editorial_qa.default_editorial_class is required")
    minimum_blocks = policy.get("minimum_body_blocks")
    minimum_sources = policy.get("minimum_primary_sources")
    duplicate_threshold = policy.get("duplicate_headline_similarity_threshold")
    max_future_hours = policy.get("max_source_future_skew_hours", 6)
    _require(isinstance(minimum_blocks, int) and 1 <= minimum_blocks <= 20, "minimum_body_blocks out of range")
    _require(isinstance(minimum_sources, int) and 1 <= minimum_sources <= 20, "minimum_primary_sources out of range")
    _require(isinstance(duplicate_threshold, (int, float)) and 0.5 <= float(duplicate_threshold) <= 1.0, "duplicate threshold out of range")
    _require(isinstance(max_future_hours, int) and 0 <= max_future_hours <= 48, "max future skew out of range")

    risk_rules = policy.get("risk_term_classes") or []
    _require(isinstance(risk_rules, list), "risk_term_classes must be a list")
    normalized_rules: list[dict[str, Any]] = []
    for rule in risk_rules:
        _require(isinstance(rule, dict), "risk term rule must be an object")
        editorial_class = _clean(rule.get("editorial_class"))
        terms = [_clean(term).casefold() for term in (rule.get("terms") or []) if _clean(term)]
        _require(editorial_class in review, "risk term rule must route to a human-review class")
        _require(terms, "risk term rule requires terms")
        normalized_rules.append({"editorial_class": editorial_class, "terms": sorted(set(terms))})
    return {
        "auto_classes": auto,
        "review_classes": review,
        "default_editorial_class": default_class,
        "minimum_body_blocks": minimum_blocks,
        "minimum_primary_sources": minimum_sources,
        "duplicate_headline_similarity_threshold": float(duplicate_threshold),
        "max_source_future_skew_hours": max_future_hours,
        "risk_term_classes": normalized_rules,
    }


def _decode_decision(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["gates"] = json.loads(data.pop("gates_json"))
    return data


def get_qa_decision(conn: sqlite3.Connection, *, instance_id: str, decision_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM editorial_qa_decisions WHERE instance_id=? AND decision_id=?",
        (instance_id, decision_id),
    ).fetchone()
    if row is None:
        raise EditorialQAError("QA decision not found for instance")
    return _decode_decision(row)


def get_latest_qa_decision(conn: sqlite3.Connection, *, instance_id: str, story_id: str) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM editorial_qa_decisions
        WHERE instance_id=? AND story_id=?
        ORDER BY created_at DESC, decision_id DESC LIMIT 1
        """,
        (instance_id, story_id),
    ).fetchone()
    return _decode_decision(row) if row is not None else None


def list_qa_decisions(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    outcome: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    if outcome is not None:
        _require(outcome in OUTCOMES, "unknown QA outcome")
        rows = conn.execute(
            "SELECT * FROM editorial_qa_decisions WHERE instance_id=? AND outcome=? ORDER BY created_at DESC LIMIT ?",
            (instance_id, outcome, bounded),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM editorial_qa_decisions WHERE instance_id=? ORDER BY created_at DESC LIMIT ?",
            (instance_id, bounded),
        ).fetchall()
    return [_decode_decision(row) for row in rows]


def _normalized_tokens(text: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE)
        if len(token) >= 3
    }


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _claim_signature(draft: dict[str, Any]) -> str:
    claims = sorted(
        _clean(block.get("text")).casefold()
        for block in draft.get("body_blocks") or []
        if _clean(block.get("text"))
    )
    return _stable_hash(claims)


def _find_duplicate(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    draft: dict[str, Any],
    threshold: float,
) -> tuple[str | None, float]:
    rows = conn.execute(
        "SELECT story_id, headline, body_blocks_json FROM story_drafts WHERE instance_id=? AND story_id<>?",
        (instance_id, story_id),
    ).fetchall()
    headline_tokens = _normalized_tokens(str(draft["headline"]))
    signature = _claim_signature(draft)
    best_story: str | None = None
    best_similarity = 0.0
    for row in rows:
        other_blocks = json.loads(row["body_blocks_json"])
        other_signature = _stable_hash(
            sorted(
                _clean(block.get("text")).casefold()
                for block in other_blocks
                if _clean(block.get("text"))
            )
        )
        similarity = _jaccard(headline_tokens, _normalized_tokens(str(row["headline"])))
        if signature == other_signature:
            similarity = 1.0
        if similarity > best_similarity:
            best_similarity = similarity
            best_story = str(row["story_id"])
    if best_similarity >= threshold:
        return best_story, round(best_similarity, 4)
    return None, round(best_similarity, 4)


def _parse_time(value: str | None) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _temporal_gate(signal: dict[str, Any], draft: dict[str, Any], *, max_future_hours: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    ceiling = now + timedelta(hours=max_future_hours)
    checked: list[str] = []
    bad: list[str] = []
    source_published = signal.get("source_published_at")
    if source_published:
        parsed = _parse_time(str(source_published))
        checked.append("signal.source_published_at")
        if parsed is None or parsed > ceiling:
            bad.append("signal.source_published_at")
    for index, source in enumerate(draft.get("source_references") or []):
        observed = source.get("source_observed_at")
        if observed:
            parsed = _parse_time(str(observed))
            field = f"source_references[{index}].source_observed_at"
            checked.append(field)
            if parsed is None or parsed > ceiling:
                bad.append(field)
    return {"pass": not bad, "checked": checked, "invalid_or_future": bad}


def _classify(draft: dict[str, Any], policy: dict[str, Any]) -> tuple[str, list[str]]:
    corpus = " ".join(
        [str(draft.get("headline") or ""), str(draft.get("dek") or "")]
        + [str(block.get("text") or "") for block in draft.get("body_blocks") or []]
    ).casefold()
    matched: list[str] = []
    for rule in policy["risk_term_classes"]:
        hits = [term for term in rule["terms"] if term in corpus]
        if hits:
            matched.extend(hits)
            return str(rule["editorial_class"]), sorted(set(matched))
    return str(policy["default_editorial_class"]), []


def evaluate_story_draft(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    editorial_pack: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    policy = validate_qa_policy(editorial_pack, instance_id=instance_id)
    story = get_story(conn, instance_id=instance_id, story_id=story_id)
    draft = get_story_draft(conn, instance_id=instance_id, story_id=story_id)
    _require(story["state"] == "STORY_DRAFTED", "Editorial QA requires STORY_DRAFTED state")
    _require(draft["state"] == "DRAFTED", "Editorial QA requires DRAFTED draft")
    _require(draft["publication_authority"] == PUBLICATION_AUTHORITY, "draft unexpectedly carries publication authority")

    kernel = get_fact_kernel(conn, instance_id=instance_id, kernel_id=str(draft["kernel_id"]))
    signal = get_signal(conn, instance_id=instance_id, signal_id=str(kernel["signal_id"]))
    newsworthiness = get_latest_newsworthiness(conn, instance_id=instance_id, kernel_id=str(draft["kernel_id"]))
    _require(newsworthiness is not None, "Editorial QA requires newsworthiness decision")
    expected = compose_structured_draft(
        instance_id=instance_id,
        kernel=kernel,
        signal=signal,
        newsworthiness_event=newsworthiness,
        editorial_pack=editorial_pack,
    )

    comparable_fields = (
        "headline", "dek", "body_blocks", "factbox", "context",
        "source_references", "follow_up", "section", "tags", "entity_bindings",
    )
    structured_match = all(draft[field] == expected[field] for field in comparable_fields)
    body = draft.get("body_blocks") or []
    kernel_facts = {str(item.get("claim_key")): item for item in kernel.get("facts") or []}
    grounded = bool(body) and all(
        block.get("type") == "verified_fact"
        and str(block.get("claim_key")) in kernel_facts
        and _clean(block.get("text")) == _clean(kernel_facts[str(block.get("claim_key"))].get("claim_text"))
        and _clean(block.get("verification_result_id")) == _clean(kernel_facts[str(block.get("claim_key"))].get("verification_result_id"))
        for block in body
    ) and len(body) == len(kernel_facts)
    source_refs = draft.get("source_references") or []
    source_claim_keys = {str(item.get("claim_key")) for item in source_refs if item.get("claim_key")}
    provenance_complete = (
        len(source_refs) >= policy["minimum_primary_sources"]
        and set(kernel_facts).issubset(source_claim_keys)
        and all(_clean(item.get("primary_target_url")).startswith(("http://", "https://")) for item in source_refs)
        and all(_clean(item.get("evidence_url")).startswith(("http://", "https://")) for item in source_refs)
    )
    content_integrity = (
        bool(_clean(draft.get("headline")))
        and bool(_clean(draft.get("dek")))
        and len(body) >= policy["minimum_body_blocks"]
        and bool(draft.get("factbox"))
        and bool(_clean(draft.get("section")))
    )
    unresolved_safe = all(
        item.get("resolution_status") == "UNRESOLVED" and item.get("public_claim_allowed") is False
        for item in draft.get("entity_bindings") or []
    )
    temporal = _temporal_gate(signal, draft, max_future_hours=policy["max_source_future_skew_hours"])
    duplicate_story_id, duplicate_similarity = _find_duplicate(
        conn,
        instance_id=instance_id,
        story_id=story_id,
        draft=draft,
        threshold=policy["duplicate_headline_similarity_threshold"],
    )
    gates = {
        "structured_draft_matches_verified_kernel": {"pass": structured_match},
        "claim_level_grounding": {"pass": grounded, "verified_fact_count": len(kernel_facts)},
        "provenance_complete": {"pass": provenance_complete, "source_reference_count": len(source_refs)},
        "content_integrity": {"pass": content_integrity, "body_block_count": len(body)},
        "temporal_consistency": temporal,
        "unresolved_entities_non_public": {"pass": unresolved_safe},
        "duplicate_risk": {
            "pass": duplicate_story_id is None,
            "duplicate_story_id": duplicate_story_id,
            "similarity": duplicate_similarity,
            "threshold": policy["duplicate_headline_similarity_threshold"],
        },
        "publication_authority_absent": {"pass": draft["publication_authority"] == PUBLICATION_AUTHORITY},
    }
    all_gates_pass = all(bool(value.get("pass")) for value in gates.values())
    editorial_class, risk_matches = _classify(draft, policy)
    if not all_gates_pass:
        outcome = "HOLD"
        reason = "one or more fail-closed editorial QA gates failed"
    elif editorial_class in policy["review_classes"] or editorial_class not in policy["auto_classes"]:
        outcome = "HUMAN_REVIEW"
        reason = "editorial class requires human review"
    else:
        outcome = "QA_PASSED"
        reason = "all editorial QA gates passed for an approved low-risk class"

    decision_payload = {
        "story_id": story_id,
        "draft_fingerprint": draft["fingerprint"],
        "draft_revision": int(draft["revision"]),
        "editorial_class": editorial_class,
        "risk_term_matches": risk_matches,
        "outcome": outcome,
        "gates": gates,
        "duplicate_story_id": duplicate_story_id,
        "publication_authority": PUBLICATION_AUTHORITY,
    }
    decision_fingerprint = _stable_hash(decision_payload)
    decision_id = _hash_id(instance_id, story_id, str(draft["fingerprint"]), decision_fingerprint)
    existing = conn.execute(
        "SELECT * FROM editorial_qa_decisions WHERE instance_id=? AND decision_id=?",
        (instance_id, decision_id),
    ).fetchone()
    if existing is not None:
        return _decode_decision(existing), False

    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute(
            "SELECT state, revision FROM stories WHERE instance_id=? AND story_id=?",
            (instance_id, story_id),
        ).fetchone()
        _require(current is not None and current["state"] == "STORY_DRAFTED", "story changed during Editorial QA")
        story_revision = int(current["revision"])
        conn.execute(
            """
            INSERT INTO editorial_qa_decisions(
                instance_id, decision_id, story_id, draft_fingerprint, draft_revision,
                decision_fingerprint, editorial_class, outcome, gates_json,
                duplicate_story_id, publication_authority, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NONE', ?)
            """,
            (
                instance_id, decision_id, story_id, draft["fingerprint"], int(draft["revision"]),
                decision_fingerprint, editorial_class, outcome,
                json.dumps(gates, ensure_ascii=False, sort_keys=True), duplicate_story_id, now,
            ),
        )
        cursor = conn.execute(
            """
            UPDATE stories SET state=?, revision=revision+1, updated_at=?
            WHERE instance_id=? AND story_id=? AND revision=? AND state='STORY_DRAFTED'
            """,
            (outcome, now, instance_id, story_id, story_revision),
        )
        _require(cursor.rowcount == 1, "story changed while persisting Editorial QA")
        event_payload = dict(decision_payload)
        event_payload["decision_id"] = decision_id
        event_payload["decision_fingerprint"] = decision_fingerprint
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id, aggregate_type, aggregate_id, event_type,
                from_state, to_state, reason, payload_json, engine_version, created_at
            ) VALUES (?, 'story', ?, ?, 'STORY_DRAFTED', ?, ?, ?, ?, ?)
            """,
            (
                instance_id, story_id, EVENT_TYPE, outcome, reason,
                json.dumps(event_payload, ensure_ascii=False, sort_keys=True), engine_version, now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_qa_decision(conn, instance_id=instance_id, decision_id=decision_id), True


def _manifest(instance_id: str, domain: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": _stable_hash({"instance_id": instance_id, "domain": domain}),
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def _pack(instance_id: str, *, risk_terms: list[str]) -> dict[str, Any]:
    return {
        "schema_version": "2.0", "pack_type": "editorial", "instance_id": instance_id,
        "auto_publish_classes": ["straight_news"],
        "human_review_classes": ["reputational_claim", "investigation", "legal_ambiguity"],
        "rules": {"verified_facts_only": True, "title_only_publishable": False, "one_held_story_blocks_publication": False},
        "newsworthiness": {
            "weights": {"local_impact": 20, "public_utility": 15, "urgency": 15, "money": 10, "affected_people": 10, "novelty": 10, "accountability": 10, "proximity": 10},
            "routing_thresholds": {"BUILD_PRIORITY": 80, "BUILD": 55, "MONITOR": 30},
        },
        "story_engine": {
            "default_section": "LOCAL", "max_headline_chars": 120, "max_dek_chars": 220,
            "section_by_claim_kind": {"HEADLINE_ASSERTION": "LOCAL", "MONEY": "ECONOMY"},
            "follow_up_label": "What next",
        },
        "editorial_qa": {
            "default_editorial_class": "straight_news",
            "minimum_body_blocks": 2,
            "minimum_primary_sources": 1,
            "duplicate_headline_similarity_threshold": 0.92,
            "max_source_future_skew_hours": 6,
            "risk_term_classes": [
                {"editorial_class": "reputational_claim", "terms": risk_terms}
            ],
        },
    }


def _insert_ready_fixture(conn: sqlite3.Connection, *, instance_id: str, signal_id: str, kernel_id: str, headline: str, suffix: str) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO signals(instance_id,signal_id,fingerprint,source_id,source_role,source_item_fingerprint,source_url,source_title,source_published_at,state,publication_authority,material_fact_ready,fact_kernel_ready,claim_hints_json,entity_hints_json,created_at,updated_at)
        VALUES (?,?,?,'fixture','DISCOVERY',?,'https://example.invalid/signal',?,?,'DISCOVERED','NONE',0,0,'[]','[]',?,?)
        """,
        (instance_id, signal_id, f"sig-{suffix}", f"item-{suffix}", headline, now, now, now),
    )
    facts = [
        {"claim_key":"headline","claim_kind":"HEADLINE_ASSERTION","claim_text":headline,"normalized_claim":{"statement":headline},"confidence":99,"verification_result_id":f"r-h-{suffix}"},
        {"claim_key":"money","claim_kind":"MONEY","claim_text":"The verified amount is 100 units","normalized_claim":{"amount":100,"unit":"units"},"confidence":97,"verification_result_id":f"r-m-{suffix}"},
    ]
    provenance = [
        {"claim_key":"headline","verification_result_id":f"r-h-{suffix}","primary_target_id":"authority","primary_target_url":"https://authority.example.invalid/notices","evidence_url":f"https://authority.example.invalid/{suffix}","evidence_fingerprint":f"e-{suffix}","evidence_summary":"supported","source_observed_at":now,"verdict":"SUPPORTS"},
        {"claim_key":"money","verification_result_id":f"r-m-{suffix}","primary_target_id":"authority","primary_target_url":"https://authority.example.invalid/notices","evidence_url":f"https://authority.example.invalid/{suffix}","evidence_fingerprint":f"e-{suffix}","evidence_summary":"supported","source_observed_at":now,"verdict":"SUPPORTS"},
    ]
    conn.execute(
        """
        INSERT INTO fact_kernels(instance_id,kernel_id,signal_id,fingerprint,state,material_fact_ready,fact_kernel_ready,publication_authority,facts_json,provenance_json,created_at,updated_at)
        VALUES (?,?,?,?,'READY',1,1,'NONE',?,?,?,?)
        """,
        (instance_id, kernel_id, signal_id, f"kernel-{suffix}", json.dumps(facts, sort_keys=True), json.dumps(provenance, sort_keys=True), now, now),
    )
    conn.commit()


def _build_draft(conn: sqlite3.Connection, *, instance_id: str, kernel_id: str, pack: dict[str, Any], engine: str) -> dict[str, Any]:
    score_fact_kernel(
        conn, instance_id=instance_id, kernel_id=kernel_id,
        dimension_signals={"local_impact":90,"public_utility":90,"urgency":80,"money":70,"affected_people":80,"novelty":70,"accountability":70,"proximity":90},
        editorial_pack=pack, engine_version=engine,
    )
    draft, _ = materialize_story_draft(
        conn, instance_id=instance_id, kernel_id=kernel_id,
        editorial_pack=pack, engine_version=engine,
    )
    return draft


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        conn = connect(Path(tmp) / "qa.sqlite3")
        initialize(conn)
        engine = "vnext-editorial-qa-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid"), engine_version=engine)
        alpha_pack = _pack("alpha-local", risk_terms=["fraud", "accused"])
        beta_pack = _pack("beta-local", risk_terms=["allegation"])

        _insert_ready_fixture(conn, instance_id="alpha-local", signal_id="s1", kernel_id="k1", headline="Verified service changes start Monday", suffix="a1")
        d1 = _build_draft(conn, instance_id="alpha-local", kernel_id="k1", pack=alpha_pack, engine=engine)
        q1, created = evaluate_story_draft(conn, instance_id="alpha-local", story_id=d1["story_id"], editorial_pack=alpha_pack, engine_version=engine)
        assert created and q1["outcome"] == "QA_PASSED" and q1["publication_authority"] == "NONE"
        assert get_story(conn, instance_id="alpha-local", story_id=d1["story_id"])["state"] == "QA_PASSED"

        _insert_ready_fixture(conn, instance_id="alpha-local", signal_id="s2", kernel_id="k2", headline="Official notice contains fraud allegation", suffix="a2")
        d2 = _build_draft(conn, instance_id="alpha-local", kernel_id="k2", pack=alpha_pack, engine=engine)
        q2, _ = evaluate_story_draft(conn, instance_id="alpha-local", story_id=d2["story_id"], editorial_pack=alpha_pack, engine_version=engine)
        assert q2["outcome"] == "HUMAN_REVIEW" and q2["editorial_class"] == "reputational_claim"
        assert get_story(conn, instance_id="alpha-local", story_id=d2["story_id"])["state"] == "HUMAN_REVIEW"

        _insert_ready_fixture(conn, instance_id="alpha-local", signal_id="s3", kernel_id="k3", headline="Verified service changes start Monday", suffix="a3")
        d3 = _build_draft(conn, instance_id="alpha-local", kernel_id="k3", pack=alpha_pack, engine=engine)
        q3, _ = evaluate_story_draft(conn, instance_id="alpha-local", story_id=d3["story_id"], editorial_pack=alpha_pack, engine_version=engine)
        assert q3["outcome"] == "HOLD" and q3["duplicate_story_id"] == d1["story_id"]

        _insert_ready_fixture(conn, instance_id="beta-local", signal_id="s4", kernel_id="k4", headline="Neutral verified community update", suffix="b1")
        d4 = _build_draft(conn, instance_id="beta-local", kernel_id="k4", pack=beta_pack, engine=engine)
        try:
            get_latest_qa_decision(conn, instance_id="beta-local", story_id=d1["story_id"])
        except Exception:
            raise
        assert get_latest_qa_decision(conn, instance_id="beta-local", story_id=d1["story_id"]) is None
        q4, _ = evaluate_story_draft(conn, instance_id="beta-local", story_id=d4["story_id"], editorial_pack=beta_pack, engine_version=engine)
        assert q4["outcome"] == "QA_PASSED"
        assert len(list_qa_decisions(conn, instance_id="alpha-local")) == 3
        assert len(list_qa_decisions(conn, instance_id="beta-local")) == 1
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_EDITORIAL_QA_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("use --self-test")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
