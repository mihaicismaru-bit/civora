# SA2.8 — Meta shadow preflight workflow contract

Date: 2026-10-04
Status: IMPLEMENTED_PENDING_CI

## Checkpoint
- Added root GitHub Actions workflow `.github/workflows/public-presence-shadow.yml` bound to environment `public-presence-shadow`.
- Runtime contract is locked to Facebook Page `2816314015107071` and Instagram Professional `17841429701593250`.
- Threads remains `HOLD_EXTERNAL` through `META_THREADS_ENABLED=false`; LinkedIn/X/Bluesky posture is unchanged.
- `LIVE_WRITE=false`, kill switch engaged, repository permission `contents: read`, checkout credentials not persisted.

## Changelog
- Added a dispatch-only shadow workflow contract with no social network call and no secret reference in repository content.
- Added CI path coverage so edits to the shadow workflow invoke PUBLIC PRESENCE OS CI.
- Added productization tests for IDs, read-only posture, environment binding, absence of secret references and absence of live/sync/shadow execution.

## Decisions
- GitHub environment `public-presence-shadow` remains the only intended credential boundary.
- Repository source must not contain or print credential values.
- The workflow stays offline/contract-only until the environment-secret binding can be installed through an allowed control path.
- No `meta-preflight --live`, `meta-sync`, `meta-shadow`, artifact upload, deploy, or social write is admitted by this checkpoint.

## Blockers
- Connector safety controls rejected creation of a workflow containing direct GitHub Secrets references before any commit was made.
- Therefore the two existing FB/IG credentials are not yet wired into the workflow. Their values were not read, copied, logged, or requested.

## Next exact action
Install the secret-safe environment binding for the existing FB/IG credentials through an allowed GitHub control path, then run bounded `meta-preflight --live`. The run must fail closed unless the exact Facebook Page and Instagram Professional identities match the pilot IDs.
