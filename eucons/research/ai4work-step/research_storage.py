from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
ALLOWED_FORMS = {"AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"}


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
