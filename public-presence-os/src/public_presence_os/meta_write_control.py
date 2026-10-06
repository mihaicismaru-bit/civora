from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Mapping, Protocol

from .control import canonical_json


class MetaWriteHold(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise MetaWriteHold("HOLD_WRITE_TIMESTAMP_INVALID") from exc
    if parsed.tzinfo is None:
        raise MetaWriteHold("HOLD_WRITE_TIMESTAMP_INVALID")
    return parsed.astimezone(timezone.utc)


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class WriteAuthorityReceipt:
    receipt_id: str
    owner: str
    identity: str
    action_classes: tuple[str, ...]
    issued_at: str
    expires_at: str
    nonce: str
    body_sha256: str


def validate_authority_receipt(
    value: Mapping[str, Any], *, now_utc: str, expected_owner: str = "Mihai Cismaru"
) -> WriteAuthorityReceipt:
    required = {"receipt_id", "owner", "identity", "action_classes", "issued_at", "expires_at", "nonce", "body_sha256"}
    if set(value) != required:
        raise MetaWriteHold("HOLD_WRITE_AUTHORITY_RECEIPT_SHAPE")
    body = dict(value)
    claimed = body.pop("body_sha256")
    if claimed != _hash(body):
        raise MetaWriteHold("HOLD_WRITE_AUTHORITY_RECEIPT_HASH")
    if value["owner"] != expected_owner or value["identity"] != "Mihai Cismaru":
        raise MetaWriteHold("HOLD_WRITE_AUTHORITY_IDENTITY")
    issued = _parse_utc(str(value["issued_at"]))
    expires = _parse_utc(str(value["expires_at"]))
    now = _parse_utc(now_utc)
    if issued > now or expires <= now or expires <= issued:
        raise MetaWriteHold("HOLD_WRITE_AUTHORITY_STALE")
    actions = value["action_classes"]
    if not isinstance(actions, list) or not actions or any(not isinstance(item, str) for item in actions):
        raise MetaWriteHold("HOLD_WRITE_AUTHORITY_ACTIONS")
    return WriteAuthorityReceipt(
        receipt_id=str(value["receipt_id"]), owner=str(value["owner"]), identity=str(value["identity"]),
        action_classes=tuple(actions), issued_at=str(value["issued_at"]), expires_at=str(value["expires_at"]),
        nonce=str(value["nonce"]), body_sha256=str(claimed),
    )


@dataclass(frozen=True)
class ControlledWriteIntent:
    idempotency_key: str
    action_class: str
    platform: str
    payload_sha256: str
    rights_evidence_sha256: str
    approval_id: str
    approval_expires_at: str


@dataclass(frozen=True)
class ExternalWriteResult:
    external_id: str
    receipt: Mapping[str, Any]


class WriteTransport(Protocol):
    def execute(self, intent: ControlledWriteIntent) -> ExternalWriteResult: ...


class WriteLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS controlled_writes (
                    idempotency_key TEXT PRIMARY KEY,
                    intent_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    external_id TEXT,
                    receipt_json TEXT,
                    hold_reason TEXT
                );
                CREATE TABLE IF NOT EXISTS controlled_write_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                """
            )

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=1.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def row(self, key: str):
        with self.connect() as connection:
            return connection.execute(
                "SELECT intent_sha256,state,external_id,receipt_json,hold_reason FROM controlled_writes WHERE idempotency_key=?",
                (key,),
            ).fetchone()

    def events(self, key: str) -> tuple[str, ...]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT event_type FROM controlled_write_events WHERE idempotency_key=? ORDER BY sequence", (key,)
            ).fetchall()
        return tuple(row[0] for row in rows)


class ControlledWriter:
    def __init__(
        self,
        *,
        ledger: WriteLedger,
        transport: WriteTransport,
        readback: Callable[[str], bool],
        authority: WriteAuthorityReceipt,
        external_green_actions: tuple[str, ...],
        kill_switch_engaged: Callable[[], bool],
        live_write_enabled: Callable[[], bool],
    ) -> None:
        self.ledger = ledger
        self.transport = transport
        self.readback = readback
        self.authority = authority
        self.external_green_actions = external_green_actions
        self.kill_switch_engaged = kill_switch_engaged
        self.live_write_enabled = live_write_enabled

    def _gates(self, intent: ControlledWriteIntent, now_utc: str) -> None:
        if self.kill_switch_engaged() or not self.live_write_enabled():
            raise MetaWriteHold("HOLD_WRITE_KILL_SWITCH_OR_LIVE_WRITE")
        if intent.action_class not in self.external_green_actions:
            raise MetaWriteHold("HOLD_WRITE_ACTION_NOT_GREEN")
        if intent.action_class not in self.authority.action_classes:
            raise MetaWriteHold("HOLD_WRITE_ACTION_NOT_AUTHORIZED")
        if _parse_utc(self.authority.expires_at) <= _parse_utc(now_utc):
            raise MetaWriteHold("HOLD_WRITE_AUTHORITY_STALE")
        if _parse_utc(intent.approval_expires_at) <= _parse_utc(now_utc):
            raise MetaWriteHold("HOLD_WRITE_APPROVAL_STALE")
        if (
            len(intent.payload_sha256) != 64
            or len(intent.rights_evidence_sha256) != 64
            or not intent.idempotency_key
            or not intent.approval_id
        ):
            raise MetaWriteHold("HOLD_WRITE_INTENT_INVALID")

    def execute(self, intent: ControlledWriteIntent, *, now_utc: str) -> dict[str, Any]:
        self._gates(intent, now_utc)
        intent_hash = _hash(asdict(intent))
        existing = self.ledger.row(intent.idempotency_key)
        if existing:
            if existing[0] != intent_hash:
                raise MetaWriteHold("HOLD_WRITE_IDEMPOTENCY_CONFLICT")
            if existing[1] == "CONFIRMED":
                return {"state": "DUPLICATE_NOOP", "external_id": existing[2]}
            raise MetaWriteHold("HOLD_WRITE_PREVIOUS_ATTEMPT_UNCONFIRMED")

        try:
            with self.ledger.connect() as connection:
                connection.execute(
                    "INSERT INTO controlled_writes(idempotency_key,intent_sha256,state) VALUES(?,?,?)",
                    (intent.idempotency_key, intent_hash, "PREPARED"),
                )
                connection.execute(
                    "INSERT INTO controlled_write_events(idempotency_key,event_type,event_json) VALUES(?,?,?)",
                    (intent.idempotency_key, "PRE_WRITE", canonical_json({"intent_sha256": intent_hash, "approval_id": intent.approval_id})),
                )
        except sqlite3.Error as exc:
            raise MetaWriteHold("HOLD_WRITE_DB_CONTENTION") from exc

        if self.kill_switch_engaged():
            self._hold(intent.idempotency_key, "HOLD_WRITE_KILL_SWITCH_MID_QUEUE")
            raise MetaWriteHold("HOLD_WRITE_KILL_SWITCH_MID_QUEUE")
        try:
            result = self.transport.execute(intent)
        except Exception:
            self._hold(intent.idempotency_key, "HOLD_WRITE_AMBIGUOUS_RESULT")
            raise MetaWriteHold("HOLD_WRITE_AMBIGUOUS_RESULT") from None
        if not result.external_id:
            self._hold(intent.idempotency_key, "HOLD_WRITE_RECEIPT_MISSING_EXTERNAL_ID")
            raise MetaWriteHold("HOLD_WRITE_RECEIPT_MISSING_EXTERNAL_ID")

        with self.ledger.connect() as connection:
            connection.execute(
                "UPDATE controlled_writes SET state=?,external_id=?,receipt_json=? WHERE idempotency_key=?",
                ("SENT_UNCONFIRMED", result.external_id, canonical_json(result.receipt), intent.idempotency_key),
            )
            connection.execute(
                "INSERT INTO controlled_write_events(idempotency_key,event_type,event_json) VALUES(?,?,?)",
                (intent.idempotency_key, "API_RECEIPT", canonical_json({"external_id": result.external_id})),
            )
        if not self.readback(result.external_id):
            self._hold(intent.idempotency_key, "HOLD_WRITE_READBACK_FAILED")
            raise MetaWriteHold("HOLD_WRITE_READBACK_FAILED")
        with self.ledger.connect() as connection:
            connection.execute(
                "UPDATE controlled_writes SET state=? WHERE idempotency_key=?", ("CONFIRMED", intent.idempotency_key)
            )
            connection.execute(
                "INSERT INTO controlled_write_events(idempotency_key,event_type,event_json) VALUES(?,?,?)",
                (intent.idempotency_key, "POST_WRITE_CONFIRMED", canonical_json({"external_id": result.external_id})),
            )
        return {"state": "CONFIRMED", "external_id": result.external_id}

    def _hold(self, key: str, reason: str) -> None:
        with self.ledger.connect() as connection:
            connection.execute(
                "UPDATE controlled_writes SET state=?,hold_reason=? WHERE idempotency_key=?", ("HOLD", reason, key)
            )
            connection.execute(
                "INSERT INTO controlled_write_events(idempotency_key,event_type,event_json) VALUES(?,?,?)",
                (key, "HOLD", canonical_json({"reason": reason})),
            )


def promotion_evidence(
    *,
    stage: str,
    read_ingestion_pass: bool,
    identity_binding_pass: bool,
    shadow_acceptance_pass: bool,
    calibration_pass: bool,
    kill_switch_pass: bool,
    idempotency_pass: bool,
    retry_exhaustion_pass: bool,
    authorization_receipt_pass: bool,
) -> dict[str, Any]:
    checks = {
        "real_read_ingestion": read_ingestion_pass,
        "identity_binding": identity_binding_pass,
        "shadow_acceptance": shadow_acceptance_pass,
        "calibration": calibration_pass,
        "kill_switch": kill_switch_pass,
        "idempotency": idempotency_pass,
        "retry_exhaustion": retry_exhaustion_pass,
        "authorization_receipt": authorization_receipt_pass,
    }
    ready = all(value is True for key, value in checks.items() if key != "authorization_receipt")
    accepted = ready and authorization_receipt_pass is True
    target = (
        "LIMITED_WRITE" if accepted else
        "READY_FOR_LIMITED_WRITE_APPROVAL" if ready else "HOLD_READINESS_EVIDENCE_INCOMPLETE"
    )
    body = {"from_stage": stage, "target_stage": target, "checks": checks, "accepted": accepted}
    body["evidence_sha256"] = _hash(body)
    return body
