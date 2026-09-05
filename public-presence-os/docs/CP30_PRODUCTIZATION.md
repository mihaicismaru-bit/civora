# CP30 — Canonical GitHub productization + reproducible build layout v1

CP30 establishes one maintainable executable-source tree without importing live credentials, real-account state, historical Drive evidence, generated font files or deployment state into Git.

## Canonical boundaries

GitHub owns executable source. Google Drive remains evidence/checkpoint authority. The two authorities are deliberately separate: commits do not rewrite historical checkpoint evidence, and Drive evidence cannot silently mutate executable source.

## Layout

- `src/public_presence_os/` — package/control primitives.
- `config/runtime_policy.json` — fail-closed pre-pilot policy.
- `config/module_registry.json` — pipeline/module map.
- `scripts/build_release.py` — deterministic standard-library package builder.
- `tests/` — productization and safety regression.
- `.github/workflows/public-presence-os-ci.yml` — validation-only CI.
- `docs/` — versioned productization contract.

## Reproducibility

The source manifest hashes every included source/config/script/test/doc/workflow file. ZIP timestamps and permissions are normalized so two builds from identical bytes are byte-identical.

## Non-goals

CP30 does not deploy, publish, connect Meta accounts, reserve scheduler slots, mutate queues, execute experiments or import paid SaaS dependencies. It does not copy Google Drive checkpoints into the repository; only the executable contract and checkpoint identifier are represented.

## Migration rule for CP01–CP29

Older locally validated modules are not blindly copied. A later module-import unit may move each executable component into this tree only when its exact source bytes, tests and checkpoint provenance are available and validated against this CP30 policy. Until then the registry marks their maturity without pretending the historical bytes are already canonical GitHub source.
