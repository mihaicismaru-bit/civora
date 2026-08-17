# CIVORA persistence reconciliation engine acceptance

This increment implements the executable core required by PRS-016–024 and the explicit acceptance cases required by PRS-042–049.

## Authority boundaries

- **Drive/persisted state** supplies prior decisions, capability claims and backlog state.
- **Repository evidence** supplies implementation state (`MERGED`, `OPEN_PR`, `DRAFT_PR`, `CLOSED_UNMERGED`, `ABSENT`, `SUPERSEDED`) and runtime mode.
- **External evidence** supplies remote/live confirmation independently from local readiness.
- The engine is advisory and pure: it writes only its requested output file and never mutates Drive, GitHub state, external accounts or publication state.

## Required fail-closed behavior

1. An open/draft/closed-unmerged PR cannot reconcile to `IMPLEMENTED`.
2. A merged implementation can repair a stale persisted `ACTIVE_UNIMPLEMENTED` claim and emits `FALSE_NEGATIVE_PERSISTENCE`.
3. A persisted `IMPLEMENTED` claim without current merged evidence is downgraded and emits `FALSE_POSITIVE_PERSISTENCE`.
4. Superseded work becomes `SUPERSEDED` and remains traceable.
5. An outbox-only runtime cannot reconcile to direct publication.
6. Local `READY` cannot reconcile to external/live without confirmed external evidence.
7. Missing external evidence defaults to `UNCONFIRMED`.
8. Unknown implementation states fail closed.
9. Identical normalized inputs must produce byte-stable semantic output and identical fingerprints.
10. `PERSISTENCE_FRESH` is possible only when every required freshness gate is true, no blocking reconciliation diagnostic remains, and repository scope is not `STRUCTURAL_RECONCILIATION`.
11. **PRS-042:** when persisted/Drive state is older than current main and current main contains merged implementation evidence, repository evidence remains authoritative; the input is not mutated, the stale decision reconciles forward to `IMPLEMENTED`, `FALSE_NEGATIVE_PERSISTENCE` is emitted, and persistence health remains `RECONCILIATION_REQUIRED` until the corrected state is separately persisted under the writer lease.
12. **PRS-043:** repository evidence that exists only as an `OPEN_PR` or `DRAFT_PR` never reconciles to `IMPLEMENTED`. With no explicit partial implementation evidence the decision remains `ACTIVE_UNIMPLEMENTED`; with explicit `partial_evidence=true`, `PARTIAL` is permitted. PR existence, branch existence, CI success or a locally READY asset is insufficient to infer merge/implementation.
13. **PRS-044:** when an older PR is explicitly superseded by a later merged replacement, the older decision reconciles to `SUPERSEDED`, keeps its `superseded_by` lineage and is removed from the active backlog. The later replacement reconciles independently from `MERGED` evidence to `IMPLEMENTED`; the old PR never reactivates merely because its historical branch/PR evidence still exists.
14. **PRS-045:** an implemented/READY social adapter whose runtime is `OUTBOX_ONLY` or `DURABLE_OUTBOX_ONLY` reconciles to capability `PARTIAL`, `direct_or_outbox=OUTBOX_ONLY`, and `direct publication=false`. A stale persisted `DIRECT` claim emits `FALSE_POSITIVE_PERSISTENCE`; adapter code readiness alone cannot imply direct publication.
15. **PRS-046:** a profile asset/configuration that is locally `READY` with direct-capable runtime but has no remote readback remains capability `PARTIAL` with `external_state=UNCONFIRMED` and `gap=EXTERNAL_CONFIRMATION_GAP`. A stale persisted `LIVE_CONFIRMED` claim emits `FALSE_POSITIVE_PERSISTENCE`; local asset readiness never implies external LIVE.
16. **PRS-047:** a `NO_PROGRESS_HISTORICAL_STATE` checkpoint remains immutable historical context after a later implementation is merged on main. The checkpoint is not rewritten or promoted to resume authority; current reconciled truth advances to the newer main/`IMPLEMENTED` decision, the stale checkpoint-derived backlog item is removed, and persistence remains `RECONCILIATION_REQUIRED` until the advanced current state is separately persisted under the writer lease.
17. **PRS-048:** when current evidence explicitly replaces an old active decision with a newer not-yet-implemented decision, the old decision reconciles to `SUPERSEDED` with `superseded_by` lineage, its stale backlog is retired, and the replacement remains `ACTIVE_UNIMPLEMENTED` with an active backlog item. The replacement relationship alone must not make the new decision `IMPLEMENTED`, and the changed active binding remains `RECONCILIATION_REQUIRED` until separately persisted and read back under the writer lease.
18. **PRS-049:** two consecutive reconciliations with unchanged repository/external evidence and the first result used as the second persisted layer must have zero semantic drift, zero diagnostics and exactly one row per decision, capability and backlog identity. Reconciliation must not duplicate already-active backlog items or manufacture new decision state on an unchanged second pass.

## PRS mapping

- PRS-016: normalized persisted-state reader (`--input` JSON contract).
- PRS-017: repository implementation/runtime reader within the normalized contract.
- PRS-018: Decision ↔ Implementation comparator.
- PRS-019: Capability ↔ Runtime comparator.
- PRS-020: Runtime ↔ External State comparator.
- PRS-021: `FALSE_NEGATIVE_PERSISTENCE` detector.
- PRS-022: `FALSE_POSITIVE_PERSISTENCE` detector.
- PRS-023: `SUPERSEDED_WORK` detector.
- PRS-024: deterministic canonical JSON + SHA-256 fingerprints and repeated-run equality self-test.
- PRS-042: executable `prs_042_drive_old_main_new_acceptance.py` verifies that stale Drive state cannot downgrade newer merged main evidence and cannot silently claim persistence freshness.
- PRS-043: executable `prs_043_open_pr_unmerged_acceptance.py` verifies that open/draft unmerged work remains `ACTIVE_UNIMPLEMENTED` or explicit `PARTIAL`, never `IMPLEMENTED`.
- PRS-044: executable `prs_044_superseded_pr_later_merge_acceptance.py` verifies that a later merged replacement becomes the implementation truth, while the explicitly superseded PR remains historical and cannot re-enter the active backlog.
- PRS-045: executable `prs_045_outbox_only_capability_acceptance.py` verifies that implemented adapter code plus outbox-only runtime remains `PARTIAL` and never becomes direct publication.
- PRS-046: executable `prs_046_profile_asset_no_remote_readback_acceptance.py` verifies that local profile readiness without remote readback remains `PARTIAL`/`UNCONFIRMED` and never becomes external LIVE.
- PRS-047: executable `prs_047_no_progress_checkpoint_then_main_acceptance.py` verifies that a historical NO_PROGRESS checkpoint stays immutable/history-only while later merged main evidence advances current truth and retires stale checkpoint-derived backlog.
- PRS-048: executable `prs_048_explicit_decision_replacement_acceptance.py` verifies that an explicit replacement retires the old decision/backlog as `SUPERSEDED` while the new decision remains active until independently implemented.
- PRS-049: executable `prs_049_consecutive_no_change_idempotency_acceptance.py` verifies that two unchanged consecutive reconciliation passes preserve identical semantic state with zero diagnostics and no duplicate decisions, capabilities or backlog items.

The engine does not replace the Google Drive writer lease. Any process that persists its result into active CIVORA state must separately acquire `CIVORA_PERSISTENCE_WRITER_LEASE_V1`, use per-target revision control, verify readback, and release the lease.
