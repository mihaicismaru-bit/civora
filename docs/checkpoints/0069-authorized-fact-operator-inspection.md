# CIVORA Checkpoint 0069 — Authorized Fact Operator Inspection

Status: CLOSED_VALIDATED

## Objective

Expose the exact factual projection that production drafting is allowed to consume, so an operator can inspect authorized facts, excluded facts, exclusion reasons, authorization mode and immutable editorial/kernel bindings before resume or publication.

## Implementation

The operational CLI includes:

```bash
civora --state-dir <path> authorized-story <story-id>
```

The command loads the current durable Fact Kernel, reconciliation report, contradiction report, editorial gate decision and approval case, then calls the same `AuthorizedStoryBuilder` used by production drafting. It does not duplicate or weaken authorization policy.

The output is machine-readable JSON and includes authorization mode, editorial decision ID, Fact Kernel semantic hash, authorized facts, excluded facts with exact exclusion reasons, authorized uncertain claims and the effective authorization policy.

The command is read-only. It cannot approve a case, edit facts, mutate durable reports or bypass editorial alignment. Missing durable components, stale reports, invalid approval binding, contradictions or a projection with no authorized confirmed facts fail closed through `AuthorizedStoryError`.

## Validation

`tests/test_authorized_cli.py` verifies exact authorized/excluded fact visibility and fail-closed behavior for an incomplete durable editorial chain.

GitHub Actions run `31228762852` completed successfully for head `a6add143a7a507801930c65b4a3a48cca8ba8a54`, closing the cross-platform gate.

## Gates

- PRODUCTION_AUTHORIZATION_BUILDER_REUSED: PASS
- AUTHORIZED_FACT_VISIBILITY: PASS
- EXCLUDED_FACT_VISIBILITY: PASS
- EXCLUSION_REASON_VISIBILITY: PASS
- AUTHORIZATION_BINDING_VISIBILITY: PASS
- MACHINE_READABLE_JSON: PASS
- READ_ONLY_OPERATOR_SURFACE: PASS
- INCOMPLETE_CHAIN_FAIL_CLOSED: PASS
- CROSS_PLATFORM_CI: PASS

## Remaining backlog after closure

1. Evidence-constrained reader-visible rendering.
2. Operator remediation and recovery runbooks for editorial consistency and authorization failures.
3. Production-readiness review covering crash recovery, health, editorial safety, packaging and operational runbooks.

## Blockers

None.

## Next action

Implement evidence-constrained rendering so reader-visible factual prose is no longer sourced from raw signal title/summary text.
