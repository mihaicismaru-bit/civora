# Scope-aware persistence drift acceptance

This increment separates repository movement from CIVORA-scope movement in the shared monorepo.

Acceptance invariants:

- A commit that changes only `partener-eu/**` may advance repository HEAD without changing the configured CIVORA scope fingerprint.
- A change under `local-news-os/**`, `valcea-clar/**`, or the matching LOCAL NEWS OS / VÂLCEA CLAR workflows changes the scope fingerprint and requires reconciliation.
- Fingerprints are deterministic for identical trees and config.
- The classifier is generic code; product-specific path ownership lives in `repository_scope.json`.
- The result is advisory input to persistence. It does not claim deployment, publication, or external state.
