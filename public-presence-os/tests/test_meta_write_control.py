from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3

import pytest

from public_presence_os.control import canonical_json
from public_presence_os.meta_write_control import (
    ControlledWriteIntent,
    ControlledWriter,
    ExternalWriteResult,
    MetaWriteHold,
    WriteLedger,
    promotion_evidence,
    validate_authority_receipt,
)


NOW = "2026-10-03T10:00:00Z"


def authority(actions=("TEST_GREEN",)):
    body = {
        "receipt_id": "owner-authorization-001",
        "owner": "Mihai Cismaru",
        "identity": "Mihai Cismaru",
        "action_classes": list(actions),
        "issued_at": "2026-10-03T09:00:00Z",
        "expires_at": "2026-10-04T09:00:00Z",
        "nonce": "explicit-owner-acknowledgement-001",
    }
    body["body_sha256"] = sha256(canonical_json(body).encode()).hexdigest()
    return validate_authority_receipt(body, now_utc=NOW)


def intent(key="idem-1", action="TEST_GREEN", expiry="2026-10-03T11:00:00Z"):
    return ControlledWriteIntent(
        idempotency_key=key,
        action_class=action,
        platform="THREADS",
        payload_sha256="a" * 64,
        rights_evidence_sha256="b" * 64,
        approval_id="approval-1",
        approval_expires_at=expiry,
    )


class Transport:
    def __init__(self, outcome=None):
        self.calls = 0
        self.outcome = outcome or ExternalWriteResult("external-1", {"id": "external-1"})

    def execute(self, _intent):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def writer(tmp_path, transport, *, kill=False, live=True, readback=True, actions=("TEST_GREEN",)):
    return ControlledWriter(
        ledger=WriteLedger(tmp_path / "writes.sqlite3"),
        transport=transport,
        readback=lambda _external_id: readback,
        authority=authority(actions),
        external_green_actions=("TEST_GREEN",),
        kill_switch_engaged=lambda: kill,
        live_write_enabled=lambda: live,
    )


def test_confirmed_write_has_pre_receipt_readback_post_and_duplicate_noop(tmp_path):
    transport = Transport()
    controlled = writer(tmp_path, transport)
    assert controlled.execute(intent(), now_utc=NOW)["state"] == "CONFIRMED"
    assert controlled.execute(intent(), now_utc=NOW)["state"] == "DUPLICATE_NOOP"
    assert transport.calls == 1
    assert controlled.ledger.events("idem-1") == ("PRE_WRITE", "API_RECEIPT", "POST_WRITE_CONFIRMED")


