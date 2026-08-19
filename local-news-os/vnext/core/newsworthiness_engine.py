#!/usr/bin/env python3
"""Configuration-driven Newsworthiness Engine for LOCAL NEWS OS vNext.

Consumes only READY fact kernels from the site-owned runtime database and appends
an auditable scoring decision to the runtime event ledger. The engine ranks
editorial value but never grants publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any

from fact_kernel_engine import FactKernelError, get_fact_kernel
from runtime_store import connect, initialize, register_instance, utc_now

ROOT = Path(__file__).resolve().parents[3]

DIMENSIONS = (
    "local_impact",
    "public_utility",
    "urgency",
    "money",
    "affected_people",
    "novelty",
    "accountability",
    "proximity",
)
ROUTES = ("BUILD_PRIORITY", "BUILD", "MONITOR", "IGNORE")
PUBLICATION_AUTHORITY = "NONE"
EVENT_TYPE = "NEWSWORTHINESS_SCORED"


class NewsworthinessError(RuntimeError):
    pass


def _stable_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise NewsworthinessError(message)


def _bounded_score(value: Any, *, field: str) -> int:
    _require(isinstance(value, int) and not isinstance(value, bool), f"{field} must be an integer")
    _require(0 <= value <= 100, f"{field} must be between 0 and 100")
    return int(value)


def validate_newsworthiness_policy(
    editorial_pack: dict[str, Any],
    *,
    instance_id: str,
) -> dict[str, Any]:
    _require(isinstance(editorial_pack, dict), "editorial pack must be an object")
    _require(editorial_pack.get("schema_version") == "2.0", "editorial pack schema mismatch")
    _require(editorial_pack.get("pack_type") == "editorial", "not an editorial pack")
    _require(editorial_pack.get("instance_id") == instance_id, "editorial pack instance mismatch")

    policy = editorial_pack.get("newsworthiness")
    _require(isinstance(policy, dict), "editorial pack requires newsworthiness policy")
    weights = policy.get("weights")
    thresholds = policy.get("routing_thresholds")
    _require(isinstance(weights, dict), "newsworthiness.weights must be an object")
    _require(set(weights) == set(DIMENSIONS), "newsworthiness weights must define exactly the canonical dimensions")
    normalized_weights: dict[str, int] = {}
    for dimension in DIMENSIONS:
        weight = weights[dimension]
        _require(isinstance(weight, int) and not isinstance(weight, bool), f"weight must be integer: {dimension}")
        _require(0 <= weight <= 100, f"weight out of range: {dimension}")
        normalized_weights[dimension] = int(weight)
    _require(sum(normalized_weights.values()) > 0, "newsworthiness weights must have positive total")

    _require(isinstance(thresholds, dict), "newsworthiness.routing_thresholds must be an object")
    _require(
        set(thresholds) == {"BUILD_PRIORITY", "BUILD", "MONITOR"},
        "routing thresholds must define BUILD_PRIORITY, BUILD and MONITOR",
    )
    priority = _bounded_score(thresholds["BUILD_PRIORITY"], field="BUILD_PRIORITY threshold")
    build = _bounded_score(thresholds["BUILD"], field="BUILD threshold")
    monitor = _bounded_score(thresholds["MONITOR"], field="MONITOR threshold")
    _require(priority > build > monitor, "routing thresholds must be strictly descending")
    return {
        "weights": normalized_weights,
        "routing_thresholds": {
            "BUILD_PRIORITY": priority,
            "BUILD": build,
            "MONITOR": monitor,
        },
    }


def load_editorial_pack(instance_id: str) -> dict[str, Any]:
    instance_path = ROOT / "local-news-os" / "vnext" / "instances" / instance_id / "instance.json"
    _require(instance_path.is_file(), f"unknown instance: {instance_id}")
    cfg = json.loads(instance_path.read_text(encoding="utf-8"))
    _require(cfg.get("instance_id") == instance_id, "instance directory/id mismatch")
    packs = cfg.get("packs") or {}
    rel = packs.get("editorial")
    _require(isinstance(rel, str) and rel, "instance has no editorial pack")
    path = (ROOT / rel).resolve()
    root = ROOT.resolve()
    _require(root in path.parents, "editorial pack escapes repository")
    _require(path.is_file(), "editorial pack file missing")
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_newsworthiness_policy(value, instance_id=instance_id)
    return value


def validate_dimension_signals(signals: dict[str, Any]) -> dict[str, int]:
    _require(isinstance(signals, dict), "dimension signals must be an object")
    _require(set(signals) == set(DIMENSIONS), "dimension signals must define exactly the canonical dimensions")
    return {
        dimension: _bounded_score(signals[dimension], field=f"dimension signal {dimension}")
        for dimension in DIMENSIONS
    }


def calculate_score(
    *,
    signals: dict[str, Any],
    editorial_pack: dict[str, Any],
    instance_id: str,
) -> dict[str, Any]:
    normalized_signals = validate_dimension_signals(signals)
    policy = validate_newsworthiness_policy(editorial_pack, instance_id=instance_id)
    weights = policy["weights"]
    total_weight = sum(weights.values())
    numerator = sum(normalized_signals[key] * weights[key] for key in DIMENSIONS)
    score = (numerator + total_weight // 2) // total_weight
    thresholds = policy["routing_thresholds"]
    if score >= thresholds["BUILD_PRIORITY"]:
        route = "BUILD_PRIORITY"
    elif score >= thresholds["BUILD"]:
        route = "BUILD"
    elif score >= thresholds["MONITOR"]:
        route = "MONITOR"
    else:
        route = "IGNORE"
    components = {
        key: {
            "signal": normalized_signals[key],
            "weight": weights[key],
            "weighted_points": normalized_signals[key] * weights[key],
        }
        for key in DIMENSIONS
    }
    return {
        "score": int(score),
        "route": route,
        "dimension_signals": normalized_signals,
        "weights": dict(weights),
        "routing_thresholds": dict(thresholds),
        "components": components,
        "policy_fingerprint": _stable_hash(policy),
    }


def _decode_event(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["payload"] = json.loads(data.get("payload_json") or "{}")
    return data


def get_latest_newsworthiness(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    kernel_id: str,
) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT * FROM runtime_events
        WHERE instance_id=? AND aggregate_type='fact_kernel' AND aggregate_id=? AND event_type=?
        ORDER BY event_id DESC
        LIMIT 1
        """,
        (instance_id, kernel_id, EVENT_TYPE),
    ).fetchone()
    return _decode_event(row) if row is not None else None


