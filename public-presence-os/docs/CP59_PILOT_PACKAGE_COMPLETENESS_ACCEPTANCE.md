# CP59 — Pilot Package Completeness Manifest + Final Offline Acceptance Suite v1

## Purpose

CP59 is the final **offline** acceptance boundary for PUBLIC PRESENCE OS — TEXT/PHOTO before any real Meta account connection or pilot execution. It aggregates the executable source package, module registry, runtime policy, operator documentation, Meta offline lineage, tests and safety controls into one deterministic, SHA-256-bound acceptance receipt.

CP59 does **not** grant live authority. The global control checkpoint remains CP58 while live evidence, real secret resolution, account connection and final explicit pilot authorization remain absent. This distinction prevents a green offline build from being misinterpreted as permission to contact Meta or publish.

## Canonical lanes

Active lanes are exactly Facebook Page, Instagram Professional and Threads. LinkedIn remains held until production API access is available. X remains excluded while its API is paid. Bluesky remains held until a later local ROI test passes.

## Acceptance inputs

The CP59 policy binds the complete in-house package: RADAR → research → scoring → master draft → native adaptations → image-rights registry → visual generation → QA → approval → queue → publisher → analytics → learning, plus local DB/event-log support, installation/recovery documentation, visual identity runtime, and the CP50–CP58 Meta adapter/preflight/test-twin/read-only/evidence/readiness chain.

The compiler checks the exact module states recorded in `module_registry.json`, requires the CP58 parent control checkpoint, validates the fail-closed runtime policy, confirms all required artifacts exist, binds them by SHA-256, creates a deterministic source manifest, rejects network-client imports, scans source/config/docs for raw secret material, and verifies the kill switch remains engaged.

## Result semantics

A successful receipt has state:

`PASS_CP59_FINAL_OFFLINE_ACCEPTANCE_LIVE_GATES_HOLD`

It means the package is internally complete enough for final offline acceptance and operator handoff preparation. It does **not** mean a Meta token is valid, permissions are live, an account is connected, a destination is verified, a network probe is authorized, publishing is enabled, deployment is approved, or a paid service may be used.

The following blockers remain mandatory after a CP59 PASS:

- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_FINAL_PILOT_AUTHORIZATION_REQUIRED`
- `HOLD_GLOBAL_CONTROL_CHECKPOINT_PROMOTION`

## CI acceptance

CP59 itself is covered by `tests/test_cp59_pilot_package_acceptance.py`. Repository CI remains the authority for the complete pytest suite and reproducible package check. The CP59 policy explicitly requires both, while the runtime remains offline and has no deploy step.

## Safety and rollback

No CP59 code resolves `ENV:` or `OS_KEYCHAIN:` locators, performs OAuth, opens a socket, contacts Meta, connects an account, mutates the queue, publishes, writes externally, deploys, or invokes paid services. Rollback is source-only: revert the CP59 policy/module/test/doc additions and the M28 registry row; CP58 remains the parent control checkpoint throughout.

## Next unit

`CP60_OPERATOR_PILOT_HANDOFF_AND_EXPLICIT_AUTHORIZATION_PACKET` — prepare the final operator-facing handoff and explicit authorization boundary. That unit must still remain fail-closed and may not itself connect accounts or publish without a fresh explicit authorization.
