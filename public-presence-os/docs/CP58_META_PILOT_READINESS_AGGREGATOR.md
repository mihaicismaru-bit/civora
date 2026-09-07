# CP58 — META PILOT READINESS AGGREGATOR + LIVE CONNECTION AUTHORIZATION GATE v1

Status: `PASS_CP58_OFFLINE_READINESS_AGGREGATED_LIVE_CONNECTION_HOLD / HOLD_PILOT_CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE`

## Purpose

CP58 collapses the exact CP50–CP57 Meta path into one deterministic, fail-closed readiness receipt. It is deliberately an offline aggregation unit: it does not resolve credentials, read environment or keychain values, run OAuth, query a real account, make a network request, connect an account, publish content, perform an external write, deploy anything or use a paid service.

The result separates two questions that must not be conflated:

1. Is the local Meta integration path structurally coherent from the offline request compiler through the CP57 synthetic evidence dry-run?
2. Is a real Meta connection or pilot publication authorized?

CP58 can answer the first question `PASS` while keeping the second one `HOLD`.

Facebook Page, Instagram Professional and Threads remain the only active lanes. LinkedIn remains gated until production API access exists, X remains excluded while its API is paid, and Bluesky remains gated until a later local ROI test passes.

## Exact lineage

CP58 requires and revalidates all eight upstream artifacts:

- CP50 — offline request plan;
- CP51 — connection profile with symbolic `ENV:` or `OS_KEYCHAIN:` secret reference;
- CP52 — synthetic preflight receipt;
- CP53 — operator provisioning packet;
- CP54 — synthetic transport twin;
- CP55 — read-only connection gate;
- CP56 — read-only probe runbook/evidence contract;
- CP57 — synthetic evidence bundle and operator dry-run receipt.

The aggregator verifies every direct parent binding: plan→preflight, profile→preflight, preflight/profile→operator packet, plan/preflight/packet→transport twin, twin→read-only gate, gate→probe contract and probe contract→CP57 evidence bundle. Platform and mode must remain exact across the complete lineage.

The CP58 receipt stores only checkpoint, artifact kind, artifact ID and SHA-256 binding for each upstream artifact. It does not persist credential material or even the CP51 secret-reference locator.

## Readiness checks

A CP58 PASS means all of the following local properties hold:

- every CP50–CP57 artifact validates under its own contract;
- the eight-artifact lineage is exact and hash-bound;
- the platform is one of the three active Meta lanes;
- platform and mode are identical across the lineage;
- the CP51/CP52 offline capability contract is complete;
- the CP55 kill-switch interlock is still engaged;
- CP56 still requires the kill switch;
- CP57 is synthetic-only, zero-write and its operator dry-run passed;
- none of the upstream receipts claims live entitlement, real account connection, live network execution, publication or deployment.

## Deliberate live-connection HOLD

CP58 never promotes an offline PASS into live authority. The readiness receipt carries `authorization_state=HOLD_LIVE_CONNECTION_AUTHORIZATION`, `live_connection_authorized=false` and `pilot_publish_ready=false`.

The mandatory blockers are:

- `HOLD_LIVE_EVIDENCE_NOT_CAPTURED`;
- `HOLD_LIVE_PERMISSION_CAPABILITY_NOT_VERIFIED`;
- `HOLD_LIVE_API_VERSION_AND_DESTINATION_UNBOUND`;
- `HOLD_SECRET_REFERENCE_NOT_RESOLVED`;
- `HOLD_REAL_ACCOUNT_NOT_CONNECTED`;
- `HOLD_FINAL_PILOT_AUTHORIZATION_REQUIRED`.

These blockers are not errors in CP58. They are the intended proof that the system remains inside the pre-pilot safety boundary.

## Authorization rules

The CP58 policy requires a fresh explicit final authorization after the complete pilot package is validated. Automatic authorization and self-authorization are both forbidden. CP58 contains no function that can authorize a live connection or disengage the kill switch.

A forged/tampered receipt that flips live connection, network, publication, final authorization or pilot-ready flags fails validation before the receipt hash check can legitimize it.

## Output

The deterministic receipt contains:

- platform and mode;
- exact CP58 policy hash;
- ordered CP50–CP57 lineage bindings;
- the local readiness checks;
- the mandatory live blockers;
- the nine required future live evidence codes inherited from CP55/CP56;
- the engaged kill-switch state;
- zeroed live/network/account/publish/deploy authority flags;
- a SHA-256-derived receipt ID and receipt hash.

Given the same exact input artifacts and CP58 policy, the output is identical.

## Recovery and rollback

CP58 performs no external mutation. On failure, discard the invalid readiness receipt, retain the global kill switch, and return to the exact upstream artifact that failed validation. No account disconnect, publish rollback or deployment rollback is required because none of those actions is possible in CP58.

Repository rollback is a normal Git revert of the CP58 merge.

## Pilot state after CP58

The Meta path is aggregated and locally validated, but the pilot remains HOLD. No real connection attempt is authorized.

The next bounded unit is:

`CP59_PILOT_PACKAGE_COMPLETENESS_MANIFEST_AND_FINAL_OFFLINE_ACCEPTANCE_SUITE`

CP59 should aggregate the complete PUBLIC PRESENCE OS pilot package — not just the Meta path — into one reproducible completeness manifest and final offline acceptance suite before any real account connection or publication can be considered.