@pytest.mark.parametrize(
    "case,kwargs,expected",
    [
        ("expired_token", {"outcome": TimeoutError()}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("revoked_permission", {"outcome": PermissionError()}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("http_429", {"outcome": RuntimeError("429")}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("http_5xx", {"outcome": RuntimeError("503")}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("timeout_before_write", {"outcome": TimeoutError()}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("timeout_after_write", {"outcome": TimeoutError()}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("ack_lost", {"outcome": TimeoutError()}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
        ("invalid_media", {"outcome": ValueError("invalid")}, "HOLD_WRITE_AMBIGUOUS_RESULT"),
    ],
)
def test_ambiguous_or_failed_external_attempt_never_retries(tmp_path, case, kwargs, expected):
    transport = Transport(**kwargs)
    controlled = writer(tmp_path / case, transport)
    with pytest.raises(MetaWriteHold, match=expected):
        controlled.execute(intent(key=case), now_utc=NOW)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_PREVIOUS_ATTEMPT_UNCONFIRMED"):
        controlled.execute(intent(key=case), now_utc=NOW)
    assert transport.calls == 1


def test_kill_switch_stale_approval_and_missing_authority_prevent_transport(tmp_path):
    transport = Transport()
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_KILL_SWITCH_OR_LIVE_WRITE"):
        writer(tmp_path / "kill", transport, kill=True).execute(intent(), now_utc=NOW)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_APPROVAL_STALE"):
        writer(tmp_path / "stale", transport).execute(intent(expiry="2026-10-03T09:30:00Z"), now_utc=NOW)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_ACTION_NOT_AUTHORIZED"):
        writer(tmp_path / "auth", transport, actions=("OTHER",)).execute(intent(), now_utc=NOW)
    assert transport.calls == 0


def test_kill_switch_engaged_mid_queue_holds_before_transport(tmp_path):
    states = iter((False, True))
    transport = Transport()
    controlled = ControlledWriter(
        ledger=WriteLedger(tmp_path / "writes.sqlite3"),
        transport=transport,
        readback=lambda _external_id: True,
        authority=authority(),
        external_green_actions=("TEST_GREEN",),
        kill_switch_engaged=lambda: next(states),
        live_write_enabled=lambda: True,
    )
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_KILL_SWITCH_MID_QUEUE"):
        controlled.execute(intent(), now_utc=NOW)
    assert transport.calls == 0
    assert controlled.ledger.events("idem-1") == ("PRE_WRITE", "HOLD")


def test_expired_authority_and_missing_rights_evidence_fail_closed(tmp_path):
    transport = Transport()
    controlled = writer(tmp_path / "authority", transport)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_AUTHORITY_STALE"):
        controlled.execute(intent(), now_utc="2026-10-05T10:00:00Z")
    missing_rights = ControlledWriteIntent(**{**intent().__dict__, "rights_evidence_sha256": ""})
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_INTENT_INVALID"):
        writer(tmp_path / "rights", transport).execute(missing_rights, now_utc=NOW)
    assert transport.calls == 0


def test_db_contention_holds_before_transport(tmp_path, monkeypatch):
    transport = Transport()
    controlled = writer(tmp_path, transport)
    original_connect = controlled.ledger.connect
    calls = 0

    def fail_second_connect():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("database is locked")
        return original_connect()

    monkeypatch.setattr(controlled.ledger, "connect", fail_second_connect)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_DB_CONTENTION"):
        controlled.execute(intent(), now_utc=NOW)
    assert transport.calls == 0


def test_readback_failure_holds_and_never_retries(tmp_path):
    transport = Transport()
    controlled = writer(tmp_path, transport, readback=False)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_READBACK_FAILED"):
        controlled.execute(intent(), now_utc=NOW)
    with pytest.raises(MetaWriteHold, match="HOLD_WRITE_PREVIOUS_ATTEMPT_UNCONFIRMED"):
        controlled.execute(intent(), now_utc=NOW)
    assert transport.calls == 1


def test_no_production_external_green_action_and_transition_stops_for_authorization():
    policy = json.loads((Path(__file__).parents[1] / "config" / "meta_action_risk_policy.json").read_text())
    assert policy["external_green_actions"] == []
    evidence = promotion_evidence(
        stage="SHADOW_REAL",
        read_ingestion_pass=True,
        identity_binding_pass=True,
        shadow_acceptance_pass=True,
        calibration_pass=True,
        kill_switch_pass=True,
        idempotency_pass=True,
        retry_exhaustion_pass=True,
        authorization_receipt_pass=False,
    )
    assert evidence["accepted"] is False
    assert evidence["target_stage"] == "READY_FOR_LIMITED_WRITE_APPROVAL"


@pytest.mark.parametrize("missing", ["read_ingestion_pass", "identity_binding_pass", "shadow_acceptance_pass",
                                     "calibration_pass", "kill_switch_pass", "idempotency_pass", "retry_exhaustion_pass"])
def test_missing_readiness_evidence_never_requests_write_approval(missing):
    checks = dict(read_ingestion_pass=True, identity_binding_pass=True, shadow_acceptance_pass=True,
                  calibration_pass=True, kill_switch_pass=True, idempotency_pass=True,
                  retry_exhaustion_pass=True, authorization_receipt_pass=True)
    checks[missing] = False
    evidence = promotion_evidence(stage="SHADOW_REAL", **checks)
    assert evidence["accepted"] is False
    assert evidence["target_stage"] == "HOLD_READINESS_EVIDENCE_INCOMPLETE"
