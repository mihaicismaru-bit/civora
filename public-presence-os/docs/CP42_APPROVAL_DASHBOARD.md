# CP42 — M12 Approval Dashboard Minimal Executable Slice

Status: internal/local-only executable source. No queue, publisher, network, account-connection, public-publish, or deploy authority.

## Input contract

M12 accepts only `VisualQAReport` values from M07 that pass exact model/version, authority, platform, state, report-ID and SHA-256 verification. The complete M07 HOLD set is immutable input to local review. A QA HOLD cannot be overridden by M12.

## Local state machine

Initial state is `PENDING_REVIEW` only for a clean M07 PASS with zero HOLDs; otherwise it is `HOLD_REVIEW`.

Supported decisions are `APPROVE_LOCAL`, `REJECT_LOCAL`, `ACKNOWLEDGE_HOLD`, `DEFER_LOCAL`, and `REOPEN_LOCAL`. `APPROVE_LOCAL` requires M07 PASS + zero HOLDs + `approval_input_ready=true`. Reports with HOLDs can be acknowledged, rejected or deferred, but cannot be approved.

All decisions append immutable SQLite events. Existing report rows and event rows are protected by no-update/no-delete triggers. Caller-supplied request IDs provide retry idempotency; reusing a request ID with different decision payload fails closed.

## Review receipt

`ApprovalReviewReceipt` binds the current local review state to the exact M07 report hash and latest append-only event. `queue_input_ready=true` can exist only after a clean local approval. It is a readiness signal for future M08 implementation, not queue authority. M12 always reports `queue_authority=false`, `publish_authority=false`, and `publish_eligible=false`.

## Dashboard

The dashboard renderer produces self-contained static HTML from the exact report and append-only local event history. It lists every QA HOLD reason and escapes operator-controlled text. It contains no scripts, remote assets, network calls, account controls, or publishing controls.

## Preserved pilot blocker

The current M07 contract still emits `HOLD_IDENTITY_EQUIVALENCE` because exact historical CP29 font hashes remain unavailable. M12 surfaces and persists that HOLD; it cannot approve through it. Pilot identity therefore remains fail-closed until the evidence is recovered or a later explicit versioned identity supersession is canonized.

## Next dependency

M08 Queue is next. It may later consume only a hash-bound M12 receipt satisfying the queue-input contract. CP42 itself performs zero queue mutations.
