# CIVORA Checkpoint 0055 — Resolution Audit Inspection

Status: CLOSED_VALIDATED

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

## Validation

GitHub Actions workflow run `31181149845` completed successfully for head `8d1cf32c6b6f510ebdb1aa268eedc853ecfe1c78`.

The full cross-platform test matrix passed, closing the CI gate that was pending when checkpoint 0055 was first written.

## Gates

- RECOVERY_EVENT_INSPECTION: PASS
- TRANSACTION_DETAIL_INSPECTION: PASS
- RESOLUTION_AUDIT_READ_ONLY_STATUS: PASS
- MISSING_MIRROR_DETECTION: PASS
- ORPHAN_AUDIT_VISIBILITY: PASS
- IDEMPOTENT_PROGRAMMATIC_RECONCILIATION: PASS
- SILENT_AUDIT_DELETION: ABSENT
- CROSS_PLATFORM_TEST_MATRIX: PASS

## Remaining backlog at closure

1. Durable Fact Kernel.
2. Claim/evidence reconciliation.
3. Editorial approval state machine.
4. Expanded operator runbooks.

## Closure

Checkpoint 0055 is `CLOSED_VALIDATED`. Development proceeded into the accelerated editorial-engine phase with checkpoint 0056.
