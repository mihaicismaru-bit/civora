#!/usr/bin/env python3
"""Site-owned Signal Engine for LOCAL NEWS OS vNext.

Consumes normalized SourceItem objects and persists discovery signals into the
site runtime database. A signal is never publication authority and never a
fact kernel. It only captures provenance plus deterministic hints for later
primary-source resolution.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from runtime_store import connect, initialize, register_instance, utc_now
from source_adapters import SourceDefinition, SourceItem

SIGNAL_STATE = "DISCOVERED"
PUBLICATION_AUTHORITY = "NONE"
MAX_HINTS = 32


class SignalEngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class SignalCandidate:
    signal_id: str
    instance_id: str
    source_id: str
    source_role: str
    source_item_fingerprint: str
    source_url: str
    source_title: str
    source_published_at: str | None
    claim_hints: tuple[dict[str, Any], ...]
    entity_hints: tuple[dict[str, Any], ...]
    fingerprint: str
    publication_authority: str = PUBLICATION_AUTHORITY
    material_fact_ready: bool = False
    fact_kernel_ready: bool = False

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["claim_hints"] = list(self.claim_hints)
        data["entity_hints"] = list(self.entity_hints)
        return data


def build_signal(*, instance_id: str, source: SourceDefinition, item: SourceItem) -> SignalCandidate:
    if not instance_id:
        raise SignalEngineError("instance_id is required")
    if item.source_id != source.source_id:
        raise SignalEngineError("source item/source definition mismatch")
    if not item.fingerprint:
        raise SignalEngineError("source item fingerprint is required")
    signal_id = hashlib.sha256(
        f"{instance_id}\n{source.source_id}\n{item.fingerprint}".encode("utf-8")
    ).hexdigest()[:24]
    fingerprint = hashlib.sha256(
        f"{instance_id}\n{item.fingerprint}".encode("utf-8")
    ).hexdigest()
    return SignalCandidate(
        signal_id=signal_id,
        instance_id=instance_id,
        source_id=source.source_id,
        source_role=source.role,
        source_item_fingerprint=item.fingerprint,
        source_url=item.url,
        source_title=item.title,
        source_published_at=item.published_at,
        claim_hints=tuple(_claim_hints(item)),
        entity_hints=tuple(_entity_hints(item)),
        fingerprint=fingerprint,
    )


def _claim_hints(item: SourceItem) -> list[dict[str, Any]]:
    text = " ".join(filter(None, (item.title, item.summary)))
    hints: list[dict[str, Any]] = [
        {
            "kind": "HEADLINE_ASSERTION",
            "text": item.title,
            "verification_required": True,
            "material_fact_ready": False,
        }
    ]
    token_patterns = (
        ("PERCENT", r"(?<!\w)[+-]?\d+(?:[.,]\d+)?\s*%"),
        ("MONEY", r"(?<!\w)\d[\d .]*(?:[.,]\d+)?\s*(?:lei|ron|eur|euro|€)(?!\w)"),
        ("DATE", r"(?<!\d)\d{1,2}[./-]\d{1,2}[./-]\d{2,4}(?!\d)"),
        ("NUMBER", r"(?<!\w)\d+(?:[.,]\d+)?(?!\w)"),
    )
    seen: set[tuple[str, str]] = set()
    for kind, pattern in token_patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            value = re.sub(r"\s+", " ", match.group(0)).strip()
            key = (kind, value.casefold())
            if key in seen:
                continue
            seen.add(key)
            hints.append(
                {
                    "kind": kind,
                    "text": value,
                    "verification_required": True,
                    "material_fact_ready": False,
                }
            )
            if len(hints) >= MAX_HINTS:
                return hints
    return hints


def _entity_hints(item: SourceItem) -> list[dict[str, Any]]:
    title = item.title
    words = re.findall(r"[^\W\d_][\w'’.-]*", title, flags=re.UNICODE)
    candidates: list[str] = []
    current: list[str] = []
    for word in words:
        first_alpha = next((c for c in word if c.isalpha()), "")
        looks_named = bool(first_alpha and first_alpha.isupper())
        looks_acronym = len(word) > 1 and any(c.isalpha() for c in word) and word.upper() == word
        if looks_named or looks_acronym:
            current.append(word)
        else:
            if current:
                candidates.append(" ".join(current))
                current = []
    if current:
        candidates.append(" ".join(current))

    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text in candidates:
        normalized = text.strip(" .,-")
        if not normalized or len(normalized) < 2:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(
            {
                "kind": "UNRESOLVED_MENTION",
                "text": normalized,
                "resolution_required": True,
            }
        )
        if len(output) >= MAX_HINTS:
            break
    return output


def persist_signal(
    conn: sqlite3.Connection,
    *,
    signal: SignalCandidate,
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    """Persist idempotently. Returns (row, created_now)."""
    if signal.publication_authority != PUBLICATION_AUTHORITY:
        raise SignalEngineError("signals cannot carry publication authority")
    now = utc_now()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT * FROM signals
            WHERE instance_id=? AND source_id=? AND source_item_fingerprint=?
            """,
            (signal.instance_id, signal.source_id, signal.source_item_fingerprint),
        ).fetchone()
        if existing is not None:
            conn.commit()
            return _decode_row(existing), False

        conn.execute(
            """
            INSERT INTO signals(
                instance_id, signal_id, fingerprint, source_id, source_role,
                source_item_fingerprint, source_url, source_title, source_published_at,
                state, publication_authority, material_fact_ready, fact_kernel_ready,
                claim_hints_json, entity_hints_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'NONE', 0, 0, ?, ?, ?, ?)
            """,
            (
                signal.instance_id,
                signal.signal_id,
                signal.fingerprint,
                signal.source_id,
                signal.source_role,
                signal.source_item_fingerprint,
                signal.source_url,
                signal.source_title,
                signal.source_published_at,
                SIGNAL_STATE,
                json.dumps(list(signal.claim_hints), ensure_ascii=False, sort_keys=True),
                json.dumps(list(signal.entity_hints), ensure_ascii=False, sort_keys=True),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO runtime_events(
                instance_id, aggregate_type, aggregate_id, event_type,
                from_state, to_state, reason, payload_json, engine_version, created_at
            ) VALUES (?, 'signal', ?, 'SIGNAL_DISCOVERED', NULL, 'DISCOVERED',
                      'normalized source item materialized', ?, ?, ?)
            """,
            (
                signal.instance_id,
                signal.signal_id,
                json.dumps(
                    {
                        "source_id": signal.source_id,
                        "source_item_fingerprint": signal.source_item_fingerprint,
                        "publication_authority": "NONE",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                engine_version,
                now,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return get_signal(conn, instance_id=signal.instance_id, signal_id=signal.signal_id), True


def materialize_source_item(
    conn: sqlite3.Connection,
    *,
    instance_id: str,
    source: SourceDefinition,
    item: SourceItem,
    engine_version: str,
) -> tuple[dict[str, Any], bool]:
    return persist_signal(
        conn,
        signal=build_signal(instance_id=instance_id, source=source, item=item),
        engine_version=engine_version,
    )


def get_signal(conn: sqlite3.Connection, *, instance_id: str, signal_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM signals WHERE instance_id=? AND signal_id=?",
        (instance_id, signal_id),
    ).fetchone()
    if row is None:
        raise SignalEngineError("signal not found for instance")
    return _decode_row(row)


def list_signals(
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
            SELECT * FROM signals
            WHERE instance_id=? AND state=?
            ORDER BY updated_at DESC, signal_id ASC
            LIMIT ?
            """,
            (instance_id, state, bounded),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT * FROM signals
            WHERE instance_id=?
            ORDER BY updated_at DESC, signal_id ASC
            LIMIT ?
            """,
            (instance_id, bounded),
        ).fetchall()
    return [_decode_row(row) for row in rows]


def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["claim_hints"] = json.loads(data.pop("claim_hints_json"))
    data["entity_hints"] = json.loads(data.pop("entity_hints_json"))
    data["material_fact_ready"] = bool(data["material_fact_ready"])
    data["fact_kernel_ready"] = bool(data["fact_kernel_ready"])
    return data


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
        engine = "vnext-signal-test"
        register_instance(conn, _manifest("alpha-local", "alpha.invalid", "a" * 64), engine_version=engine)
        register_instance(conn, _manifest("beta-local", "beta.invalid", "b" * 64), engine_version=engine)

        source = SourceDefinition.from_dict(
            {
                "source_id": "fixture-feed",
                "adapter": "RSS_ATOM",
                "role": "DISCOVERY",
                "url": "https://example.test/feed",
                "config": {},
            }
        )
        item = SourceItem(
            source_id="fixture-feed",
            external_id="1",
            url="https://example.test/story",
            title="City Hall Approves 12.5% Increase Worth 20,000 EUR",
            published_at="2026-08-19T08:00:00Z",
            summary="Decision dated 19.08.2026.",
            fingerprint="source-item-fingerprint",
        )

        alpha, created = materialize_source_item(
            conn,
            instance_id="alpha-local",
            source=source,
            item=item,
            engine_version=engine,
        )
        assert created is True
        assert alpha["state"] == "DISCOVERED"
        assert alpha["publication_authority"] == "NONE"
        assert alpha["material_fact_ready"] is False
        assert alpha["fact_kernel_ready"] is False
        assert any(h["kind"] == "PERCENT" for h in alpha["claim_hints"])
        assert any(h["kind"] == "MONEY" for h in alpha["claim_hints"])
        assert all(h.get("verification_required") for h in alpha["claim_hints"])
        assert all(h["kind"] == "UNRESOLVED_MENTION" for h in alpha["entity_hints"])

        same, created_again = materialize_source_item(
            conn,
            instance_id="alpha-local",
            source=source,
            item=item,
            engine_version=engine,
        )
        assert created_again is False
        assert same["signal_id"] == alpha["signal_id"]
        assert conn.execute(
            "SELECT COUNT(*) FROM signals WHERE instance_id='alpha-local'"
        ).fetchone()[0] == 1
        assert conn.execute(
            """SELECT COUNT(*) FROM runtime_events
               WHERE instance_id='alpha-local' AND aggregate_type='signal'"""
        ).fetchone()[0] == 1

        beta, beta_created = materialize_source_item(
            conn,
            instance_id="beta-local",
            source=source,
            item=item,
            engine_version=engine,
        )
        assert beta_created is True
        assert beta["signal_id"] != alpha["signal_id"]
        assert len(list_signals(conn, instance_id="alpha-local")) == 1
        assert len(list_signals(conn, instance_id="beta-local")) == 1

        try:
            bad = SignalCandidate(
                signal_id="bad",
                instance_id="alpha-local",
                source_id="fixture-feed",
                source_role="DISCOVERY",
                source_item_fingerprint="bad-fp",
                source_url="https://example.test/bad",
                source_title="Bad",
                source_published_at=None,
                claim_hints=(),
                entity_hints=(),
                fingerprint="bad",
                publication_authority="STORY_READY",
            )
            persist_signal(conn, signal=bad, engine_version=engine)
        except SignalEngineError:
            pass
        else:
            raise AssertionError("signal with publication authority was accepted")

        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_SIGNAL_ENGINE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("signal_engine is a library; use --self-test for validation")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
