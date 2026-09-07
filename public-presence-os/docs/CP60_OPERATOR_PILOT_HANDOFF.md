# CP60 — Operator Pilot Handoff + Explicit Authorization Packet v1

## Status

`PASS_CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD`

CP60 is an **offline handoff boundary**. It packages the already-passed CP59 final offline acceptance into an operator-facing, deterministic, SHA-256-bound handoff packet while keeping every live authorization gate closed.

## What CP60 proves

The compiler re-runs and validates the exact CP59 final offline acceptance receipt, binds its acceptance ID/hash/source-manifest hash, validates the fail-closed runtime policy, confirms the global control checkpoint remains CP58, confirms only Facebook Page, Instagram Professional and Threads are active lanes, and emits a deterministic operator checklist plus two separate authorization gate templates.

The two gates are deliberately distinct:

1. `LIVE_READ_ONLY_CONNECTION_PROBE` — future permission to resolve the minimum credentials and perform only the bounded read-only connection/evidence-capture sequence.
2. `PILOT_PUBLISH` — future pilot-publishing permission, which remains unavailable until the live read-only validation path has separately passed.

Both gates are emitted with `state=NOT_GRANTED`, `decision_source=EXTERNAL_HUMAN_ONLY`, no authorizer reference, no timestamp and no authorization-evidence hash. CP60 cannot infer, synthesize or grant either decision.

## Canonical lanes

Active lanes remain exactly Facebook Page, Instagram Professional and Threads. LinkedIn remains held until production API access exists. X remains excluded while its API is paid. Bluesky remains held until a later local ROI test passes.

## Safety boundary

CP60 performs no secret resolution, environment/keychain reads, OAuth, real-account lookup, account connection, network request, publish attempt, external write, deploy or paid-service call. The global kill switch stays engaged. The global control checkpoint remains CP58, so a green CP60 packet cannot promote itself into live authority.

## Operator checklist

The packet requires explicit review of: CP59 acceptance binding; kill-switch state; active lanes; symbolic-only secret references; absence of live evidence; absence of read-only authorization; absence of publish authorization; and the source-only recovery path.

## Changelog

- Added `config/operator_pilot_handoff_policy.json`.
- Added `src/public_presence_os/operator_pilot_handoff.py`.
- Added CP60 tests and repository-layout binding.
- Added module `M29_OPERATOR_PILOT_HANDOFF` with state `CP60_OPERATOR_HANDOFF_READY_AUTHORIZATION_HOLD`.
- Preserved the CP58 global control checkpoint and CP59 priority marker intentionally.

## Decisions

- Offline package acceptance and live authorization remain separate concepts.
- Read-only connection/probe authorization and pilot-publish authorization are separate gates.
- Authorization may only come from an explicit external human decision; CP60 has no self-authorization path.
- A future authorization must be platform- and scope-bound and must not imply deploy authority.
- No real account identifiers or raw credentials belong in the CP60 packet.

## Blockers carried forward

- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`
- `HOLD_LIVE_READ_ONLY_AUTHORIZATION_NOT_GRANTED`
- `HOLD_PILOT_PUBLISH_AUTHORIZATION_NOT_GRANTED`
- `HOLD_GLOBAL_CONTROL_CHECKPOINT_PROMOTION`

## Rollback

Rollback is source-only: revert the CP60 policy/compiler/test/doc additions and the M29 registry row. CP59 remains the accepted offline boundary and CP58 remains the global control checkpoint.

## Next unit

`CP61_CONTROL_PLANE_PROMOTION_AND_AUTHORIZATION_INTAKE_CONTRACT` — define the fail-closed structure for receiving a future explicit authorization decision without executing network access, connecting accounts or publishing in the same unit.
