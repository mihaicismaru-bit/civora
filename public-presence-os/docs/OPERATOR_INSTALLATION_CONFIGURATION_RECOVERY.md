# PUBLIC PRESENCE OS — Operator installation, configuration and recovery manual

Checkpoint family: CP32 / pre-pilot local-only operations.

## 1. Purpose and hard boundary

This manual prepares PUBLIC PRESENCE OS for a controlled pilot without connecting real social accounts or publishing anything. The canonical executable source is GitHub; Google Drive remains the checkpoint/evidence authority. The pre-pilot posture is fail-closed: the global kill switch is engaged and network, OAuth, real-account connection, scheduler writes, queue mutation, publisher writes, publication and deployment are disabled.

The only active product lanes are Facebook Page, Instagram Professional and Threads. LinkedIn remains gated until production API access is available. X remains excluded while its required API is paid. Bluesky remains HOLD_ROI.

## 2. Zero-cost local prerequisites

Required:

1. Python 3.11 or newer.
2. Git for source checkout and rollback.
3. SQLite, supplied through Python's standard library for the pre-pilot profile.
4. A filesystem location writable by the operator.
5. No paid SaaS dependency.

Optional local tools may be used for inspection, but they are not runtime requirements. Canva is not a runtime dependency.

## 3. Source checkout and authority check

1. Checkout the canonical `mihaicismaru-bit/civora` repository.
2. Enter `public-presence-os/`.
3. Confirm `config/runtime_policy.json` declares `GITHUB_EXECUTABLE_SOURCE` and `GOOGLE_DRIVE_CHECKPOINT_EVIDENCE`.
4. Confirm the runtime mode is `PRE_PILOT_DRY_RUN`.
5. Do not copy historical Drive checkpoint prose into executable source. Historical modules remain evidence-bound until exact source bytes are recovered and validated.

## 4. Local environment preparation

Create a Python virtual environment if desired. PUBLIC PRESENCE OS currently has no runtime package dependency beyond the standard library. The CI test runner uses pytest for validation only.

Required local directories are exactly:

- `var/`
- `var/artifacts/`
- `var/backups/`
- `var/logs/`

Do not place OAuth credentials, access tokens or account exports inside Git-tracked paths.

## 5. Operator profile

Start from `config/operator_profile.example.json`. In CP32 the example profile is also the preflight contract. It intentionally requires:

- local SQLite;
- synthetic-only evidence;
- live API calls disabled;
- OAuth disabled;
- local approval surface only;
- kill switch required;
- verified backups;
- preflight after every restore.

Any relaxation of those controls should fail preflight until a later explicitly authorized activation checkpoint changes the canonical policy.

## 6. Preflight

Run:

`PYTHONPATH=src python scripts/preflight.py`

PASS is exactly `PASS_PRE_PILOT_LOCAL`.

A PASS proves only that the local pre-pilot configuration is internally consistent. It does not authorize live API traffic, account connection, publication or deployment.

Typical HOLD classes:

- `HOLD_RUNTIME_POLICY_*` — fail-closed runtime policy is missing or relaxed.
- `HOLD_OPERATOR_*` — operator profile violates the local-only contract.
- `HOLD_DATABASE_PROFILE` — database is not the approved local SQLite profile.
- `HOLD_BACKUP_POLICY` — backup verification/retention contract is too weak.
- `HOLD_RECOVERY_POLICY` — restore would not force a new preflight.
- `HOLD_PYTHON_VERSION` — interpreter is below the supported floor.
- `HOLD_PLATFORM_SET` — active network set differs from Facebook Page / Instagram Professional / Threads.
- `HOLD_KILL_SWITCH` — global kill switch is not engaged.

Never bypass a HOLD by editing generated evidence. Correct the underlying config or restore the last-known-good state.

## 7. Daily pre-pilot operating sequence

Use this sequence for every local rehearsal:

1. Read the latest canonical Drive checkpoint and its rollback pointer.
2. Read the current GitHub main commit for `public-presence-os/`.
3. Run repository validation and CP32 preflight.
4. Confirm kill switch ENGAGED.
5. Confirm `network_enabled=false`, `real_accounts_connected=false`, `publish_enabled=false`, `deploy_enabled=false`.
6. Run only synthetic/local fixtures through the pipeline.
7. Inspect approval dashboard locally.
8. Verify event-log continuity, hashes and idempotent replay.
9. Create a verified local backup before any migration or schema-changing rehearsal.
10. Record test evidence in the checkpoint/evidence layer; do not claim external delivery.

## 8. Backup contract

Before any stateful rehearsal that changes the local SQLite database:

1. Stop local writers.
2. Confirm no pending transaction.
3. Copy the SQLite file into `var/backups/` with a timestamped name.
4. Calculate SHA-256 for the backup.
5. Verify that the copied bytes hash consistently on readback.
6. Keep at least the configured retention count; CP32 requires at least 3 and the example keeps 7.
7. Record the source DB hash, backup hash, timestamp and checkpoint ID in the local evidence record.

A backup is not VERIFIED merely because the copy command returned success.

## 9. Restore contract

Restore only from a VERIFIED backup.

