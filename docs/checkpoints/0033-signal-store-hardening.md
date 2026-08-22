# CIVORA Checkpoint 0033 — Signal Store Hardening

**State:** CODE_COMPLETE / CI_PENDING  
**Package line:** core runtime v0.2 development branch  
**Scope:** persistent signal ingestion store

## Implemented

- schema version advanced to 2;
- deterministic SHA-256 checksum over the complete persisted payload;
- structural validation for signals and fingerprint index;
- rejection of fingerprint references to missing signals;
- fsync-backed temporary-file writes followed by atomic replacement;
- preservation of the previous valid generation as `.bak`;
- automatic restoration when the primary generation is corrupt;
- fail-closed startup when both primary and backup are invalid;
- in-memory rollback when persistence fails;
- explicit `SignalStoreError` diagnostics.

## Completed gates

| Gate | Result |
|---|---|
| Payload integrity checksum | PASS — implementation and tests committed |
| Atomic file replacement | PASS — implementation committed |
| Previous-generation backup | PASS — implementation and tests committed |
| Corrupt-primary recovery | PASS — test committed |
| Dual-corruption fail-closed behavior | PASS — test committed |
| Fingerprint referential integrity | PASS — test committed |
| Full CI execution | PENDING — GitHub Actions has not emitted a run |

## Evidence

- `civora/ingestion.py`
- `tests/test_registry_ingestion.py`
- commits `37add25940fd7d19cd51f3e9f5b98125c9c2371f` and `9a1c4335b091966b52c36bfd7e8adbd620fa5bc2`

## Remaining backlog

1. Obtain a complete GitHub Actions run for Python 3.11–3.13.
2. Apply the same atomic/checksummed persistence contract to Source Registry, Review Queue and orchestrator state.
3. Add process-level locking around read-modify-write operations.
4. Introduce transaction coordination across source, signal, story and review artifacts.
5. Add structured recovery events and unified health reporting.

## Blockers

- GitHub Actions has not yet produced a workflow run for the development branch.
- Native Windows validation remains unavailable in the current execution environment.
- Repository visibility is public; no secrets or operational credentials may be committed.

## Next action

Generalize this persistence mechanism into a shared `AtomicJsonStore` and migrate Source Registry and Review Queue to the shared implementation, eliminating duplicated and unsafe direct writes.
