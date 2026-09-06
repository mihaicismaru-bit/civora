# CP48 — Versioned Visual Identity Supersession + Exact Font/Licence Binding v1

Status: PASS_CONTRACT / STAGED_FAIL_CLOSED / PRE-PILOT

## Scope

CP48 resolves the unrecoverable historical-font-hash problem by creating a new identity revision, `EDITORIAL_LEDGER_V2`, rather than claiming byte-for-byte equivalence with CP29. The visual grammar remains deliberately continuous with the CP29 canon: warm paper/ink palette, signal vermilion, annotation blue, square geometry, source/folio structure, disciplined Marginalia, and the same typography roles. The material identity change is the explicit binding of the four local font files to newly observed exact SHA-256 values and embedded OFL-1.1 licence evidence.

This checkpoint does not activate the new identity inside the CP40 renderer or CP41 QA path. It creates the canonical V2 contract and an executable local verifier. Activation remains fail-closed and is the next granular unit.

## Exact font binding

- DISPLAY — Inter Display SemiBold — `991234562ac06b47aefa2ca4d4ff74360a164a5653ec05357816fc4ffe3ca8a2`
- EDITORIAL — Noto Serif Regular — `9d7583b7dc9e812afd32a14280c5cac3160012efe50c8d08938f4fea266ff67f`
- EDITORIAL_ITALIC — Noto Serif Italic — `bc25600aa27cd409e1e5b3d86340df3a329bb860fcfbe57a03a95070b229e1b0`
- MARGINALIA — Noto Sans Mono Medium — `c6107a9c14e9d33db347299fc467fb52c473919050d1be7c661869107eeffc06`

Derived binding hashes:

- font binding hash: `a3edbdb93a494a9dcac436e3395be078d746a731c1fbb75caad7300d65c7d4af`
- identity profile hash: `8678c85bb7addc1c1d4ccabf9c6116c2a1f74a89c8146d240b877a9b86eb90bf`

Font files are not stored in the repository or release package. An operator must supply local files that match the exact hashes. Verification is local-only and performs no network request.

## Licence binding

The four exact font files expose SIL Open Font License 1.1 metadata in their embedded name tables. `config/font_license_manifest.json` binds the exact file hash to family/style/PostScript/version metadata, `OFL-1.1`, the embedded licence URL, and the SHA-256 of the embedded licence text. This is provenance evidence for the selected exact bytes; it is not a bundled font licence file and does not redistribute font software.

## Canon preserved

Active lanes remain Facebook Page, Instagram Professional and Threads. LinkedIn remains gated on production API access; X remains excluded while the API is paid; Bluesky remains HOLD_ROI. Marginalia cannot create new facts. PHOTO_FRAME keeps factual overlays prohibited and captions/credits outside the photograph. No paid dependency is introduced.

## Safety / authority

`M18_VISUAL_IDENTITY` has identity-contract authority only. It has no runtime activation, queue, publisher, network, account-connection, public-publish or deploy authority. CP48 does not touch real accounts and does not publish anything.

## Validation contract

`public_presence_os.identity_v2` deterministically recomputes the exact font-binding and identity-profile hashes from the contract, cross-validates the V2 policy against the font licence manifest, and verifies operator-supplied local font files fail-closed by SHA-256. `scripts/verify_identity_v2.py` exposes the local verifier without network access. Tests assert exact digest stability, OFL evidence binding, absence of packaged font bytes and fail-closed behavior on mismatched bytes.

## Decisions

D48.1 `EDITORIAL_LEDGER_V2` is the accepted versioned successor to `EDITORIAL_LEDGER_V1` for future pilot activation.

D48.2 CP48 does not assert that its font bytes reproduce CP29 byte-for-byte. `historical_cp29_byte_equivalence_asserted=false` is canonical.

D48.3 Exact SHA-256 is the material font identity; family/style names alone are insufficient.

D48.4 Licence provenance is bound to the exact selected bytes using embedded name-table metadata and a deterministic evidence hash.

D48.5 Font bytes remain external local prerequisites and are never bundled in the repository/package.

D48.6 The active social lanes and zero-cost/no-paid-service rules are unchanged.

D48.7 Runtime activation is deliberately deferred one granular unit so the current renderer/QA cannot silently accept the new identity without exact binding checks.

## Changelog

- Added `config/visual_identity_v2_policy.json`.
- Added `config/font_license_manifest.json`.
- Added executable `src/public_presence_os/identity_v2.py`.
- Added local verifier CLI `scripts/verify_identity_v2.py`.
- Added CP48 contract tests.
- Advanced module/reimplementation registries to CP48 and set the next unit to runtime activation + QA binding.

## Blockers / deferred

Pilot remains HOLD because the CP40 renderer and CP41 QA still implement the legacy CP29-equivalence hold. The blocker is no longer missing knowledge about what V2 font bytes should be; it is now a bounded runtime-integration task: `CP49_IDENTITY_RUNTIME_ACTIVATION_AND_QA_BINDING`.

## Rollback

Rollback is configuration/source-only: revert the CP48 commit/PR. CP40 renderer, CP41 QA, real accounts, queue/publisher external writes and deployment remain untouched, so rollback has no external side effects.

## Next granular unit

CP49 — Identity Runtime Activation + QA Exact-Binding Gate v1: wire `EDITORIAL_LEDGER_V2` exact font-binding/profile hashes into M06 and M07, keep fail-closed behavior for any mismatch, and prove the synthetic path can clear only the identity HOLD without enabling network/account/publish/deploy authority.
