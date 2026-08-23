# CIVORA Checkpoint 0066 — Restart-Safe Approved Re-entry

Status: CLOSED_VALIDATED

## Objective

Close the process-restart gap in editorial approval re-entry. Prior behavior could resume an approved story only when the in-memory `StoryObject` survived. Production recovery must reconstruct the story from durable state after a real process restart.

## Implementation

- Added explicit fail-closed `StoryObject` rehydration from checkpoint dictionaries in `civora/story_codec.py`.
- Added `resume_approved_story(state_dir, story_id, version)` in `civora/resume.py`.
- Re-entry loads the durable `editorial_review` checkpoint, constructs fresh Review Queue and Transaction Journal instances, creates a fresh Orchestrator, runs startup recovery/consistency gates, and only then invokes the existing approval re-entry path.
- Existing stale-approval, semantic-hash, approval-state and Review Queue invariants remain authoritative.

## Validation

`tests/test_restart_resume.py` simulates a crash window after the approval store is updated but before Review Queue and transaction commit are completed. A fresh process-equivalent resume path replays the prepared transaction, reconciles the queue, passes startup health, rehydrates the story, and reaches `PACKAGED` with durable `editorial_approved` and `packaged` checkpoints.

GitHub Actions run `31218351939` completed successfully for head `222e59561f8094f8366dec28921a246f6d25eb72`, closing the cross-platform validation gate.

## Gates

- DURABLE_STORY_REHYDRATION: PASS
- FAIL_CLOSED_CODEC: PASS
- FRESH_ORCHESTRATOR_RESTART_PATH: PASS
- PREPARED_APPROVAL_REPLAY_BEFORE_REENTRY: PASS
- CROSS_STORE_CONSISTENCY_BEFORE_REENTRY: PASS
- APPROVED_TO_PACKAGED_RESTART_PATH: PASS
- DURABLE_POST_REENTRY_CHECKPOINTS: PASS
- CROSS_PLATFORM_CI: PASS

## Remaining backlog

1. Unified health/CLI visibility for editorial cross-store consistency.
2. Operator CLI command for durable approved-story resume.
3. Story Engine constrained strictly to authorized/corroborated facts.
4. Operator remediation and recovery runbooks.

## Next action

Proceed to checkpoint 0067: expose cross-store consistency through unified health and operator CLI, and expose restart-safe approved re-entry as a machine-readable operator command.
