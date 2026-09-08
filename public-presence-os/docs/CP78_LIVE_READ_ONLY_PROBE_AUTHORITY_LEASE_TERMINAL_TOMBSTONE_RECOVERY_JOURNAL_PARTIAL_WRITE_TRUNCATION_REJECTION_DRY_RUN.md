# CP78 — Live Read-Only Probe Authority Lease Terminal Tombstone Recovery Journal Partial-Write + Truncation Rejection Dry-Run v1

## Status

`PASS_CP78_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD`

## Scope

CP78 extends the synthetic/local-only recovery-journal safety chain from CP77. It does not create a storage layer and does not perform a write. Instead, every one of the 12 complete CP77 positive-control journals is serialized deterministically as canonical UTF-8 JSON and treated as the expected complete byte sequence.

For each complete journal, CP78 applies five strict-prefix negative cases: empty write, one-byte prefix, midpoint prefix, truncation inside the `journal_hash` value, and final-byte missing. This yields 60 deterministic partial-write/truncation cases.

A candidate is rejected before JSON parsing and before any recovery effect unless its byte length exactly matches the known complete length. If the length matches, the serialized SHA-256 must also match before canonical JSON decoding and the existing CP77 semantic journal validator are reached.

## Invariants

- 12/12 complete canonical journal byte sequences are accepted as positive controls.
- 60/60 strict-prefix partial writes are rejected with `HOLD_CP78_PARTIAL_WRITE_LENGTH` before parse or recovery.
- Exact serialized length and SHA-256 are required.
- Baseline snapshot remains unchanged for every rejection.
- Recovery effect count remains zero for every rejection.
- No storage write, runtime mutation, registry mutation, policy mutation, network, OAuth, real-account lookup, live probe, publish, external write, control-plane promotion, deploy, or paid service is permitted.
- Global kill switch remains engaged.
- Active lanes remain exactly Facebook Page, Instagram Professional, and Threads.
- LinkedIn remains gated until production API access; X remains excluded while its API is paid; Bluesky remains held until the local ROI test passes.
- Global control checkpoint remains CP58.

## Rollback

Rollback target is CP77. CP78 changes are isolated to the M47 policy, source, tests, documentation, module-registry entry, and product-layout references.

## Next unit

`CP79_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY_DRY_RUN`

CP79 is named only; it is not started by CP78.
