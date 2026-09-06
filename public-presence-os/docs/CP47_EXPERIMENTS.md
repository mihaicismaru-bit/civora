# CP47 — M14 EXPERIMENTS MINIMAL EXECUTABLE SLICE

State target: `PASS_M14_EXECUTABLE / HOLD_PILOT_IDENTITY_EQUIVALENCE` after exact-head CI and canonical merge.

## Purpose

CP47 reimplements M14 Experiments as a deterministic, local-only control-validation experiment ledger. It consumes only exact CP46 `ShadowLearningRecord` inputs and deliberately refuses to turn missing external performance data into A/B tests, content variants, audience segments, optimization claims, or publishing actions.

## Input gate

M14 accepts only M11 records that:

- validate against the CP46 learning contract and exact SHA-bound record hash;
- belong to Facebook Page, Instagram Professional, or Threads;
- have `experiment_input_ready=true` and `experiment_scope=LOCAL_CONTROL_VALIDATION_ONLY`;
- have `external_experiment_ready=false`;
- have `performance_evidence_state=UNAVAILABLE_NOT_CONNECTED`;
- have `performance_conclusion=NO_PERFORMANCE_CONCLUSION`;
- have `optimization_recommendation=NO_OPTIMIZATION_RECOMMENDATION`;
- grant no performance-learning, strategy-mutation, external-experiment, network, account, publish, or deploy authority.

Any divergence is a HOLD.

## Output

For each accepted learning record M14 creates one immutable `LocalControlExperimentPlan` with exactly four control checks:

1. learning-record hash binding;
2. no performance evidence;
3. no content variants;
4. zero external authority.

The plan is forced to:

- `mode=LOCAL_CONTROL_VALIDATION_ONLY`;
- `performance_hypothesis=NO_PERFORMANCE_HYPOTHESIS`;
- `optimization_recommendation=NO_OPTIMIZATION_RECOMMENDATION`;
- `content_variant_count=0`;
- `performance_metric=null`;
- `audience_segment=null`;
- `local_control_validation_ready=true`;
- `external_experiment_ready=false`.

The ledger records that a local control plan exists; it does not execute a remote experiment and does not create content variants.

## Persistence and replay

SQLite-local tables store immutable M11 learning inputs, append-only experiment plans, and append-only experiment events. A caller `request_id` plus exact learning record and creation timestamp is idempotent. Request reuse with payload drift and a second plan for the same M11 learning record fail closed.

## Privacy

The slice is aggregate content-level only. Individual profiling, demographics, and audience segmentation are prohibited.

## Authority boundary

Allowed: local experiment-ledger writes and deterministic local control-plan creation/readback.

Not allowed: performance experiments, content mutation, strategy mutation, audience targeting, network calls, real-account connection, queue/publisher writes, publication, deploy, or paid-service use.

Active architecture remains Facebook Page, Instagram Professional, and Threads. LinkedIn remains production-API-gated; X remains excluded while its API is paid; Bluesky remains `HOLD_ROI`.

## Pilot truth boundary after CP47

CP47 closes the final executable-source gap M14, but it must not create a false green pilot. The current visual identity policy still has `font_binding_state=HOLD_HISTORICAL_EXACT_FONT_HASHES_UNRECOVERED` and `production_identity_equivalence_asserted=false`. Rehearsal therefore remains HOLD on `HOLD_IDENTITY_EQUIVALENCE` even when M01–M14 all have executable source.

## Next unit

`CP48 — VERSIONED VISUAL IDENTITY SUPERSESSION + EXACT FONT/LICENCE BINDING v1`, performed without claiming equivalence to the unrecoverable CP29 font bytes.
