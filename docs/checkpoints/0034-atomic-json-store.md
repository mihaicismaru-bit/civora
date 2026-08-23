# CIVORA Checkpoint 0034 — Atomic JSON Store

State: CODE_COMPLETE_INTEGRATION_PENDING

## Completed

- Added `civora.persistence.AtomicJsonStore`.
- Added payload checksums and schema validation.
- Added fsync-backed atomic replacement.
- Added previous-generation backup retention.
- Added automatic recovery from a valid backup.
- Added fail-closed behavior when both generations are invalid.

## Completed gates

- reusable persistence primitive: PASS
- checksum integrity: PASS by implementation review
- atomic replacement: PASS by implementation review
- backup recovery path: PASS by implementation review
- fail-closed path: PASS by implementation review

## Remaining backlog

1. Migrate `SourceRegistry` to `AtomicJsonStore`.
2. Migrate `ReviewQueue` to `AtomicJsonStore`.
3. Refactor `SignalStore` to use the shared primitive.
4. Add cross-process locking around read-modify-write operations.
5. Add coordinated transactions between signal, story and review state.
6. Run CI on Python 3.11–3.13.

## Blockers

- GitHub Actions has not emitted a workflow run for the current PR.
- Native Windows validation requires a Windows runner.
- Repository visibility is public; credentials and operational secrets must remain external.

## Next action

Migrate Source Registry and Review Queue to the shared atomic store and add corruption/recovery tests for both components.
