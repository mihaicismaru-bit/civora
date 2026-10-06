# PUBLIC PRESENCE OS — META LIVE AUTONOMY CHECKPOINT

Date: 2026-10-06
Stage: `HOLD_META_PAGE_TOKEN_EXPIRED`
Safety: `KILL_SWITCH=ENGAGED`, `LIVE_WRITE=false`, write capabilities locked, zero external writes.

## Changelog

- Re-ran the historical failed preflight once and confirmed that GitHub reruns the historical workflow definition rather than the current `main` definition; that rerun did not exercise `META_PAGE_ACCESS_TOKEN`.
- Hardened `.github/workflows/public-presence-shadow.yml` so the current shadow contract fails closed when `META_PAGE_ACCESS_TOKEN` is absent, without logging or exposing the secret.
- Triggered current-main bounded shadow preflight run `37411655710`; the Page token was present, the locked shadow contract passed, but the first live Page identity GET returned HTTP 401.
- Hardened `meta_live_runtime.py` to retain only secret-free Meta HTTP diagnostic codes from an error response.
- Triggered one diagnostic bounded shadow preflight run `37411789319`; result: `HOLD_META_HTTP_401_GRAPH_190_SUB_463`.
- No further live Meta calls are authorized while this blocker is unchanged.

## Read-only live state

- META APP: PASS
- FACEBOOK AUTH contract: PASS
- PAGE IDENTITY: NOT EVALUABLE because authentication failed before identity payload
- INSTAGRAM BINDING: NOT EVALUABLE because Page authority failed first
- THREADS IDENTITY: HOLD_EXTERNAL
- READ CAPABILITIES: FAIL
- WRITE CAPABILITIES: LOCKED
- KILL SWITCH: ENGAGED
- LIVE WRITE: OFF
- EVENT LOG boundary: PASS
- External writes: 0

## Decision

Treat Graph error code `190` with subcode `463` as an expired access-token blocker. This is an authentication-expiry failure, not evidence of a Page identity mismatch and not evidence of a read-scope denial. Do not widen scopes or enable write authority in response.

## Blocker

`HOLD_META_PAGE_TOKEN_EXPIRED`

The currently provisioned `META_PAGE_ACCESS_TOKEN` in GitHub environment `public-presence-shadow` is present but expired. Its value was not read, printed, copied, logged, or persisted by this checkpoint.

## HUMAN ACTION PACKET

1. Replace only the GitHub environment secret `META_PAGE_ACCESS_TOKEN` in `public-presence-shadow` with a fresh, non-expired Page access token for Facebook Page `2816314015107071`, produced through the existing Meta app/login flow.
2. Keep `KILL_SWITCH=true`, `LIVE_WRITE=false`, `META_THREADS_ENABLED=false`; do not add write scopes and do not connect Threads.
3. No repository edit is required from the owner.
4. After secret replacement, the next autonomous unit is exactly one bounded shadow preflight. If it passes, continue to read-only `meta-sync` and real-event `meta-shadow`; otherwise stop after one secret-free diagnostic.

## Next exact action

Await fresh Page-token provisioning. On the first hourly run after the secret changes, execute exactly one current-main bounded shadow preflight and require:
- PAGE IDENTITY PASS for `2816314015107071`
- INSTAGRAM BINDING PASS for `17841429701593250`
- READ CAPABILITIES PASS
- THREADS IDENTITY HOLD_EXTERNAL
- WRITE CAPABILITIES LOCKED
- zero writes

## Evidence

- Workflow hardening commit: `4cdf8f925128364cf82cb04f4ae12bf4eaf3a7c8`
- Current-main first bounded preflight: `37411655710`
- Secret-safe diagnostic hardening commit: `28a62632144726c8835e4a4f59645116da753a49`
- Diagnostic bounded preflight: `37411789319`