1. Engage/confirm the global kill switch.
2. Stop all local writers.
3. Preserve the current failed database and logs as incident evidence; do not overwrite them.
4. Copy the selected verified backup into a new restore candidate path.
5. Verify hash and SQLite integrity on the candidate.
6. Replace the active local DB only after candidate validation.
7. Run CP32 preflight again.
8. Run event-log/readback/idempotency checks.
9. Resume synthetic operation only after all local gates pass.

Restore never authorizes live network operations.

## 10. Recovery matrix

### POLICY_DRIFT
Action: engage kill switch, preserve current config, restore the last-known-good canonical config, rerun preflight and regressions.

### DATABASE_CORRUPTION
Action: stop runtime, preserve the corrupt DB for evidence, restore the last VERIFIED backup, run integrity and preflight checks.

### QUEUE_DRIFT
Action: preserve the append-only event log and rebuild the dry-run queue deterministically. Never repair queue drift by directly editing terminal records.

### RIGHTS_DRIFT
Action: HOLD affected assets, preserve provenance, rerun the rights registry and visual QA. Do not substitute an unverified image merely to keep the queue moving.

### PUBLISHER_UNEXPECTED_WRITE
This should be structurally impossible in CP32. If observed, immediately engage the kill switch, preserve logs/state, stop the affected process and audit the executable source/config before any further run.

### UNKNOWN
Engage kill switch, preserve state and logs, classify the failure, then choose the smallest reversible recovery path. Do not continue on an unknown state.

## 11. Retry and idempotency operator rules

- Retry only operations declared retry-safe by the relevant module.
- Reuse the canonical idempotency key for an exact replay.
- Never invent a fresh key to bypass a duplicate/conflict HOLD.
- Append-only evidence and decision records are never edited in place.
- If the current head changes between review and execution planning, revalidate from the new head.
- A successful local replay is not proof of external delivery.

## 12. Kill switch drill

Before pilot readiness can be declared, the operator should be able to demonstrate locally:

1. kill switch starts ENGAGED;
2. local dry-run pipeline can operate while external writes remain disabled;
3. any attempt to enable network/write controls causes preflight/policy failure;
4. restoring canonical fail-closed config returns preflight to PASS;
5. no live post, scheduler reservation or account change occurs during the drill.

## 13. Future Meta connection procedure — documentary only

Do not execute these steps during CP32. They define the later connection runbook.

### Common prerequisites

1. A later checkpoint explicitly authorizes account connection.
2. Current official Meta developer documentation is reverified on the connection date.
3. A production Meta app exists under the intended operator organization/account.
4. Required platform permissions/features are approved for the intended use.
5. Secrets are stored outside Git and outside public logs.
6. The runtime policy is changed only through a reviewed, versioned checkpoint.
7. Kill switch, retry limits and readback/receipt requirements are tested before enabling writes.

### Facebook Page lane

Later activation must bind an intended Facebook Page to the canonical adapter, verify the exact Page identity and permission scope, perform a read-only identity check first, then a non-public or otherwise safely bounded connectivity test if the current API permits one. No write should be accepted as delivered without the external post ID/receipt required by the publisher contract.

### Instagram Professional lane

Later activation must verify that the intended Instagram account is an eligible Professional account and that the exact Meta account/Page relationship required by the current API is present. Media publishing remains fail-closed on image/video accessibility, rights and current API preconditions. A container/outbox object is not equivalent to a published media receipt.

### Threads lane

Later activation must verify the intended Threads identity, current API permissions and the current publish flow. Creation/preparation and publication receipts must remain distinct. A prepared object is not delivered content.

### LinkedIn / X / Bluesky

- LinkedIn: remain disabled until production API access is confirmed and separately authorized.
- X: remain excluded while the required API is paid under the current canon.
- Bluesky: remain disabled until a later local-ROI test passes and the lane is explicitly added to canonical policy.

## 14. Secret handling rules for future connection

- Never commit credentials, OAuth codes, tokens or secrets to Git.
- Never place credential values in Drive checkpoint prose, screenshots or logs.
- Use environment/secret-store references only after the later activation architecture defines their exact names and storage location.
- Redact authorization headers from logs.
- Rotate credentials if accidental disclosure is suspected.
- A missing secret is a HOLD, never a reason to weaken authentication.

## 15. Incident evidence bundle

For any P0/P1 operational incident preserve:

- Git commit SHA;
- Drive checkpoint ID/revision;
- runtime policy hash;
- operator profile hash;
- database hash and last verified backup hash;
- event-log head hash;
- failing command/test and exact error class;
- timestamps;
- recovery action taken;
- post-recovery preflight result.

Do not store credential values in the evidence bundle.

## 16. Pilot-entry gate

PUBLIC PRESENCE OS is not pilot-ready merely because CP32 passes. Pilot entry additionally requires the remaining validated executable modules to exist in the canonical source tree, complete synthetic end-to-end rehearsal, a validated connection package, current API verification, and an explicit later decision to connect real accounts/deploy.

Until then the correct terminal state is PRE-PILOT / LOCAL-ONLY / FAIL-CLOSED.
