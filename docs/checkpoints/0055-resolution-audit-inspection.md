# CIVORA Checkpoint 0055 — Resolution Audit Inspection

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the remaining observability gap in the operational control surface: operators must be able to inspect recovery events, inspect an individual transaction, and prove whether durable dead-letter resolution history is fully represented in the global Recovery Event Ledger.

## Implementation

### TransactionJournal audit API

Added `resolution_audit_status(recovery_ledger)` as a read-only consistency check between transaction `resolution_history` and `RecoveryEventLedger` resolution events.

The status reports:

- `expected_count`
- `mirrored_count`
- `missing_event_ids`
- `orphan_event_ids`
- `consistent`

Missing events indicate a repairable cross-store crash gap. Orphan events indicate global resolution evidence with no matching durable transaction-history entry and are treated as inconsistent rather than silently deleted.

Added `reconcile_resolution_audit(recovery_ledger)` as an idempotent programmatic repair path for missing mirrors. It reuses the existing deterministic event identities and `mirror_resolution_events()` behavior. It never deletes orphan audit evidence.

### Operational CLI

Added read-only commands:

```text
civora --state-dir <path> recovery-events [filters]
civora --state-dir <path> transaction <transaction-id>
civora --state-dir <path> resolution-audit
```

`recovery-events` supports component, event-type, status and bounded tail filtering. `transaction` returns the full durable transaction record. `resolution-audit` returns exit code 0 only when the two durable audit sources agree; an inconsistency returns the existing unhealthy exit code 2.

No automatic deletion or destructive audit repair command was added to the CLI.

## Validation added

`tests/test_cli.py` now covers:

- recovery-event filtering and limit behavior;
- transaction detail inspection;
- detection of a missing resolution mirror;
- successful idempotent reconciliation through the programmatic API;
- healthy audit status after reconciliation;
- visibility of orphan resolution events.

## Gates

- RECOVERY_EVENT_INSPECTION: PASS_IMPLEMENTATION
- TRANSACTION_DETAIL_INSPECTION: PASS_IMPLEMENTATION
- RESOLUTION_AUDIT_READ_ONLY_STATUS: PASS_IMPLEMENTATION
- MISSING_MIRROR_DETECTION: PASS_IMPLEMENTATION
- ORPHAN_AUDIT_VISIBILITY: PASS_IMPLEMENTATION
- IDEMPOTENT_PROGRAMMATIC_RECONCILIATION: PASS_IMPLEMENTATION
- SILENT_AUDIT_DELETION: ABSENT
- CROSS_PLATFORM_TEST_MATRIX: PENDING_CURRENT_CI

## Remaining backlog

1. Complete CI validation for checkpoint 0055.
2. Begin durable Fact Kernel implementation.
3. Add claim/evidence reconciliation on top of Fact Kernel.
4. Add editorial approval state machine.
5. Expand operator documentation and runtime runbooks after the Fact Kernel interfaces stabilize.

## Next action

If CI is green, start the durable Fact Kernel with deterministic fact identity, provenance/evidence references, atomic persistence, validation, and tests. If CI fails, the failing regression remains priority 1.
