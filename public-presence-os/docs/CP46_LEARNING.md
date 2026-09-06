# CP46 — M11 LEARNING MINIMAL EXECUTABLE SLICE

State: `PASS_M11_EXECUTABLE / HOLD_PILOT_M14_GAP` after exact-head CI and canonical merge.

## Purpose

CP46 reimplements M11 Learning as a local, deterministic, fail-closed shadow-learning ledger. It consumes only exact CP45 `LocalAnalyticsSnapshot` inputs that already validate as `LOCAL_OPERATIONAL_TELEMETRY_ONLY` and explicitly have no external performance evidence.

## Input gate

M11 accepts only M10 snapshots that:

- validate against the CP45 analytics contract and exact SHA-bound snapshot hash;
- belong to Facebook Page, Instagram Professional, or Threads;
- have `learning_input_ready=true` and `learning_scope=LOCAL_OPERATIONAL_TELEMETRY_ONLY`;
- have `performance_evidence_ready=false`;
- have `external_analytics_state=NOT_CONNECTED`;
- have `derived_metrics_state=NOT_COMPUTABLE_NOT_CONNECTED`.

Any divergence is a HOLD. M11 cannot reinterpret missing external metrics as zero.

## Output

For each accepted snapshot, M11 creates one append-only `ShadowLearningRecord` with exactly these permissible observations:

1. local dry-run receipt telemetry exists;
2. the verified local receipt age in seconds;
3. remote analytics is not connected;
4. performance evidence is unavailable.

The record is forced to:

- `performance_conclusion=NO_PERFORMANCE_CONCLUSION`;
- `optimization_recommendation=NO_OPTIMIZATION_RECOMMENDATION`;
- `experiment_input_ready=true` only for `LOCAL_CONTROL_VALIDATION_ONLY`;
- `external_experiment_ready=false`.

Thus CP46 can hand M14 enough deterministic control evidence to build a local experiment ledger later, but it cannot infer what content performs better and cannot recommend publishing or strategy changes.

## Persistence and replay

SQLite-local tables store immutable M10 snapshot inputs, append-only learning records, and append-only learning events. A caller `request_id` plus exact input and timestamp is idempotent. Request reuse with payload drift and a second record for the same M10 snapshot fail closed.

## Privacy

The slice is aggregate content-level only. Individual profiling and demographic dimensions are prohibited.

## Authority boundary

Allowed: local shadow-learning record creation and readback.

Not allowed: performance learning, strategy mutation, content mutation, experiment execution, network calls, real-account connection, queue/publisher actions, publication, deploy, or paid-service use.

Active architecture remains Facebook Page, Instagram Professional, and Threads. LinkedIn remains production-API-gated; X remains excluded while its API is paid; Bluesky remains `HOLD_ROI`.

## Next unit

`CP47 — M14 EXPERIMENTS MINIMAL EXECUTABLE SLICE + LOCAL CONTROL-VALIDATION EXPERIMENT LEDGER v1`.
