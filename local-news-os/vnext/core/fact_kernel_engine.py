#!/usr/bin/env python3
"""Site-owned Fact Kernel Engine for LOCAL NEWS OS vNext.

Consumes evidence-bound primary verification results and materializes a durable
claim-level fact kernel only when every verification task for a signal is
supported by validated primary evidence. Contradicted, missing, inconclusive,
or unvalidated evidence fails closed. No publication authority is granted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from primary_resolver import (
    get_primary_target,
    get_verification_task,
    list_verification_tasks,
    resolve_signal,
)
from runtime_store import connect, initialize, register_instance, utc_now
from signal_engine import get_signal, materialize_source_item
from source_adapters import SourceDefinition, SourceItem

PUBLICATION_AUTHORITY = "NONE"
VERDICTS = {"SUPPORTS", "CONTRADICTS", "INCONCLUSIVE"}
KERNEL_STATE = "READY"


class FactKernelError(RuntimeError):
    pass


def _hash_id(*parts: str, length: int = 24) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:length]


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _absolute_http_url(value: Any, *, field: str) -> str:
    text = _clean(value)
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise FactKernelError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise FactKernelError(f"{field} must not contain credentials")
    return text


def _append_event(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    aggregate_type: str,
    aggregate_id: str,
    event_type: str,
    engine_version: str,
    to_state: str | None = None,
    reason: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO runtime_events(
            instance_id, aggregate_type, aggregate_id, event_type,
            from_state, to_state, reason, payload_json, engine_version, created_at
        ) VALUES (?, ?, ?, ?, NULL, ?, ?, ?, ?, ?)
        """,
        (
            instance_id,
            aggregate_type,
            aggregate_id,
            event_type,
            to_state,
            reason,
            json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
            engine_version,
            utc_now(),
        ),
    )


