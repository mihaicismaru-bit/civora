#!/usr/bin/env python3
"""Generic fail-closed persistence writer for CIVORA / LOCAL NEWS OS.

The writer deliberately separates product runtime success from persistence sync
success. External connector adapters provide the actual revision-controlled
write/readback functions. A failed or unavailable persistence transport never
becomes a synchronized state claim; it returns a durable failure receipt while
allowing the caller's product runtime to continue.

No instance identity, geography, source, brand, credential value, or provider-
specific API is embedded here. Active-state callers must already hold the
namespace writer lease and provide the exact holder/token proof at runtime.
"""
from __future__ import annotations

import argparse
import hashlib
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Callable

from credential_safety import CONTRACT as CREDENTIAL_SAFETY_CONTRACT, find_credential_value_violations


SCHEMA_VERSION = "1.0"
CONTRACT = "CIVORA_PERSISTENCE_WRITER_V1"
PERSISTENCE_FRESH = "PERSISTENCE_FRESH"
PERSISTENCE_STALE = "PERSISTENCE_STALE"
PERSISTENCE_BLOCKED = "PERSISTENCE_BLOCKED"


@dataclass(frozen=True)
class LeaseProof:
    status: str
    holder: str
    lease_token: str
    observed_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class WriteRequest:
    namespace: str
    target_id: str
    required_revision_id: str
    content: str
    holder: str
    lease_token: str


@dataclass(frozen=True)
class TransportWriteResult:
    ok: bool
    revision_id: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class TransportReadResult:
    ok: bool
    revision_id: str | None = None
    content: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class WriteReceipt:
    schema_version: str
    contract: str
    namespace: str
    target_id: str
    outcome: str
    persistence_health: str
    synchronized: bool
    runtime_may_continue: bool
    reason: str
    expected_content_sha256: str
    written_revision_id: str | None
    readback_revision_id: str | None

    def to_dict(self) -> dict:
        return asdict(self)


WriteFn = Callable[[str, str, str], TransportWriteResult]
ReadFn = Callable[[str], TransportReadResult]


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _receipt(
    request: WriteRequest,
    *,
    outcome: str,
    persistence_health: str,
    synchronized: bool,
    reason: str,
    written_revision_id: str | None = None,
    readback_revision_id: str | None = None,
) -> WriteReceipt:
    return WriteReceipt(
        schema_version=SCHEMA_VERSION,
        contract=CONTRACT,
        namespace=request.namespace,
        target_id=request.target_id,
        outcome=outcome,
        persistence_health=persistence_health,
        synchronized=synchronized,
        runtime_may_continue=True,
        reason=reason,
        expected_content_sha256=_sha256(request.content),
        written_revision_id=written_revision_id,
        readback_revision_id=readback_revision_id,
    )


def _lease_is_owned(request: WriteRequest, lease: LeaseProof) -> bool:
    return (
        lease.status == "HELD"
        and bool(request.namespace.strip())
        and bool(request.target_id.strip())
        and bool(request.required_revision_id.strip())
        and request.holder == lease.holder
        and request.lease_token == lease.lease_token
        and bool(request.lease_token)
        and lease.observed_at <= lease.expires_at
    )


def write_fail_closed(
    request: WriteRequest,
    lease: LeaseProof,
    *,
    write_fn: WriteFn,
    read_fn: ReadFn,
) -> WriteReceipt:
    """Attempt one revision-controlled target write and exact readback.

    The function never reports synchronization unless all of the following are
    true: the caller proves current lease ownership; the payload contains no
    credential value; the transport accepts the supplied required revision; the
    write returns a new revision; the target is read back successfully; the
    readback revision equals the written revision; and the readback content is
    byte-for-byte identical as UTF-8 text.

    Transport failures are fail-closed but non-fatal to the product runtime:
    callers receive ``PERSISTENCE_STALE`` and ``runtime_may_continue=True``.
    Lease/ownership or credential-safety failures are ``PERSISTENCE_BLOCKED``
    and perform no write.
    """
    if not _lease_is_owned(request, lease):
        return _receipt(
            request,
            outcome="BLOCKED",
            persistence_health=PERSISTENCE_BLOCKED,
            synchronized=False,
            reason="LEASE_OWNERSHIP_NOT_PROVEN",
        )

    credential_violations = find_credential_value_violations(request.content)
    if credential_violations:
        return _receipt(
            request,
            outcome="BLOCKED",
            persistence_health=PERSISTENCE_BLOCKED,
            synchronized=False,
            reason=f"CREDENTIAL_VALUE_FORBIDDEN:{CREDENTIAL_SAFETY_CONTRACT}:{len(credential_violations)}",
        )

    try:
        written = write_fn(request.target_id, request.content, request.required_revision_id)
    except Exception:
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason="WRITE_TRANSPORT_UNAVAILABLE",
        )

    if not written.ok:
        reason = "WRITE_REJECTED"
        if written.error_code:
            reason += f":{written.error_code}"
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason=reason,
            written_revision_id=written.revision_id,
        )
    if not written.revision_id:
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason="WRITE_REVISION_MISSING",
        )

    try:
        readback = read_fn(request.target_id)
    except Exception:
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason="READBACK_TRANSPORT_UNAVAILABLE",
            written_revision_id=written.revision_id,
        )

    if not readback.ok:
        reason = "READBACK_REJECTED"
        if readback.error_code:
            reason += f":{readback.error_code}"
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason=reason,
            written_revision_id=written.revision_id,
            readback_revision_id=readback.revision_id,
        )

    if readback.revision_id != written.revision_id:
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason="READBACK_REVISION_MISMATCH",
            written_revision_id=written.revision_id,
            readback_revision_id=readback.revision_id,
        )

    if readback.content is None or _sha256(readback.content) != _sha256(request.content):
        return _receipt(
            request,
            outcome="STALE",
            persistence_health=PERSISTENCE_STALE,
            synchronized=False,
            reason="READBACK_CONTENT_MISMATCH",
            written_revision_id=written.revision_id,
            readback_revision_id=readback.revision_id,
        )

    return _receipt(
        request,
        outcome="SYNCED",
        persistence_health=PERSISTENCE_FRESH,
        synchronized=True,
        reason="WRITE_AND_EXACT_READBACK_VERIFIED",
        written_revision_id=written.revision_id,
        readback_revision_id=readback.revision_id,
    )


