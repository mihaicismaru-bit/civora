#!/usr/bin/env python3
"""Fail-closed PRS-040 gate for latest-current-state promotion.

A persistence transport write is not enough to advance durable current state.
The caller must present the exact receipt emitted by the generic persistence
writer after successful readback.  This gate refuses promotion unless the
receipt proves the same namespace, target, payload hash, written revision and
readback revision, and the writer marked the operation synchronized.

The module is provider- and instance-agnostic.  It does not perform external
writes and grants no LIVE/publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime

from persistence_writer import (
    CONTRACT as WRITER_CONTRACT,
    PERSISTENCE_FRESH,
    LeaseProof,
    TransportReadResult,
    TransportWriteResult,
    WriteReceipt,
    WriteRequest,
    write_fail_closed,
)


SCHEMA_VERSION = "1.0"
CONTRACT = "CIVORA_PERSISTENCE_LATEST_STATE_PROMOTION_V1"


@dataclass(frozen=True)
class PromotionRequest:
    namespace: str
    target_id: str
    content: str
    write_receipt: WriteReceipt


@dataclass(frozen=True)
class PromotionDecision:
    schema_version: str
    contract: str
    promotable: bool
    reason: str
    namespace: str
    target_id: str
    expected_content_sha256: str
    verified_revision_id: str | None

    def to_dict(self) -> dict:
        return asdict(self)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _decision(
    request: PromotionRequest,
    *,
    promotable: bool,
    reason: str,
    verified_revision_id: str | None = None,
) -> PromotionDecision:
    return PromotionDecision(
        schema_version=SCHEMA_VERSION,
        contract=CONTRACT,
        promotable=promotable,
        reason=reason,
        namespace=request.namespace,
        target_id=request.target_id,
        expected_content_sha256=_sha256(request.content),
        verified_revision_id=verified_revision_id,
    )


def verify_latest_current_state(request: PromotionRequest) -> PromotionDecision:
    """Return promotable only for an exact readback-verified writer receipt."""
    receipt = request.write_receipt

    if receipt.contract != WRITER_CONTRACT:
        return _decision(request, promotable=False, reason="WRITER_CONTRACT_MISMATCH")
    if not request.namespace.strip() or receipt.namespace != request.namespace:
        return _decision(request, promotable=False, reason="NAMESPACE_MISMATCH")
    if not request.target_id.strip() or receipt.target_id != request.target_id:
        return _decision(request, promotable=False, reason="TARGET_MISMATCH")
    if receipt.expected_content_sha256 != _sha256(request.content):
        return _decision(request, promotable=False, reason="CONTENT_HASH_MISMATCH")
    if receipt.outcome != "SYNCED":
        return _decision(request, promotable=False, reason="WRITE_NOT_SYNCED")
    if receipt.persistence_health != PERSISTENCE_FRESH:
        return _decision(request, promotable=False, reason="PERSISTENCE_NOT_FRESH")
    if receipt.synchronized is not True:
        return _decision(request, promotable=False, reason="SYNCHRONIZED_PROOF_MISSING")
    if receipt.reason != "WRITE_AND_EXACT_READBACK_VERIFIED":
        return _decision(request, promotable=False, reason="READBACK_PROOF_REASON_MISSING")
    if not receipt.written_revision_id:
        return _decision(request, promotable=False, reason="WRITTEN_REVISION_MISSING")
    if not receipt.readback_revision_id:
        return _decision(request, promotable=False, reason="READBACK_REVISION_MISSING")
    if receipt.readback_revision_id != receipt.written_revision_id:
        return _decision(request, promotable=False, reason="READBACK_REVISION_MISMATCH")

    return _decision(
        request,
        promotable=True,
        reason="EXACT_READBACK_VERIFIED_FOR_LATEST_STATE",
        verified_revision_id=receipt.readback_revision_id,
    )


def self_test() -> int:
    observed = datetime.fromisoformat("2026-08-17T13:00:00+00:00")
    lease = LeaseProof(
        status="HELD",
        holder="prs-040-self-test",
        lease_token="prs-040-token",
        observed_at=observed,
        expires_at=datetime.fromisoformat("2026-08-17T13:08:00+00:00"),
    )
    request = WriteRequest(
        namespace="test-instance",
        target_id="project-current-state",
        required_revision_id="rev-10",
        content="state: new\n",
        holder=lease.holder,
        lease_token=lease.lease_token,
    )
    memory = {"revision": "rev-10", "content": "state: old\n"}

    def write_ok(target_id: str, content: str, required_revision_id: str) -> TransportWriteResult:
        assert target_id == request.target_id
        assert required_revision_id == memory["revision"]
        memory["content"] = content
        memory["revision"] = "rev-11"
        return TransportWriteResult(True, revision_id="rev-11")

    def read_ok(target_id: str) -> TransportReadResult:
        assert target_id == request.target_id
        return TransportReadResult(True, revision_id=memory["revision"], content=memory["content"])

    receipt = write_fail_closed(request, lease, write_fn=write_ok, read_fn=read_ok)
    promoted = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id=request.target_id,
            content=request.content,
            write_receipt=receipt,
        )
    )
    assert promoted.promotable is True
    assert promoted.verified_revision_id == "rev-11"

    wrong_payload = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id=request.target_id,
            content="state: different\n",
            write_receipt=receipt,
        )
    )
    assert wrong_payload.promotable is False
    assert wrong_payload.reason == "CONTENT_HASH_MISMATCH"

    foreign_target = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id="another-target",
            content=request.content,
            write_receipt=receipt,
        )
    )
    assert foreign_target.promotable is False
    assert foreign_target.reason == "TARGET_MISMATCH"

    stale_receipt = WriteReceipt(
        schema_version=receipt.schema_version,
        contract=receipt.contract,
        namespace=receipt.namespace,
        target_id=receipt.target_id,
        outcome="STALE",
        persistence_health="PERSISTENCE_STALE",
        synchronized=False,
        runtime_may_continue=True,
        reason="READBACK_CONTENT_MISMATCH",
        expected_content_sha256=receipt.expected_content_sha256,
        written_revision_id="rev-11",
        readback_revision_id="rev-11",
    )
    stale = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id=request.target_id,
            content=request.content,
            write_receipt=stale_receipt,
        )
    )
    assert stale.promotable is False
    assert stale.reason == "WRITE_NOT_SYNCED"

    forged_revision = WriteReceipt(
        schema_version=receipt.schema_version,
        contract=receipt.contract,
        namespace=receipt.namespace,
        target_id=receipt.target_id,
        outcome="SYNCED",
        persistence_health=PERSISTENCE_FRESH,
        synchronized=True,
        runtime_may_continue=True,
        reason="WRITE_AND_EXACT_READBACK_VERIFIED",
        expected_content_sha256=receipt.expected_content_sha256,
        written_revision_id="rev-11",
        readback_revision_id="rev-12",
    )
    mismatch = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id=request.target_id,
            content=request.content,
            write_receipt=forged_revision,
        )
    )
    assert mismatch.promotable is False
    assert mismatch.reason == "READBACK_REVISION_MISMATCH"

    def write_bad_readback(_target_id: str, content: str, _required_revision_id: str) -> TransportWriteResult:
        memory["content"] = content
        memory["revision"] = "rev-12"
        return TransportWriteResult(True, revision_id="rev-12")

    def read_bad(_target_id: str) -> TransportReadResult:
        return TransportReadResult(True, revision_id="rev-12", content="tampered\n")

    bad_receipt = write_fail_closed(request, lease, write_fn=write_bad_readback, read_fn=read_bad)
    rejected = verify_latest_current_state(
        PromotionRequest(
            namespace=request.namespace,
            target_id=request.target_id,
            content=request.content,
            write_receipt=bad_receipt,
        )
    )
    assert rejected.promotable is False
    assert bad_receipt.synchronized is False

    print("CIVORA PRS-040 latest-state readback promotion self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("This module is a library contract. Use --self-test or call verify_latest_current_state.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