def record_verification_result(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    task_id: str,
    target_id: str,
    verdict: str,
    evidence_url: str,
    evidence_fingerprint: str,
    evidence_summary: str,
    confidence: int,
    engine_version: str,
    normalized_claim: dict[str, Any] | None = None,
    source_observed_at: str | None = None,
) -> tuple[dict[str, Any], bool]:
    """Record one evidence-bound verdict idempotently. Returns (result, created)."""
    verdict = _clean(verdict).upper()
    if verdict not in VERDICTS:
        raise FactKernelError("unsupported verification verdict")
    if not isinstance(confidence, int) or not 0 <= confidence <= 100:
        raise FactKernelError("confidence must be between 0 and 100")
    evidence_url = _absolute_http_url(evidence_url, field="evidence_url")
    evidence_fingerprint = _clean(evidence_fingerprint)
    evidence_summary = _clean(evidence_summary)
    if not evidence_fingerprint or not evidence_summary:
        raise FactKernelError("evidence_fingerprint and evidence_summary are required")
    if normalized_claim is not None and not isinstance(normalized_claim, dict):
        raise FactKernelError("normalized_claim must be an object")

    task = get_verification_task(conn, instance_id=instance_id, task_id=task_id)
    if task["state"] != "TARGETS_READY":
        raise FactKernelError("verification result requires a TARGETS_READY task")
    if task["publication_authority"] != "NONE":
        raise FactKernelError("verification task unexpectedly carries publication authority")
    linked = {str(item["target_id"]): item for item in task.get("target_candidates", [])}
    if target_id not in linked:
        raise FactKernelError("target is not routed to this verification task")
    target = get_primary_target(conn, instance_id=instance_id, target_id=target_id)
    if target["status"] != "VALIDATED" or target["publication_authority"] != "NONE":
        raise FactKernelError("verification result requires a validated fail-closed primary target")

    result_id = _hash_id(instance_id, task_id, target_id, evidence_fingerprint, verdict)
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM verification_results WHERE instance_id=? AND result_id=?",
            (instance_id, result_id),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return _decode_result(existing), False
        conn.execute(
            """
            INSERT INTO verification_results(
                instance_id, result_id, task_id, signal_id, target_id, verdict,
                evidence_url, evidence_fingerprint, evidence_summary,
                normalized_claim_json, confidence, source_observed_at,
                publication_authority, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NONE', ?)
            """,
            (
                instance_id,
                result_id,
                task_id,
                task["signal_id"],
                target_id,
                verdict,
                evidence_url,
                evidence_fingerprint,
                evidence_summary,
                json.dumps(normalized_claim or {}, ensure_ascii=False, sort_keys=True),
                confidence,
                _clean(source_observed_at) or None,
                now,
            ),
        )
        _append_event(
            conn,
            instance_id=instance_id,
            aggregate_type="verification_result",
            aggregate_id=result_id,
            event_type="PRIMARY_EVIDENCE_RECORDED",
            to_state=verdict,
            reason="evidence-bound primary verification result",
            engine_version=engine_version,
            payload={
                "task_id": task_id,
                "signal_id": task["signal_id"],
                "target_id": target_id,
                "evidence_fingerprint": evidence_fingerprint,
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_verification_result(conn, instance_id=instance_id, result_id=result_id), True


def _decode_result(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["normalized_claim"] = json.loads(data.pop("normalized_claim_json"))
    return data


def get_verification_result(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    result_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM verification_results WHERE instance_id=? AND result_id=?",
        (instance_id, result_id),
    ).fetchone()
    if row is None:
        raise FactKernelError("verification result not found for instance")
    return _decode_result(row)


def list_verification_results(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str | None = None,
    task_id: str | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    bounded = max(1, min(1000, int(limit)))
    clauses = ["instance_id=?"]
    params: list[Any] = [instance_id]
    if signal_id:
        clauses.append("signal_id=?")
        params.append(signal_id)
    if task_id:
        clauses.append("task_id=?")
        params.append(task_id)
    params.append(bounded)
    rows = conn.execute(
        f"SELECT * FROM verification_results WHERE {' AND '.join(clauses)} ORDER BY created_at ASC, result_id ASC LIMIT ?",
        tuple(params),
    ).fetchall()
    return [_decode_result(row) for row in rows]


def _task_support(task: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    task_results = [item for item in results if item["task_id"] == task["task_id"]]
    if not task_results:
        return {"status": "MISSING", "result": None}
    if any(item["verdict"] == "CONTRADICTS" for item in task_results):
        return {"status": "CONTRADICTED", "result": None}
    supported = [item for item in task_results if item["verdict"] == "SUPPORTS"]
    if not supported:
        return {"status": "INCONCLUSIVE", "result": None}
    best = sorted(supported, key=lambda item: (-int(item["confidence"]), item["created_at"], item["result_id"]))[0]
    return {"status": "SUPPORTED", "result": best}


def _decode_kernel(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["facts"] = json.loads(data.pop("facts_json"))
    data["provenance"] = json.loads(data.pop("provenance_json"))
    data["material_fact_ready"] = bool(data["material_fact_ready"])
    data["fact_kernel_ready"] = bool(data["fact_kernel_ready"])
    return data


def get_fact_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    kernel_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM fact_kernels WHERE instance_id=? AND kernel_id=?",
        (instance_id, kernel_id),
    ).fetchone()
    if row is None:
        raise FactKernelError("fact kernel not found for instance")
    return _decode_kernel(row)


def list_fact_kernels(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    bounded = max(1, min(500, int(limit)))
    rows = conn.execute(
        "SELECT * FROM fact_kernels WHERE instance_id=? ORDER BY created_at DESC, kernel_id ASC LIMIT ?",
        (instance_id, bounded),
    ).fetchall()
    return [_decode_kernel(row) for row in rows]


def materialize_fact_kernel(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    signal_id: str,
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    signal = get_signal(conn, instance_id=instance_id, signal_id=signal_id)
    if signal["publication_authority"] != "NONE":
        raise FactKernelError("signal unexpectedly carries publication authority")
    tasks = list_verification_tasks(conn, instance_id=instance_id, limit=1000)
    tasks = [task for task in tasks if task["signal_id"] == signal_id]
    if not tasks:
        raise FactKernelError("fact kernel requires verification tasks")
    if any(task["state"] != "TARGETS_READY" for task in tasks):
        raise FactKernelError("all verification tasks must have validated primary targets")
    results = list_verification_results(conn, instance_id=instance_id, signal_id=signal_id, limit=1000)

    facts: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    for task in sorted(tasks, key=lambda item: (item["claim_kind"], item["claim_key"])):
        support = _task_support(task, results)
        if support["status"] != "SUPPORTED":
            raise FactKernelError(
                f"fact kernel blocked: task {task['task_id']} is {support['status']}"
            )
        result = support["result"]
        assert isinstance(result, dict)
        target = get_primary_target(conn, instance_id=instance_id, target_id=result["target_id"])
        fact = {
            "claim_key": task["claim_key"],
            "claim_kind": task["claim_kind"],
            "claim_text": task["claim_text"],
            "normalized_claim": result["normalized_claim"],
            "confidence": int(result["confidence"]),
            "verification_result_id": result["result_id"],
        }
        facts.append(fact)
        provenance.append(
            {
                "claim_key": task["claim_key"],
                "verification_result_id": result["result_id"],
                "primary_target_id": target["target_id"],
                "primary_target_url": target["url"],
                "evidence_url": result["evidence_url"],
                "evidence_fingerprint": result["evidence_fingerprint"],
                "evidence_summary": result["evidence_summary"],
                "source_observed_at": result["source_observed_at"],
                "verdict": result["verdict"],
            }
        )

    kernel_fingerprint = hashlib.sha256(
        json.dumps(
            {"instance_id": instance_id, "signal_id": signal_id, "facts": facts, "provenance": provenance},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    kernel_id = _hash_id(instance_id, signal_id, kernel_fingerprint)
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM fact_kernels WHERE instance_id=? AND signal_id=?",
            (instance_id, signal_id),
        ).fetchone()
        if existing is not None:
            existing_kernel = _decode_kernel(existing)
            if existing_kernel["fingerprint"] != kernel_fingerprint:
                raise FactKernelError("fact kernel already exists with different verified evidence")
            conn.commit()
            return existing_kernel, False
        conn.execute(
            """
            INSERT INTO fact_kernels(
                instance_id, kernel_id, signal_id, fingerprint, state,
                material_fact_ready, fact_kernel_ready, publication_authority,
                facts_json, provenance_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'READY', 1, 1, 'NONE', ?, ?, ?, ?)
            """,
            (
                instance_id,
                kernel_id,
                signal_id,
                kernel_fingerprint,
                json.dumps(facts, ensure_ascii=False, sort_keys=True),
                json.dumps(provenance, ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        _append_event(
            conn,
            instance_id=instance_id,
            aggregate_type="fact_kernel",
            aggregate_id=kernel_id,
            event_type="FACT_KERNEL_READY",
            to_state="READY",
            reason="all verification tasks supported by validated primary evidence",
            engine_version=engine_version,
            payload={"signal_id": signal_id, "fact_count": len(facts)},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_fact_kernel(conn, instance_id=instance_id, kernel_id=kernel_id), True


def _manifest(instance_id: str, domain: str, config_sha: str) -> dict[str, Any]:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": config_sha,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "facts.sqlite3"
        conn = connect(db)
        initialize(conn)
        engine = "vnext-fact-kernel-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a" * 64), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b" * 64), engine_version=engine)
        discovery = SourceDefinition.from_dict(
            {"source_id": "neutral-discovery", "adapter": "RSS_ATOM", "role": "DISCOVERY", "url": "https://news.example.test/feed.xml", "config": {}}
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
                    "verification": {"match_terms": [], "claim_kinds": []},
                },
            }
        )
        item = SourceItem(
            source_id="neutral-discovery",
            external_id="1",
            url="https://news.example.test/story",
            title="Public Board Approves 12.5% Increase Worth 20,000 EUR",
            summary="Decision dated 19.08.2026.",
            fingerprint="neutral-fact-source-item",
        )
        signal, _ = materialize_source_item(
            conn,
            instance_id="alpha-local",
            source=discovery,
            item=item,
            engine_version=engine,
        )
        tasks = resolve_signal(
            conn,
            instance_id="alpha-local",
            signal_id=signal["signal_id"],
            source_definitions=[discovery, primary],
            engine_version=engine,
        )
        assert tasks and all(task["state"] == "TARGETS_READY" for task in tasks)
        target_id = tasks[0]["target_candidates"][0]["target_id"]

        try:
            materialize_fact_kernel(conn, instance_id="alpha-local", signal_id=signal["signal_id"], engine_version=engine)
        except FactKernelError as exc:
            assert "MISSING" in str(exc)
        else:
            raise AssertionError("kernel materialized without evidence")

        for task in tasks:
            record_verification_result(
                conn,
                instance_id="alpha-local",
                task_id=task["task_id"],
                target_id=target_id,
                verdict="SUPPORTS",
                evidence_url="https://authority.example.test/notices/1",
                evidence_fingerprint=f"evidence-{task['claim_key']}",
                evidence_summary=f"Primary record supports {task['claim_kind']}",
                confidence=95,
                normalized_claim={"value": task["claim_text"]},
                source_observed_at="2026-08-19T12:00:00Z",
                engine_version=engine,
            )
        kernel, created = materialize_fact_kernel(
            conn,
            instance_id="alpha-local",
            signal_id=signal["signal_id"],
            engine_version=engine,
        )
        assert created is True
        assert kernel["state"] == "READY"
        assert kernel["material_fact_ready"] is True
        assert kernel["fact_kernel_ready"] is True
        assert kernel["publication_authority"] == "NONE"
        assert len(kernel["facts"]) == len(tasks)
        assert len(kernel["provenance"]) == len(tasks)
        assert all(item["verdict"] == "SUPPORTS" for item in kernel["provenance"])

        same, created_again = materialize_fact_kernel(
            conn,
            instance_id="alpha-local",
            signal_id=signal["signal_id"],
            engine_version=engine,
        )
        assert created_again is False and same["kernel_id"] == kernel["kernel_id"]
        assert list_fact_kernels(conn, instance_id="beta-local") == []

        beta_signal, _ = materialize_source_item(
            conn,
            instance_id="beta-local",
            source=discovery,
            item=SourceItem(
                source_id="neutral-discovery",
                external_id="2",
                url="https://news.example.test/beta",
                title="Second Board Announces 5% Change",
                fingerprint="beta-fact-source-item",
            ),
            engine_version=engine,
        )
        beta_tasks = resolve_signal(
            conn,
            instance_id="beta-local",
            signal_id=beta_signal["signal_id"],
            source_definitions=[discovery, primary],
            engine_version=engine,
        )
        beta_target = beta_tasks[0]["target_candidates"][0]["target_id"]
        for task in beta_tasks:
            verdict = "CONTRADICTS" if task is beta_tasks[0] else "SUPPORTS"
            record_verification_result(
                conn,
                instance_id="beta-local",
                task_id=task["task_id"],
                target_id=beta_target,
                verdict=verdict,
                evidence_url="https://authority.example.test/notices/2",
                evidence_fingerprint=f"beta-evidence-{task['claim_key']}",
                evidence_summary="Primary evidence checked",
                confidence=90,
                engine_version=engine,
            )
        try:
            materialize_fact_kernel(conn, instance_id="beta-local", signal_id=beta_signal["signal_id"], engine_version=engine)
        except FactKernelError as exc:
            assert "CONTRADICTED" in str(exc)
        else:
            raise AssertionError("contradicted signal materialized into a fact kernel")

        events = conn.execute(
            "SELECT event_type FROM runtime_events WHERE instance_id='alpha-local' AND aggregate_type IN ('verification_result','fact_kernel') ORDER BY event_id"
        ).fetchall()
        event_types = [row["event_type"] for row in events]
        assert "PRIMARY_EVIDENCE_RECORDED" in event_types
        assert event_types[-1] == "FACT_KERNEL_READY"
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_FACT_KERNEL_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("fact_kernel_engine is a library; use --self-test for validation")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
