from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from channel_provenance import ChannelProvenanceError, validate_recruitment_channel_id

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
ALLOWED_FORMS = {"AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class ResearchStorageError(RuntimeError):
    pass


class ResearchStorage(Protocol):
    def append(self, record: dict[str, Any], *, raw_bytes: bytes) -> str: ...
    def export(self, form_id: str) -> list[dict[str, Any]]: ...


def canonical_json_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def validate_record_envelope(record: dict[str, Any]) -> None:
    if record.get("research_id") != RESEARCH_ID:
        raise ResearchStorageError("research_id mismatch")
    if record.get("form_id") not in ALLOWED_FORMS:
        raise ResearchStorageError("unsupported form_id")
    if record.get("synthetic") is not False:
        raise ResearchStorageError("PROD storage rejects synthetic records")
    if not isinstance(record.get("response_id"), str) or not record["response_id"]:
        raise ResearchStorageError("response_id required")
    if not isinstance(record.get("received_at"), str) or not record["received_at"]:
        raise ResearchStorageError("received_at required")
    try:
        validate_recruitment_channel_id(record.get("recruitment_channel_id"))
    except ChannelProvenanceError as exc:
        raise ResearchStorageError(str(exc)) from exc


def validate_body_sha256(value: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ResearchStorageError("body_sha256 must be lowercase SHA-256 hex")


@dataclass
class SQLiteResearchStorage:
    """
    Test/reference adapter only. Production binding must use a separately
    secured research-only database and MUST NOT point to CRM storage.
    """

    db_path: Path
    allow_production: bool = False

    def __post_init__(self) -> None:
        if self.allow_production:
            raise ResearchStorageError("SQLite adapter is test/reference only")
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS research_responses (
                response_id TEXT PRIMARY KEY,
                research_id TEXT NOT NULL,
                form_id TEXT NOT NULL,
                received_at TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                normalized_sha256 TEXT NOT NULL,
                normalized_json TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS idempotency_receipts (
                response_id TEXT PRIMARY KEY,
                body_sha256 TEXT NOT NULL,
                normalized_sha256 TEXT NOT NULL,
                FOREIGN KEY(response_id) REFERENCES research_responses(response_id)
            )
            """
        )
        self.conn.commit()

    def append(self, record: dict[str, Any], *, raw_bytes: bytes) -> str:
        validate_record_envelope(record)
        normalized = canonical_json_bytes(record)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        normalized_sha = hashlib.sha256(normalized).hexdigest()
        try:
            self.conn.execute(
                """INSERT INTO research_responses
                   (response_id, research_id, form_id, received_at, raw_sha256, normalized_sha256, normalized_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["response_id"],
                    record["research_id"],
                    record["form_id"],
                    record["received_at"],
                    raw_sha,
                    normalized_sha,
                    normalized.decode("utf-8").rstrip("\n"),
                ),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            raise ResearchStorageError("duplicate response_id") from exc
        return normalized_sha

    def append_idempotent(
        self,
        record: dict[str, Any],
        *,
        raw_bytes: bytes,
        body_sha256: str,
    ) -> tuple[str, bool]:
        """Append once, or replay the original receipt for the same body.

        Returns (normalized_sha256, inserted). A reused response_id with a
        different canonical analytical body fails closed. The body digest and
        raw idempotency key never enter analytical exports.
        """
        validate_record_envelope(record)
        validate_body_sha256(body_sha256)

        existing = self.conn.execute(
            "SELECT body_sha256, normalized_sha256 FROM idempotency_receipts WHERE response_id = ?",
            (record["response_id"],),
        ).fetchone()
        if existing is not None:
            if existing[0] != body_sha256:
                raise ResearchStorageError("idempotency key reused with different body")
            response_exists = self.conn.execute(
                "SELECT 1 FROM research_responses WHERE response_id = ?",
                (record["response_id"],),
            ).fetchone()
            if response_exists is None:
                raise ResearchStorageError("idempotency receipt without analytical row")
            return str(existing[1]), False

        normalized = canonical_json_bytes(record)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        normalized_sha = hashlib.sha256(normalized).hexdigest()

        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.execute(
                """INSERT INTO research_responses
                   (response_id, research_id, form_id, received_at, raw_sha256, normalized_sha256, normalized_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    record["response_id"],
                    record["research_id"],
                    record["form_id"],
                    record["received_at"],
                    raw_sha,
                    normalized_sha,
                    normalized.decode("utf-8").rstrip("\n"),
                ),
            )
            self.conn.execute(
                """INSERT INTO idempotency_receipts
                   (response_id, body_sha256, normalized_sha256)
                   VALUES (?, ?, ?)""",
                (record["response_id"], body_sha256, normalized_sha),
            )
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            existing = self.conn.execute(
                "SELECT body_sha256, normalized_sha256 FROM idempotency_receipts WHERE response_id = ?",
                (record["response_id"],),
            ).fetchone()
            if existing is not None and existing[0] == body_sha256:
                return str(existing[1]), False
            if existing is not None:
                raise ResearchStorageError("idempotency key reused with different body") from exc
            raise ResearchStorageError("inconsistent duplicate response_id without idempotency receipt") from exc
        except Exception:
            self.conn.rollback()
            raise

        return normalized_sha, True

    def export(self, form_id: str) -> list[dict[str, Any]]:
        if form_id not in ALLOWED_FORMS:
            raise ResearchStorageError("unsupported form_id")
        rows = self.conn.execute(
            """SELECT normalized_json FROM research_responses
               WHERE research_id = ? AND form_id = ?
               ORDER BY received_at, response_id""",
            (RESEARCH_ID, form_id),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]