def list_newsworthiness(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    route: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    rows = conn.execute(
        """
        SELECT * FROM runtime_events
        WHERE instance_id=? AND aggregate_type='fact_kernel' AND event_type=?
        ORDER BY event_id DESC
        LIMIT ?
        """,
        (instance_id, EVENT_TYPE, bounded * 4),
    ).fetchall()
    latest_by_kernel: dict[str, dict[str, Any]] = {}
    for row in rows:
        decoded = _decode_event(row)
        kernel_id = str(decoded["aggregate_id"])
        latest_by_kernel.setdefault(kernel_id, decoded)
    items = list(latest_by_kernel.values())
    if route is not None:
        _require(route in ROUTES, "unknown newsworthiness route")
        items = [item for item in items if item["payload"].get("route") == route]
    return items[:bounded]


def score_fact_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    kernel_id: str,
    dimension_signals: dict[str, Any],
    editorial_pack: dict[str, Any],
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    try:
        kernel = get_fact_kernel(conn, instance_id=instance_id, kernel_id=kernel_id)
    except FactKernelError as exc:
        raise NewsworthinessError(str(exc)) from exc
    _require(kernel.get("state") == "READY", "newsworthiness requires READY fact kernel")
    _require(kernel.get("material_fact_ready") is True, "material_fact_ready must be true")
    _require(kernel.get("fact_kernel_ready") is True, "fact_kernel_ready must be true")
    _require(kernel.get("publication_authority") == PUBLICATION_AUTHORITY, "fact kernel unexpectedly carries publication authority")

    result = calculate_score(
        signals=dimension_signals,
        editorial_pack=editorial_pack,
        instance_id=instance_id,
    )
    decision_payload = {
        "kernel_id": kernel_id,
        "kernel_fingerprint": kernel["fingerprint"],
        "score": result["score"],
        "route": result["route"],
        "dimension_signals": result["dimension_signals"],
        "weights": result["weights"],
        "routing_thresholds": result["routing_thresholds"],
        "components": result["components"],
        "policy_fingerprint": result["policy_fingerprint"],
        "publication_authority": PUBLICATION_AUTHORITY,
    }
    decision_fingerprint = _stable_hash(decision_payload)
    decision_payload["decision_fingerprint"] = decision_fingerprint

    latest = get_latest_newsworthiness(conn, instance_id=instance_id, kernel_id=kernel_id)
    if latest is not None and latest["payload"].get("decision_fingerprint") == decision_fingerprint:
        return latest, False

    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id, aggregate_type, aggregate_id, event_type,
                from_state, to_state, reason, payload_json, engine_version, created_at
            ) VALUES (?, 'fact_kernel', ?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                instance_id,
                kernel_id,
                EVENT_TYPE,
                result["route"],
                "configuration-driven editorial newsworthiness routing",
                json.dumps(decision_payload, ensure_ascii=False, sort_keys=True),
                engine_version,
                utc_now(),
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    latest = get_latest_newsworthiness(conn, instance_id=instance_id, kernel_id=kernel_id)
    assert latest is not None
    return latest, True


def _manifest(instance_id: str, domain: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": _stable_hash({"instance_id": instance_id, "domain": domain}),
        "runtime": {
            "owner": "site_application",
            "repository_runtime_state_enabled": False,
        },
    }


def _insert_ready_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str,
    kernel_id: str,
    fingerprint: str,
) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO signals(
            instance_id, signal_id, fingerprint, source_id, source_role,
            source_item_fingerprint, source_url, source_title, source_published_at,
            state, publication_authority, material_fact_ready, fact_kernel_ready,
            claim_hints_json, entity_hints_json, created_at, updated_at
        ) VALUES (?, ?, ?, 'neutral-source', 'PRIMARY', ?, 'https://example.invalid/item',
                  'Neutral source item', NULL, 'DISCOVERED', 'NONE', 0, 0, '[]', '[]', ?, ?)
        """,
        (instance_id, signal_id, f"sig-{fingerprint}", f"src-{fingerprint}", now, now),
    )
    conn.execute(
        """
        INSERT INTO fact_kernels(
            instance_id, kernel_id, signal_id, fingerprint, state,
            material_fact_ready, fact_kernel_ready, publication_authority,
            facts_json, provenance_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'READY', 1, 1, 'NONE', '[]', '[]', ?, ?)
        """,
        (instance_id, kernel_id, signal_id, fingerprint, now, now),
    )
    conn.commit()


def _policy(
    instance_id: str,
    *,
    weights: dict[str, int],
    priority: int = 75,
    build: int = 50,
    monitor: int = 25,
) -> dict[str, Any]:
    return {
        "schema_version": "2.0",
        "pack_type": "editorial",
        "instance_id": instance_id,
        "auto_publish_classes": [],
        "human_review_classes": [],
        "rules": {
            "verified_facts_only": True,
            "title_only_publishable": False,
            "one_held_story_blocks_publication": False,
        },
        "newsworthiness": {
            "weights": weights,
            "routing_thresholds": {
                "BUILD_PRIORITY": priority,
                "BUILD": build,
                "MONITOR": monitor,
            },
        },
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "runtime.db"
        conn = connect(path)
        initialize(conn)
        register_instance(conn, _manifest("alpha-local", "alpha.invalid"), engine_version="test")
        register_instance(conn, _manifest("beta-local", "beta.invalid"), engine_version="test")
        _insert_ready_kernel(
            conn,
            instance_id="alpha-local",
            signal_id="signal-a",
            kernel_id="kernel-a",
            fingerprint="kernel-fingerprint-a",
        )
        _insert_ready_kernel(
            conn,
            instance_id="beta-local",
            signal_id="signal-b",
            kernel_id="kernel-b",
            fingerprint="kernel-fingerprint-b",
        )

        signals = {
            "local_impact": 90,
            "public_utility": 80,
            "urgency": 70,
            "money": 60,
            "affected_people": 50,
            "novelty": 40,
            "accountability": 30,
            "proximity": 20,
        }
        alpha_weights = {
            "local_impact": 30,
            "public_utility": 20,
            "urgency": 15,
            "money": 10,
            "affected_people": 10,
            "novelty": 5,
            "accountability": 5,
            "proximity": 5,
        }
        beta_weights = {
            "local_impact": 5,
            "public_utility": 5,
            "urgency": 5,
            "money": 5,
            "affected_people": 10,
            "novelty": 20,
            "accountability": 25,
            "proximity": 25,
        }
        alpha_pack = _policy("alpha-local", weights=alpha_weights)
        beta_pack = _policy("beta-local", weights=beta_weights)

        first, created = score_fact_kernel(
            conn,
            instance_id="alpha-local",
            kernel_id="kernel-a",
            dimension_signals=signals,
            editorial_pack=alpha_pack,
            engine_version="test",
        )
        assert created is True
        assert first["payload"]["publication_authority"] == "NONE"
        assert first["payload"]["route"] in ROUTES
        repeat, created = score_fact_kernel(
            conn,
            instance_id="alpha-local",
            kernel_id="kernel-a",
            dimension_signals=signals,
            editorial_pack=alpha_pack,
            engine_version="test",
        )
        assert created is False
        assert repeat["event_id"] == first["event_id"]

        second, created = score_fact_kernel(
            conn,
            instance_id="beta-local",
            kernel_id="kernel-b",
            dimension_signals=signals,
            editorial_pack=beta_pack,
            engine_version="test",
        )
        assert created is True
        assert first["payload"]["score"] != second["payload"]["score"]
        assert len(list_newsworthiness(conn, instance_id="alpha-local")) == 1
        assert len(list_newsworthiness(conn, instance_id="beta-local")) == 1

        changed_signals = dict(signals)
        changed_signals["urgency"] = 100
        changed, created = score_fact_kernel(
            conn,
            instance_id="alpha-local",
            kernel_id="kernel-a",
            dimension_signals=changed_signals,
            editorial_pack=alpha_pack,
            engine_version="test",
        )
        assert created is True
        assert changed["event_id"] != first["event_id"]
        assert len(list_newsworthiness(conn, instance_id="alpha-local")) == 1

        try:
            score_fact_kernel(
                conn,
                instance_id="alpha-local",
                kernel_id="kernel-a",
                dimension_signals={"local_impact": 50},
                editorial_pack=alpha_pack,
                engine_version="test",
            )
        except NewsworthinessError:
            pass
        else:
            raise AssertionError("incomplete dimension signals were accepted")

        wrong_pack = dict(alpha_pack)
        wrong_pack["instance_id"] = "other-local"
        try:
            score_fact_kernel(
                conn,
                instance_id="alpha-local",
                kernel_id="kernel-a",
                dimension_signals=signals,
                editorial_pack=wrong_pack,
                engine_version="test",
            )
        except NewsworthinessError:
            pass
        else:
            raise AssertionError("cross-instance editorial policy was accepted")

        try:
            score_fact_kernel(
                conn,
                instance_id="beta-local",
                kernel_id="kernel-a",
                dimension_signals=signals,
                editorial_pack=beta_pack,
                engine_version="test",
            )
        except NewsworthinessError:
            pass
        else:
            raise AssertionError("cross-instance fact kernel access was accepted")
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_NEWSWORTHINESS_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--db")
    parser.add_argument("--instance")
    parser.add_argument("--kernel-id")
    parser.add_argument("--signals-json")
    parser.add_argument("--engine-version", default="local-news-os-vnext")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.db, args.instance, args.kernel_id, args.signals_json)):
        parser.error("--db, --instance, --kernel-id and --signals-json are required")
    editorial_pack = load_editorial_pack(args.instance)
    signals = json.loads(args.signals_json)
    conn = connect(args.db)
    try:
        event, created = score_fact_kernel(
            conn,
            instance_id=args.instance,
            kernel_id=args.kernel_id,
            dimension_signals=signals,
            editorial_pack=editorial_pack,
            engine_version=args.engine_version,
        )
    finally:
        conn.close()
    print(json.dumps({"created": created, "decision": event}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
