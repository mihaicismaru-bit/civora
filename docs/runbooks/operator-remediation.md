# CIVORA Operator Remediation Runbook

Release-closure baseline for deterministic, evidence-preserving recovery and investigation.

## Scope

This runbook covers durable-state incidents reported by:

```text
civora --state-dir <path> health
civora --state-dir <path> editorial-consistency
civora-remediation --state-dir <path>
```

It does not authorize direct editing of CIVORA JSON stores. It does not create a new recovery policy. The machine-readable remediation classification returned by CIVORA is authoritative.

## Safety rules

1. Never edit `*.json`, `*.bak`, `*.lock` or checkpoint files by hand.
2. Never delete a dead letter, approval case, recovery event or transaction to make health green.
3. Never overwrite the durable state directory before preserving the incident evidence.
4. Use only the existing audited mutation commands for dead-letter or editorial decisions.
5. If the remediation classification is `manual_investigation_required`, stop automatic processing and preserve evidence before any external restore.
6. Human approval may authorize a fact below the automatic corroboration threshold, but cannot override unsupported, unlinked, disputed, contradicted or unresolved factual state.

## Exit-code contract

Primary CIVORA CLI:

- `0`: healthy / operation completed;
- `2`: unhealthy state requiring recovery or operator action;
- `3`: command or operational error.

`civora-remediation`:

- `0`: `no_action`;
- `2`: action is required;
- `3`: inspection error.

## Decision tree

### A. `no_action`

Condition:

```text
remediation.classification = no_action
```

Procedure:

1. Run `civora --state-dir <path> health`.
2. Confirm overall status is `healthy` or `recovered_from_backup`.
3. If status is `recovered_from_backup`, inspect `recovery-events` and retain the event identifiers in the incident record.
4. Resume normal execution. No repair action is permitted or required.

### B. `automatic_recovery_available`

Condition:

```text
remediation.classification = automatic_recovery_available
```

This classification is valid only when each reported editorial cross-store mismatch is covered by an exact `prepared` transaction.

Procedure:

1. Preserve the output of:
   - `civora --state-dir <path> health`
   - `civora --state-dir <path> editorial-consistency`
   - `civora-remediation --state-dir <path>`
2. For every transaction ID reported by remediation guidance, run:

```text
civora --state-dir <path> transaction <transaction-id>
```

3. Do not mutate the stores manually.
4. Run the normal CIVORA startup path or the appropriate restart-safe operation. Startup transaction replay is the only automatic mutation path authorized for this condition.
5. Re-run `health` and `editorial-consistency`.
6. Closure criteria:
   - health is `healthy` or `recovered_from_backup`;
   - editorial consistency is `healthy`;
   - remediation becomes `no_action`.
7. If any criterion fails, reclassify the incident as manual investigation. Do not retry by deleting or rewriting durable records.

### C. `manual_investigation_required`

Condition:

```text
remediation.classification = manual_investigation_required
```

Examples include committed divergence, ambiguous state, or a mismatch with no exact prepared recovery transaction.

Procedure:

1. Stop new editorial work. Treat the state as fail-closed.
2. Preserve an immutable incident snapshot of the state directory and record its filesystem timestamp/location. Do not alter the original files while collecting evidence.
3. Capture:

```text
civora --state-dir <path> health
civora --state-dir <path> editorial-consistency
civora-remediation --state-dir <path>
civora --state-dir <path> resolution-audit
civora --state-dir <path> dead-letters
civora --state-dir <path> recovery-events
```

4. For every referenced transaction, inspect:

```text
civora --state-dir <path> transaction <transaction-id>
```

5. For every affected story/case, inspect as applicable:

```text
civora --state-dir <path> editorial-story <story-id>
civora --state-dir <path> authorized-story <story-id>
civora --state-dir <path> approval-case <case-id>
```

6. Determine which durable record is authoritative from the transaction and approval audit history. Do not infer authority from file modification time alone.
7. Do not synthesize a repair transaction or fabricate a missing audit record.
8. If a valid external immutable backup exists, use the backup-recovery procedure below. If not, keep the runtime blocked until a specific, evidence-backed repair procedure has been reviewed and implemented as code/tests.

## Backup recovery

CIVORA's `AtomicJsonStore` automatically restores a corrupt primary generation from a valid `.bak` generation during normal validated reads. This automatic path is preferred and is recorded as `recovered_from_backup`.

### Primary corrupt, internal `.bak` valid

1. Run `civora --state-dir <path> health`.
2. Allow CIVORA's existing validated read path to perform recovery.
3. Confirm `recovered_from_backup` and inspect `recovery-events`.
4. Re-run health. A subsequent healthy state is acceptable after the recovery event has been preserved.

Do not manually copy `.bak` over the primary store.

### Primary and internal `.bak` invalid

1. Treat as `manual_investigation_required`.
2. Preserve both corrupt generations unchanged.
3. Do not create a fresh empty store to bypass corruption.
4. Identify the most recent trusted external backup whose provenance is known.
5. Restore only into a separate recovery state directory first.
6. Run `civora --state-dir <recovery-path> health` and all relevant consistency/audit commands against that restored copy.
7. Accept the backup only if health and audit invariants pass and the incident record explains the data-loss boundary relative to the corrupt state.
8. Promotion of an external backup into production is an operator-controlled external action and is not automated by CIVORA v1.0.

## Dead-letter procedure

Inspection:

```text
civora --state-dir <path> dead-letters
civora --state-dir <path> transaction <transaction-id>
```

Permitted audited transitions only:

```text
civora --state-dir <path> resolve-dead-letter <transaction-id> --action requeue --actor <actor> --reason <reason>
civora --state-dir <path> resolve-dead-letter <transaction-id> --action abort --actor <actor> --reason <reason>
```

After resolution:

```text
civora --state-dir <path> resolution-audit
civora --state-dir <path> health
```

Never remove dead-letter records manually.

## Editorial approval procedure

Inspect:

```text
civora --state-dir <path> approval-cases --state pending
civora --state-dir <path> approval-case <case-id>
civora --state-dir <path> editorial-story <story-id>
civora --state-dir <path> authorized-story <story-id>
```

Permitted audited decision path:

```text
civora --state-dir <path> decide-approval <case-id> --action approved --actor <actor> --reason <reason>
civora --state-dir <path> decide-approval <case-id> --action rejected --actor <actor> --reason <reason>
civora --state-dir <path> decide-approval <case-id> --action revision_required --actor <actor> --reason <reason>
```

For an approved story that must resume after restart:

```text
civora --state-dir <path> resume-approved <story-id> --version <version>
```

Re-entry remains bound to the exact editorial decision and Fact Kernel semantic hash. A stale approval must fail closed.

## Incident closure checklist

An incident is closed only when all applicable checks are true:

- `civora health` returns exit code `0`;
- `editorial-consistency` is healthy;
- remediation classification is `no_action`;
- `resolution-audit` is consistent when dead-letter resolution occurred;
- no unexplained `prepared` transaction remains;
- no unexplained dead letter remains;
- recovery/decision events are present in durable audit history;
- any backup recovery and potential data-loss boundary are recorded externally;
- no durable store was edited by hand.

## Escalation rule

If the existing commands cannot establish an evidence-backed repair, CIVORA must remain fail-closed. The repair must be implemented as a new deterministic code path with tests and audit semantics before it is used on production state.