def self_test() -> int:
    observed = datetime.fromisoformat("2026-08-17T11:00:00+00:00")
    lease = LeaseProof(
        status="HELD",
        holder="self-test-writer",
        lease_token="self-test-token",
        observed_at=observed,
        expires_at=datetime.fromisoformat("2026-08-17T11:08:00+00:00"),
    )
    request = WriteRequest(
        namespace="test-instance",
        target_id="current-state",
        required_revision_id="rev-1",
        content="state: current\n",
        holder=lease.holder,
        lease_token=lease.lease_token,
    )

    memory = {"revision": "rev-1", "content": "state: old\n"}
    received_required_revision: list[str] = []

    def ok_write(target_id: str, content: str, required_revision_id: str) -> TransportWriteResult:
        assert target_id == request.target_id
        received_required_revision.append(required_revision_id)
        assert required_revision_id == memory["revision"]
        memory["content"] = content
        memory["revision"] = "rev-2"
        return TransportWriteResult(True, revision_id="rev-2")

    def ok_read(target_id: str) -> TransportReadResult:
        assert target_id == request.target_id
        return TransportReadResult(True, revision_id=memory["revision"], content=memory["content"])

    success = write_fail_closed(request, lease, write_fn=ok_write, read_fn=ok_read)
    assert success.synchronized is True
    assert success.persistence_health == PERSISTENCE_FRESH
    assert success.outcome == "SYNCED"
    assert success.runtime_may_continue is True
    assert received_required_revision == ["rev-1"]

    def unavailable_write(_target_id: str, _content: str, _required_revision_id: str) -> TransportWriteResult:
        raise OSError("external persistence unavailable")

    stale = write_fail_closed(request, lease, write_fn=unavailable_write, read_fn=ok_read)
    assert stale.synchronized is False
    assert stale.persistence_health == PERSISTENCE_STALE
    assert stale.reason == "WRITE_TRANSPORT_UNAVAILABLE"
    assert stale.runtime_may_continue is True

    def conflict_write(_target_id: str, _content: str, _required_revision_id: str) -> TransportWriteResult:
        return TransportWriteResult(False, error_code="REVISION_CONFLICT")

    conflict = write_fail_closed(request, lease, write_fn=conflict_write, read_fn=ok_read)
    assert conflict.synchronized is False
    assert conflict.persistence_health == PERSISTENCE_STALE
    assert conflict.reason == "WRITE_REJECTED:REVISION_CONFLICT"

    def mismatch_write(_target_id: str, _content: str, _required_revision_id: str) -> TransportWriteResult:
        return TransportWriteResult(True, revision_id="rev-3")

    def mismatch_read(_target_id: str) -> TransportReadResult:
        return TransportReadResult(True, revision_id="rev-3", content="different\n")

    mismatch = write_fail_closed(request, lease, write_fn=mismatch_write, read_fn=mismatch_read)
    assert mismatch.synchronized is False
    assert mismatch.persistence_health == PERSISTENCE_STALE
    assert mismatch.reason == "READBACK_CONTENT_MISMATCH"

    credential_write_called = False

    def must_not_write_credential(_target_id: str, _content: str, _required_revision_id: str) -> TransportWriteResult:
        nonlocal credential_write_called
        credential_write_called = True
        return TransportWriteResult(True, revision_id="impossible")

    unsafe_request = WriteRequest(
        namespace=request.namespace,
        target_id=request.target_id,
        required_revision_id=request.required_revision_id,
        content='{"credential_reference_names":["SOCIAL_ACCESS_TOKEN"],"access_token":"runtime-secret"}',
        holder=request.holder,
        lease_token=request.lease_token,
    )
    credential_blocked = write_fail_closed(
        unsafe_request,
        lease,
        write_fn=must_not_write_credential,
        read_fn=ok_read,
    )
    assert credential_blocked.synchronized is False
    assert credential_blocked.persistence_health == PERSISTENCE_BLOCKED
    assert credential_blocked.reason.startswith("CREDENTIAL_VALUE_FORBIDDEN:")
    assert "runtime-secret" not in credential_blocked.reason
    assert credential_write_called is False

    write_called = False

    def must_not_write(_target_id: str, _content: str, _required_revision_id: str) -> TransportWriteResult:
        nonlocal write_called
        write_called = True
        return TransportWriteResult(True, revision_id="impossible")

    foreign_lease = LeaseProof(
        status="HELD",
        holder="other-writer",
        lease_token="other-token",
        observed_at=observed,
        expires_at=datetime.fromisoformat("2026-08-17T11:08:00+00:00"),
    )
    blocked = write_fail_closed(request, foreign_lease, write_fn=must_not_write, read_fn=ok_read)
    assert blocked.synchronized is False
    assert blocked.persistence_health == PERSISTENCE_BLOCKED
    assert blocked.reason == "LEASE_OWNERSHIP_NOT_PROVEN"
    assert write_called is False

    print("CIVORA generic persistence writer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    parser.error("This module is a library contract. Use --self-test or call write_fail_closed from an adapter.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
