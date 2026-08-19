#!/usr/bin/env python3
"""Site-owned runtime database primitives for LOCAL NEWS OS vNext.

This module intentionally writes runtime state only to a database connection.
It has no repository-state writer and no locality-specific behavior.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "local-news-os" / "vnext" / "runtime" / "schema.sql"

STORY_STATES = {
    "DISCOVERED",
    "RESOLVING",
    "VERIFIED",
    "FACT_KERNEL_READY",
    "STORY_DRAFTED",
    "QA_PASSED",
    "PUBLISHED",
    "MEDIA_READY",
    "DISTRIBUTED",
    "HOLD",
    "RETRY",
    "REJECTED",
    "BLOCKED_EXTERNAL",
    "HUMAN_REVIEW",
}


class RuntimeStoreError(RuntimeError):
    pass


class RevisionConflict(RuntimeStoreError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def register_instance(
    conn: sqlite3.Connection,
    manifest: dict[str, Any],
    *,
    engine_version: str,
) -> None:
    runtime = manifest.get("runtime") or {}
    if runtime.get("owner") != "site_application":
        raise RuntimeStoreError("SITE_OWNS_RUNTIME violation")
    if runtime.get("repository_runtime_state_enabled") is not False:
        raise RuntimeStoreError("repository runtime state must be disabled")
    instance_id = manifest.get("instance_id")
    publication = manifest.get("publication") or {}
    domain = publication.get("canonical_domain")
    config_sha = manifest.get("config_sha256")
    if not all(isinstance(v, str) and v for v in (instance_id, domain, config_sha, engine_version)):
        raise RuntimeStoreError("incomplete instance release manifest")
    now = utc_now()
    conn.execute(
        """
        INSERT INTO publication_instances(
            instance_id, canonical_domain, config_sha256, engine_version,
            runtime_owner, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'site_application', ?, ?)
        ON CONFLICT(instance_id) DO UPDATE SET
            canonical_domain=excluded.canonical_domain,
            config_sha256=excluded.config_sha256,
            engine_version=excluded.engine_version,
            runtime_owner='site_application',
            updated_at=excluded.updated_at
        """,
        (instance_id, domain, config_sha, engine_version, now, now),
    )
    conn.commit()


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
) -> int:
    cursor = conn.execute(
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
    return int(cursor.lastrowid)


def create_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    fingerprint: str,
    engine_version: str,
    headline: str | None = None,
) -> dict[str, Any]:
    if not story_id or not fingerprint:
        raise RuntimeStoreError("story_id and fingerprint are required")
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO stories(
                instance_id, story_id, fingerprint, state, revision,
                headline, created_at, updated_at
            ) VALUES (?, ?, ?, 'DISCOVERED', 1, ?, ?, ?)
            """,
            (instance_id, story_id, fingerprint, headline, now, now),
        )
        _append_event(
            conn,
            instance_id=instance_id,
            aggregate_type="story",
            aggregate_id=story_id,
            event_type="STORY_CREATED",
            to_state="DISCOVERED",
            engine_version=engine_version,
            payload={"fingerprint": fingerprint},
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_story(conn, instance_id=instance_id, story_id=story_id)


def get_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM stories WHERE instance_id=? AND story_id=?",
        (instance_id, story_id),
    ).fetchone()
    if row is None:
        raise RuntimeStoreError("story not found for instance")
    return dict(row)


def transition_story(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    story_id: str,
    to_state: str,
    engine_version: str,
    reason: str,
    expected_revision: int | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if to_state not in STORY_STATES:
        raise RuntimeStoreError(f"unknown story state: {to_state}")
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT state, revision FROM stories WHERE instance_id=? AND story_id=?",
            (instance_id, story_id),
        ).fetchone()
        if row is None:
            raise RuntimeStoreError("story not found for instance")
        current_state = str(row["state"])
        revision = int(row["revision"])
        if expected_revision is not None and revision != expected_revision:
            raise RevisionConflict(
                f"story revision conflict: expected {expected_revision}, found {revision}"
            )
        now = utc_now()
        cursor = conn.execute(
            """
            UPDATE stories
            SET state=?, revision=revision+1, updated_at=?
            WHERE instance_id=? AND story_id=? AND revision=?
            """,
            (to_state, now, instance_id, story_id, revision),
        )
        if cursor.rowcount != 1:
            raise RevisionConflict("story changed during transition")
        _append_event(
            conn,
            instance_id=instance_id,
            aggregate_type="story",
            aggregate_id=story_id,
            event_type="STORY_STATE_CHANGED",
            from_state=current_state,
            to_state=to_state,
            reason=reason,
            engine_version=engine_version,
            payload=payload,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_story(conn, instance_id=instance_id, story_id=story_id)


def list_events(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    aggregate_type: str,
    aggregate_id: str,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM runtime_events
        WHERE instance_id=? AND aggregate_type=? AND aggregate_id=?
        ORDER BY event_id ASC
        """,
        (instance_id, aggregate_type, aggregate_id),
    ).fetchall()
    return [dict(row) for row in rows]


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
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        engine = "vnext-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a" * 64), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b" * 64), engine_version=engine)

        create_story(
            conn,
            instance_id="alpha-local",
            story_id="shared-story-id",
            fingerprint="alpha-fingerprint",
            engine_version=engine,
        )
        create_story(
            conn,
            instance_id="beta-local",
            story_id="shared-story-id",
            fingerprint="beta-fingerprint",
            engine_version=engine,
        )

        first = transition_story(
            conn,
            instance_id="alpha-local",
            story_id="shared-story-id",
            to_state="RESOLVING",
            engine_version=engine,
            reason="self-test",
            expected_revision=1,
        )
        assert first["state"] == "RESOLVING"
        assert first["revision"] == 2
        second = get_story(conn, instance_id="beta-local", story_id="shared-story-id")
        assert second["state"] == "DISCOVERED"
        assert second["revision"] == 1

        events = list_events(
            conn,
            instance_id="alpha-local",
            aggregate_type="story",
            aggregate_id="shared-story-id",
        )
        assert [e["event_type"] for e in events] == ["STORY_CREATED", "STORY_STATE_CHANGED"]

        try:
            transition_story(
                conn,
                instance_id="alpha-local",
                story_id="shared-story-id",
                to_state="VERIFIED",
                engine_version=engine,
                reason="stale writer",
                expected_revision=1,
            )
        except RevisionConflict:
            pass
        else:
            raise AssertionError("stale runtime writer was accepted")

        try:
            conn.execute("UPDATE runtime_events SET reason='tamper' WHERE event_id=?", (events[0]["event_id"],))
        except sqlite3.DatabaseError:
            conn.rollback()
        else:
            raise AssertionError("append-only event ledger allowed UPDATE")

        try:
            conn.execute("DELETE FROM runtime_events WHERE event_id=?", (events[0]["event_id"],))
        except sqlite3.DatabaseError:
            conn.rollback()
        else:
            raise AssertionError("append-only event ledger allowed DELETE")

        try:
            create_story(
                conn,
                instance_id="alpha-local",
                story_id="duplicate-fingerprint",
                fingerprint="alpha-fingerprint",
                engine_version=engine,
            )
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("duplicate story fingerprint was accepted")

        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_RUNTIME_STORE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("runtime_store is a library; use --self-test for validation")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
