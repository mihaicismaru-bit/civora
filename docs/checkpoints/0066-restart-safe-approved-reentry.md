# CIVORA Checkpoint 0066 — Restart-Safe Approved Re-entry

Status: CODE_COMPLETE_CI_PENDING

## Objective

Close the process-restart gap in editorial approval re-entry. Prior behavior could resume an approved story only when the in-memory `StoryObject` survived. Production recovery must reconstruct the story from durable state after a real process restart.

## Implementation

- Added explicit fail-closed `StoryObject` rehydration from checkpoint dictionaries in `civora/story_codec.py`.
- Added `resume_approved_story(state_dir, story_id, version)` in `civora/resume.py`.
- Re-entry loads the durable `editorial_review` checkpoint, constructs fresh Review Queue and Transaction Journal instances, creates a fresh Orchestrator, runs startup recovery/consistency gates, and only then invokes the existing approval re-entry path.
- Existing stale-approval, semantic-hash, approval-state and Review Queue invariants remain authoritative.

## Validation added

`tests/test_restart_resume.py` simulates a crash window after the approval store is updated but before Review Queue and transaction commit are completed. A fresh process-equivalent resume path must replay the prepared transaction, reconcile the queue, pass startup health, rehydrate the story, and reach `PACKAGED` with durable `editorial_approved` and `packaged` checkpoints.

## Gates

- DURABLE_STORY_REHYDRATION: PASS_IMPLEMENTATION
- FAIL_CLOSED_CODEC: PASS_IMPLEMENTATION
- FRESH_ORCHESTRATOR_RESTART_PATH: PASS_IMPLEMENTATION
- PREPARED_APPROVAL_REPLAY_BEFORE_REENTRY: PASS_IMPLEMENTATION
- CROSS_STORE_CONSISTENCY_BEFORE_REENTRY: PASS_IMPLEMENTATION
- APPROVED_TO_PACKAGED_RESTART_PATH: PASS_IMPLEMENTATION
- DURABLE_POST_REENTRY_CHECKPOINTS: PASS_IMPLEMENTATION
- CROSS_PLATFORM_CI: PENDING_CURRENT_CI

## Remaining backlog

1. Unified health/CLI visibility for editorial cross-store consistency.
2. Operator CLI command for durable approved-story resume.
3. Story Engine constrained strictly to authorized/corroborated facts.
4. Operator remediation and recovery runbooks.

## Next action

Validate checkpoint 0066 in cross-platform CI. If green, wire cross-store consistency into the unified health output and expose the restart-safe approved re-entry through the operator CLI.
