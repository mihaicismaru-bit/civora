# PUBLIC PRESENCE OS — META LIVE AUTONOMY CHECKPOINT

Date: 2026-10-06
Stage: `HOLD_META_HTTP_400_GRAPH_100`
Internal readiness: bounded hardening tested locally; exact-head GitHub CI required before merge.
Safety: `KILL_SWITCH=ENGAGED`, `LIVE_WRITE=false`, writes LOCKED, Threads HOLD_EXTERNAL. Zero social writes and zero Meta calls in this continuation.

## Baseline and provenance

PR #1367: https://github.com/mihaicismaru-bit/civora/pull/1367
Audited PR head: `a0d8dae23b3667abdb6e2ed86343b89692700860`.
Audited main: `7f8e6b283dcd98b09d41edf77cbfd5192fd5f2c5`.
CI run `37427293500` matches that PR head: shards 1/3 SUCCESS, 0/2 IN_PROGRESS at audit; validation incomplete. Earlier green runs cannot validate a changed head.

Latest live state comes from the owner's continuation and referenced conversation: run `37411789319`, latest attempt job `112148805751`, `HOLD_META_HTTP_400_GRAPH_100`. No Meta call or secret inspection was performed here. Historical expiry `HOLD_META_HTTP_401_GRAPH_190_SUB_463` is superseded. Graph 100 is ambiguous: PAGE READ AUTHORITY / TOKEN TYPE / PAGE ACCESS OR PERMISSION CONTEXT unresolved. It does not prove expiry, a User token, or a wrong Page ID.

## Internal repairs and validation

- First Page probe remains Graph-safe `fields=id,name`.
- Page credential `/me?fields=id,name` must resolve to Page `2816314015107071`. A User credential in the Page slot fails closed even if it can read the Page object. This proves subject, not app identity or every scope.
- Separate Page linkage read must return `instagram_business_account.id=17841429701593250` before content ingestion. Direct IG profile access alone is insufficient binding evidence.
- Graph 100 classifier retains only numeric diagnostics and preserves ambiguity; HTTP 400 is never retried. Raw error messages, traces and bodies are not persisted.
- Malformed, negative/non-finite Retry-After values fall back to bounded delays; ceiling 30 seconds, maximum four attempts.
- SA2.3 serialized restart regression replays duplicates ten times while preserving sequence, last event and accepted count, with one duplicate increment per replay.
- Promotion stays HOLD_READINESS_EVIDENCE_INCOMPLETE whenever any prerequisite is missing. Approval readiness requires real ingestion, exact binding, shadow acceptance, calibration, kill switch, idempotency and retry evidence.
- Shadow workflow has no push/schedule trigger. Explicit dispatch requires a non-secret material-change reference. This is operator attestation, not automatic proof of rotation; never dispatch again for an unchanged blocker.
- CI emits 20 slowest durations to identify the CP54–CP82 bottleneck without removing coverage.

Validation: 92 targeted offline tests PASS, 15 productization tests PASS, product layout validation PASS, release package built. Targeted coverage includes authority/binding, runtime, controlled-writer failure soak, kill-switch before/mid-queue, ambiguous-write no-retry, idempotency, SA2.1–SA2.5 and shadow calibration. Windows compileall cache writes hit the long-path limit in existing CP75–CP82 filenames; full source syntax is checked in memory instead. Linux exact-head CI compileall and full suite remain required.

No new real observations were collected. Calibration still requires at least 100 real observations and complete evaluations. Synthetic tests and a successful identity probe do not establish READY_FOR_LIMITED_WRITE_APPROVAL.

Minimum provisioning permissions do not establish all comment permissions. The full read preflight may HOLD on restricted Facebook/Instagram comments. Do not add instagram_manage_comments or other write-capable scopes, skip failures, or reinterpret partial reads as PASS. The capability matrix keeps live entitlement UNVERIFIED.

## HUMAN ACTION PACKET — only credential provisioning

1. In Meta Graph API Explorer select existing **presence os**, app ID `1488219383133581`. Use the Facebook user already authorized to manage Page `2816314015107071`. Obtain a **User Access Token** for that app with minimum relevant permissions `pages_show_list`, `pages_read_engagement`, `instagram_basic`, and access to the existing Page. Do not change account relationships, connect Threads or add write scopes.
2. Privately, using that User token, request `GET /v26.0/me/accounts?fields=id,name,access_token,instagram_business_account&limit=100`. Follow pagination privately if necessary. Select exactly `id=2816314015107071` and verify `instagram_business_account.id=17841429701593250`. That entry's **access_token** is the Page Access Token; the User token must not go into the Page secret.
3. If the Page is absent, linkage mismatches or permissions are unavailable, stop and report only the non-secret condition. Do not change accounts or widen scopes. In Meta's private token debugger verify validity, app ID `1488219383133581` and Page credential/destination. Never send token or debugger output to chat, logs or repo.
4. GitHub → mihaicismaru-bit/civora → Settings → Environments → **public-presence-shadow** → Environment secrets → replace only **META_PAGE_ACCESS_TOKEN** with that selected Page token. Transfer only through private Meta→GitHub provisioning; never paste it into chat, files, terminal commands, workflow inputs or reports.
5. Leave `KILL_SWITCH=true`, `LIVE_WRITE=false`, `META_THREADS_ENABLED=false`. Report only completion and a non-secret rotation time/reference.

Sources: [Meta Page token request](https://www.postman.com/meta/instagram/request/lpx8lul/get-access-tokens-of-pages-you-manage), [Meta Instagram API](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api).

## Next exact action

1. Require all CI checks on final PR head; merge only with checks passing and no-push shadow trigger present. Recheck main commit/product validation. Never rerun historical preflight.
2. After confirmed material credential/config change, dispatch exactly one current-main PUBLIC PRESENCE SHADOW PREFLIGHT with a non-secret material_change_reference. Require correct Page subject, explicit Page→IG linkage, READ CAPABILITIES PASS, Threads HOLD_EXTERNAL, writes LOCKED, kill switch ENGAGED and zero writes. On HOLD stop after one sanitized diagnostic.
3. After read authority passes, collect bounded real read-only events and evaluate shadow calibration, preserving capability holds and real sample counts.
4. Only when all evidence gates pass, report READY_FOR_LIMITED_WRITE_APPROVAL and request explicit owner approval for a concrete limited action. Stop before the first social write. This checkpoint grants no write scope or execution authority.
