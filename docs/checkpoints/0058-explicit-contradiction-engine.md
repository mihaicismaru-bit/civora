# CIVORA Checkpoint 0058 — Explicit Contradiction Engine

Status: CODE_COMPLETE_CI_PENDING

## Objective

Add explicit contradiction reasoning to the accelerated editorial path without relying on lexical negation, fuzzy semantic inference, or hidden mutation of evidence.

## Implementation

### Explicit evidence polarity

`EvidencePolarity` defines two supported relations:

- `support`
- `contradict`

`EvidenceRelation` binds a target Fact Kernel statement to one concrete evidence item through source identity plus evidence claim text. Relations are explicit editorial/provenance assertions; CIVORA does not infer contradiction merely because text contains words such as `not`, `nu`, or other negation patterns.

### Contradiction engine

`ExplicitContradictionEngine` evaluates each confirmed fact or uncertain claim using:

- existing Fact Kernel evidence links as support;
- optional explicit support relations;
- explicit contradiction relations;
- strongest evidence per independent source;
- deterministic combined confidence.

Outcomes are:

- `uncontested`
- `disputed`
- `contradicted`
- `unresolved`

The same evidence item cannot simultaneously support and contradict the same target. Missing targets or ambiguous/missing evidence relations fail closed.

### Durable contradiction reports

`FactContradictionStore` persists reports atomically and idempotently. Report identity is bound to:

- Fact Kernel identity;
- Fact Kernel semantic hash;
- normalized explicit relation set;
- contradiction policy.

This keeps the validated Fact Kernel store stable while allowing contradiction reasoning to evolve as a derived editorial artifact.

### Orchestrator integration

The accelerated path is now:

```text
verify story
→ persist Fact Kernel
→ persist claim/evidence reconciliation
→ persist contradiction report
→ draft/package (0058 remains observational; enforcement moves to 0059)
```

0058 deliberately records conflicts but does not yet block drafting. The next checkpoint will combine reconciliation + contradiction outcomes into a deterministic dispute-resolution/editorial gate.

## Validation added

`tests/test_contradictions.py` covers:

- strong support + strong contradiction → `disputed`;
- no explicit contradiction → `uncontested`;
- strong contradiction + weak support → `contradicted`;
- invalid target → fail closed;
- one evidence item cannot both support and contradict a target;
- durable-store idempotence;
- durable-store invalid-relation rejection;
- Orchestrator persistence of conflict reports.

## Gates

- EXPLICIT_EVIDENCE_POLARITY: PASS_IMPLEMENTATION
- NO_LEXICAL_NEGATION_HEURISTIC: PASS_IMPLEMENTATION
- INDEPENDENT_SOURCE_CONTRADICTION_SCORING: PASS_IMPLEMENTATION
- DISPUTED_OUTCOME: PASS_IMPLEMENTATION
- CONTRADICTED_OUTCOME: PASS_IMPLEMENTATION
- INVALID_RELATION_FAIL_CLOSED: PASS_IMPLEMENTATION
- DURABLE_CONTRADICTION_REPORT: PASS_IMPLEMENTATION
- ORCHESTRATOR_CONTRADICTION_WIRING: PASS_IMPLEMENTATION
- CROSS_PLATFORM_TEST_MATRIX: PENDING_CURRENT_CI

## Remaining backlog

1. Conflict/dispute resolution gate combining reconciliation and contradiction reports.
2. Editorial approval state machine.
3. Unified health inspection for Fact Kernel/reconciliation/contradiction stores.
4. Story Engine generation exclusively from approved/reconciled facts.
5. Operator inspection commands for editorial evidence/conflict state.

## Blockers

Current-head CI must pass before checkpoint 0058 can be declared CLOSED_VALIDATED.

## Next action

Implement checkpoint 0059: deterministic conflict/dispute resolution and enforcement before article drafting.
