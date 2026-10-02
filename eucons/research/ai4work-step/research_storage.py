from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from channel_provenance import ChannelProvenanceError, validate_recruitment_channel_id

RESEARCH_ID = "AI4WORK-STEP-NF-RUN-001"
ALLOWED_FORMS = {"AI4WORK_ADULTS_V1", "AI4WORK_EMPLOYERS_V1"}
ALLOWED_RIGHTS_HOLDS = {"RESTRICTED_PENDING_REVIEW", "OBJECTED_PENDING_REVIEW"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_ERASURE_REPLAY_TTL = timedelta(hours=24)


class ResearchStorageError(RuntimeError):
    pass


class ResearchStorage(Protocol):
    def append(self, record: dict[str, Any], *, raw_bytes: bytes) -> str: ...
    def export(self, form_id: str) -> list[dict[str, Any]]: ...
    def get_by_response_id(self, response_id: str) -> dict[str, Any] | None: ...
    def delete_by_response_id(self, response_id: str) -> bool: ...
    def set_analysis_hold(self, response_id: str, hold_state: str) -> bool: ...
    def clear_analysis_hold(self, response_id: str) -> bool: ...
    def get_analysis_hold(self, response_id: str) -> str | None: ...


def canonical_json_bytes(record: dict[str, Any]) -> bytes:
    return (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def validate_record_envelope(record: dict[str, Any]) -> None:
    if record.get("research_id") != RESEARCH_ID:
        raise ResearchStorageError("research_id mismatch")
    if record.get("form_id") not in ALLOWED_FORMS:
        raise ResearchStorageError("unsupported form_id")
    if record.get("synthetic") is not False:
        raise ResearchStorageError("PROD storage rejects synthetic records")
    response_id = record.get("response_id")
    if not isinstance(response_id, str) or not SHA256_RE.fullmatch(response_id):
        raise ResearchStorageError("response_id must be opaque lowercase SHA-256 hex")
    if not isinstance(record.get("received_at"), str) or not record["received_at"]:
        raise ResearchStorageError("received_at required")
    try:
        validate_recruitment_channel_id(record.get("recruitment_channel_id"))
    except ChannelProvenanceError as exc:
        raise ResearchStorageError(str(exc)) from exc


def validate_body_sha256(value: str) -> None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise ResearchStorageError("body_sha256 must be lowercase SHA-256 hex")


def validate_response_id(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ResearchStorageError("response_id lookup value invalid")
    return value


def validate_hold_state(value: Any) -> str:
    if value not in ALLOWED_RIGHTS_HOLDS:
        raise ResearchStorageError("unsupported rights analysis hold")
    return str(value)


def parse_utc_boundary(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ResearchStorageError("erasure replay retention boundary must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ResearchStorageError("erasure replay retention boundary must include timezone")
    return parsed.astimezone(timezone.utc)


@dataclass
class SQLiteResearchStorage:
    """
    Test/reference adapter only. Production binding must use a separately
    secured research-only database and MUST NOT point to CRM storage.

    Erasure replay suppression has deliberately no default retention. A finite
    UTC not-after cap must be injected by the approved live binding before an
    erasure can create a replay marker. Every marker receives its own bounded
    expires_at_utc no later than erasure + 24 hours; expiry metadata stays in
    the non-analytical rights-control table and never enters analytical export.
    """

    db_path: Path
    allow_production: bool = False
    erasure_replay_not_after_utc: str | None = None

    def __post_init__(self) -> None:
        if self.allow_production:
            raise ResearchStorageError("SQLite adapter is test/reference only")
        self._erasure_replay_max_not_after = parse_utc_boundary(self.erasure_replay_not_after_utc)
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
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS rights_analysis_holds (
                response_id TEXT PRIMARY KEY,
                hold_state TEXT NOT NULL CHECK(
                    hold_state IN ('RESTRICTED_PENDING_REVIEW', 'OBJECTED_PENDING_REVIEW')
                ),
                FOREIGN KEY(response_id) REFERENCES research_responses(response_id)
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS erasure_replay_blocks (
                response_id TEXT PRIMARY KEY,
                expires_at_utc TEXT NOT NULL
            )
            """
        )
        replay_columns = {
            str(row[1])
            for row in self.conn.execute("PRAGMA table_info(erasure_replay_blocks)").fetchall()
        }
        if "expires_at_utc" not in replay_columns:
            legacy_count = int(
                self.conn.execute("SELECT COUNT(*) FROM erasure_replay_blocks").fetchone()[0]
            )
            if legacy_count:
                raise ResearchStorageError(
                    "legacy erasure replay markers without per-marker expiry require manual disposal"
                )
            self.conn.execute("ALTER TABLE erasure_replay_blocks ADD COLUMN expires_at_utc TEXT")
        self.conn.commit()

    @staticmethod
    def _normalise_now(now_utc: datetime | None = None) -> datetime:
        now = now_utc or datetime.now(timezone.utc)
        if now.tzinfo is None:
            raise ResearchStorageError("erasure replay clock must include timezone")
        return now.astimezone(timezone.utc)

    def _new_erasure_replay_expiry(self, *, now_utc: datetime | None = None) -> datetime:
        cap = self._erasure_replay_max_not_after
        if cap is None:
            raise ResearchStorageError("erasure replay retention boundary required before erasure")
        now = self._normalise_now(now_utc)
        if now >= cap:
            raise ResearchStorageError("erasure replay retention boundary already expired")
        expires_at = min(now + MAX_ERASURE_REPLAY_TTL, cap)
        if expires_at <= now:
            raise ResearchStorageError("erasure replay retention boundary must be in the future")
        return expires_at

    def _purge_expired_erasure_replay_blocks(self, *, now_utc: datetime | None = None) -> int:
        now = self._normalise_now(now_utc)
        rows = self.conn.execute(
            "SELECT response_id, expires_at_utc FROM erasure_replay_blocks"
        ).fetchall()
        expired: list[str] = []
        for response_id, expires_at_utc in rows:
            expiry = parse_utc_boundary(expires_at_utc)
            if expiry is None:
                raise ResearchStorageError("erasure replay marker missing per-marker expiry")
            if expiry <= now:
                expired.append(str(response_id))
        if not expired:
            return 0
        self.conn.executemany(
            "DELETE FROM erasure_replay_blocks WHERE response_id = ?",
            [(response_id,) for response_id in expired],
        )
        return len(expired)

    def expire_erasure_replay_blocks(self, *, now_utc: datetime | None = None) -> int:
        """Delete only replay markers whose own expires_at_utc has elapsed."""
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            deleted = self._purge_expired_erasure_replay_blocks(now_utc=now_utc)
            self.conn.commit()
            return deleted
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def _erasure_replay_blocked(self, response_id: str) -> bool:
        self._purge_expired_erasure_replay_blocks()
        return self.conn.execute(
            "SELECT 1 FROM erasure_replay_blocks WHERE response_id = ?",
            (response_id,),
        ).fetchone() is not None

    def append(self, record: dict[str, Any], *, raw_bytes: bytes) -> str:
        validate_record_envelope(record)
        normalized = canonical_json_bytes(record)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        normalized_sha = hashlib.sha256(normalized).hexdigest()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            if self._erasure_replay_blocked(record["response_id"]):
                raise ResearchStorageError("erased response replay blocked")
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
            self.conn.rollback()
            raise ResearchStorageError("duplicate response_id") from exc
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
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
        different canonical analytical body fails closed. A response_id that
        was erased is blocked only until its own finite per-marker expiry. The
        body digest and raw idempotency key never enter analytical exports.
        """
        validate_record_envelope(record)
        validate_body_sha256(body_sha256)

        normalized = canonical_json_bytes(record)
        raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        normalized_sha = hashlib.sha256(normalized).hexdigest()

        try:
            self.conn.execute("BEGIN IMMEDIATE")
            if self._erasure_replay_blocked(record["response_id"]):
                raise ResearchStorageError("erased response replay blocked")

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
                self.conn.commit()
                return str(existing[1]), False

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
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

        return normalized_sha, True

    def get_by_response_id(self, response_id: str) -> dict[str, Any] | None:
        """Locate one analytical record by its opaque technical receipt only."""
        receipt = validate_response_id(response_id)
        row = self.conn.execute(
            """SELECT normalized_json FROM research_responses
               WHERE research_id = ? AND response_id = ?""",
            (RESEARCH_ID, receipt),
        ).fetchone()
        return None if row is None else json.loads(row[0])

    def set_analysis_hold(self, response_id: str, hold_state: str) -> bool:
        """Exclude a live record from analytical export while a rights case is pending.

        Only an opaque response receipt and a bounded state enum are stored in
        the research database. Case narrative/identity belongs in the separate
        privacy-request administration store, never in research analytics.
        """
        receipt = validate_response_id(response_id)
        state = validate_hold_state(hold_state)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            exists = self.conn.execute(
                "SELECT 1 FROM research_responses WHERE research_id = ? AND response_id = ?",
                (RESEARCH_ID, receipt),
            ).fetchone()
            if exists is None:
                self.conn.rollback()
                return False
            self.conn.execute(
                """INSERT INTO rights_analysis_holds(response_id, hold_state)
                   VALUES (?, ?)
                   ON CONFLICT(response_id) DO UPDATE SET hold_state = excluded.hold_state""",
                (receipt, state),
            )
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def clear_analysis_hold(self, response_id: str) -> bool:
        """Clear a previously approved restriction/objection hold by receipt."""
        receipt = validate_response_id(response_id)
        deleted = self.conn.execute(
            "DELETE FROM rights_analysis_holds WHERE response_id = ?",
            (receipt,),
        ).rowcount
        self.conn.commit()
        return deleted == 1

    def get_analysis_hold(self, response_id: str) -> str | None:
        receipt = validate_response_id(response_id)
        row = self.conn.execute(
            "SELECT hold_state FROM rights_analysis_holds WHERE response_id = ?",
            (receipt,),
        ).fetchone()
        return None if row is None else str(row[0])

    def delete_by_response_id(self, response_id: str) -> bool:
        """Atomically erase a live analytical row and block stale replay resurrection."""
        receipt = validate_response_id(response_id)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            exists = self.conn.execute(
                "SELECT 1 FROM research_responses WHERE research_id = ? AND response_id = ?",
                (RESEARCH_ID, receipt),
            ).fetchone()
            if exists is None:
                self.conn.rollback()
                return False
            expires_at = self._new_erasure_replay_expiry()
            self.conn.execute(
                """INSERT OR IGNORE INTO erasure_replay_blocks(response_id, expires_at_utc)
                   VALUES (?, ?)""",
                (receipt, expires_at.isoformat()),
            )
            self.conn.execute(
                "DELETE FROM rights_analysis_holds WHERE response_id = ?",
                (receipt,),
            )
            self.conn.execute(
                "DELETE FROM idempotency_receipts WHERE response_id = ?",
                (receipt,),
            )
            deleted = self.conn.execute(
                "DELETE FROM research_responses WHERE research_id = ? AND response_id = ?",
                (RESEARCH_ID, receipt),
            ).rowcount
            if deleted != 1:
                raise ResearchStorageError("rights erasure did not delete exactly one analytical row")
            self.conn.commit()
            return True
        except Exception:
            self.conn.rollback()
            raise

    def export(self, form_id: str) -> list[dict[str, Any]]:
        if form_id not in ALLOWED_FORMS:
            raise ResearchStorageError("unsupported form_id")
        rows = self.conn.execute(
            """SELECT r.normalized_json
               FROM research_responses AS r
               LEFT JOIN rights_analysis_holds AS h ON h.response_id = r.response_id
               WHERE r.research_id = ? AND r.form_id = ? AND h.response_id IS NULL
               ORDER BY r.received_at, r.response_id""",
            (RESEARCH_ID, form_id),
        ).fetchall()
        return [json.loads(row[0]) for row in rows]
