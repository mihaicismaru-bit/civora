# CIVORA Checkpoint 0076 — Release Candidate Preflight

Status: CODE_COMPLETE_CI_PENDING

## Objective

Turn release closure from a narrative checklist into an executable gate without merging, tagging or otherwise performing irreversible release operations.

## Implementation

Added `tools/release_preflight.py`, a deterministic stdlib-only preflight that verifies the repository tree before CIVORA can be considered a v1.0 release candidate.

The preflight checks:

- required release files are present;
- `pyproject.toml` and `civora.__version__` are synchronized;
- the declared Python lower bound remains explicit;
- CI includes Python 3.10 lower-bound coverage;
- Windows-native CI remains present;
- built-distribution smoke validation remains present;
- installed `civora` and `civora-remediation` entrypoints are smoke-tested;
- README declares the current release-closure baseline;
- CHANGELOG contains an Unreleased section before final version lock;
- known CIVORA durable-state filenames and `.env` are absent from the release source tree.

Added `CHANGELOG.md` and `docs/release/v1.0-release-checklist.md` as canonical release-governance artifacts.

The GitHub Actions workflow now has an independent `release-preflight` job invoking the deterministic preflight script.

## Safety properties

- Preflight is read-only.
- It does not merge, tag, publish or mutate runtime state.
- A failed check exits non-zero and blocks technical release closure.
- Version remains pre-v1 until the exact final release head is prepared.
- Human approval remains mandatory before irreversible merge/tag/release.

## Gates

- EXECUTABLE_RELEASE_PREFLIGHT: PASS_IMPLEMENTATION
- REQUIRED_RELEASE_FILE_GATE: PASS_IMPLEMENTATION
- VERSION_SYNC_GATE: PASS_IMPLEMENTATION
- PYTHON_SUPPORT_GATE: PASS_IMPLEMENTATION
- WINDOWS_CI_PRESENCE_GATE: PASS_IMPLEMENTATION
- BUILT_DISTRIBUTION_GATE: PASS_IMPLEMENTATION
- INSTALLED_ENTRYPOINT_GATE: PASS_IMPLEMENTATION
- CHANGELOG_GATE: PASS_IMPLEMENTATION
- DURABLE_STATE_EXCLUSION_GATE: PASS_IMPLEMENTATION
- RELEASE_CHECKLIST_CREATED: PASS_IMPLEMENTATION
- CI_PREFLIGHT_JOB: PASS_IMPLEMENTATION
- EXPANDED_CROSS_PLATFORM_RC_CI: PENDING_CURRENT_CI

## Remaining release backlog

1. Validate 0073, 0075 and 0076 together on the final expanded CI head.
2. If green, create exact release manifest and prepare `1.0.0` version lock.
3. Convert CHANGELOG Unreleased content to the v1.0.0 release entry.
4. Run final CI on that exact versioned head.
5. Require explicit human approval before marking PR ready, merging to main or creating a tag/release.

## Next action

If current expanded CI passes, close 0073/0075/0076 and execute checkpoint 0077 Final Version Lock + Release Manifest. If any Python 3.10, package-smoke, release-preflight, Linux or Windows job fails, repair that failure first and keep v1.0 blocked.
