# CIVORA

CIVORA is the canonical deterministic runtime for the LOCAL NEWS V2 evidence, verification, editorial-safety and story-generation pipeline.

## Current status

The canonical development branch has progressed through the production-hardening and editorial-safety checkpoint series and is now in **v1.0 release-closure mode**.

Implemented capabilities include:

- source and signal persistence;
- atomic JSON stores with checksums, backups and fail-closed recovery;
- cross-process locking and transaction journaling;
- dead-letter handling and audited resolution;
- unified runtime/editorial health and remediation guidance;
- durable Fact Kernel with evidence provenance;
- claim/evidence reconciliation and explicit contradiction analysis;
- editorial conflict gate and audited approval state machine;
- restart-safe approved-story re-entry;
- authorized-fact-only story generation;
- evidence-constrained reader-visible rendering;
- operational CLI, recovery inspection and remediation runbooks.

The package version remains pre-v1 until final release gates, RC preflight and explicit release approval are complete.

## Validation

Run the full test suite:

```bash
python -m unittest discover -s tests -v
```

GitHub Actions validates the declared Python lower bound and supported current versions on Linux, includes a Windows-native full-suite job, and performs a built-distribution smoke test before v1.0 closure.

## Operator surfaces

Primary runtime and editorial control:

```bash
civora --help
```

Read-only remediation guidance:

```bash
civora-remediation --help
```

Canonical incident/recovery procedures are documented in:

```text
docs/runbooks/operator-remediation.md
```

## Release policy

Changes are developed on the canonical branch, validated by GitHub Actions and integrated through a pull request. Release closure requires:

1. all release-blocking audit findings resolved;
2. full cross-platform and built-artifact validation;
3. release manifest and changelog;
4. synchronized version metadata;
5. final RC preflight;
6. explicit human approval before merge/tag/release.

## Historical import provenance

The repository originated from the validated `CIVORA core runtime v0.2` artifact imported on 2026-08-06. `docs/CANONICAL_IMPORT.md` records that historical bootstrap; it is not the current implementation status.
