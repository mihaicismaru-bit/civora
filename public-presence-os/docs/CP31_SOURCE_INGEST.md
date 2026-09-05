# CP31 — Validated module import manifest + CP23–CP29 evidence-bound source ingest v1

CP31 does **not** reconstruct historical executable files from checkpoint prose. It creates the source-import ledger that prevents that mistake.

Each CP23–CP29 checkpoint is bound to its exact Google Drive document ID and revision ID. The checkpoint documents prove the validated contract, migration number and expected source families, but the declared `public_presence_cpXX_reference.zip` archives are not present in the canonical Drive search surface. Therefore `source_bytes_available=false`, `import_eligible=false` and `HOLD_SOURCE_BYTES_UNAVAILABLE` are mandatory for all seven packages.

GitHub remains executable-source authority. A later import may promote a checkpoint only after the exact source archive/bytes are recoverable, SHA-256-bound, path-inventoried and regression-tested against current CP30+ policy. Checkpoint prose is evidence, not substitute source code.

This is intentionally a fail-closed ingest: evidence is now canonicalized in the source tree; historical executable bytes are not falsely claimed.
