# S-A2.1 — META READ-ONLY RUNTIME CREDENTIAL / ENV CONTRACT

Date: 2026-09-30  
Parent evidence: S-A1 Meta real-world access closure.

## Status

**IMPLEMENTED / TEST-BOUND / ZERO NETWORK AUTHORITY**

This is the first granular S-A2 unit after the owner-directed transition from the CP92 offline roadmap into real Meta read-only observability preparation.

## Purpose

Define the exact runtime binding boundary for the three identities proven in S-A1, without committing, logging, hashing, returning, resolving, refreshing, or transmitting any credential.

Verified identity bindings:

- Facebook Page: 2816314015107071
- Instagram Professional: 17841429701593250
- Threads user: 28391623420464631

## Runtime environment contract

Non-secret bindings:

- PPOS_META_PAGE_ID
- PPOS_META_IG_USER_ID
- PPOS_THREADS_USER_ID
- PPOS_META_GRAPH_API_VERSION
- PPOS_THREADS_API_VERSION

Secret bindings:

- PPOS_META_USER_ACCESS_TOKEN
- PPOS_META_PAGE_ACCESS_TOKEN
- PPOS_THREADS_USER_ACCESS_TOKEN

The module never reads os.environ itself. A future runtime boundary must explicitly pass a mapping into the validator. This keeps secret acquisition outside the pure contract and makes accidental implicit credential reads test-detectable.

## Read-only scope floor

Facebook Page:
- pages_show_list
- pages_read_engagement

Instagram Professional through Facebook Login:
- pages_show_list
- pages_read_engagement
- instagram_basic

Threads:
- threads_basic

The contract explicitly marks publishing/moderation write scopes as forbidden at this stage.

## Token handling

The validator checks only that a caller-supplied secret value is present, non-placeholder and structurally non-empty. Secret bytes are never included in receipts, hashed, persisted, logged, copied into policy, or returned by the redacted operator contract.

## Authority

S-A2.1 does not grant transport authority. It keeps network, publish, external-write and deploy authority OFF. The global kill switch remains required and engaged.

The state READY_FOR_EXPLICIT_READ_ONLY_TRANSPORT_WIRING means only that runtime inputs are structurally suitable for the next unit.

## Current Meta contract evidence

The selected Instagram route is Facebook Login, not Instagram Login. Its read-only floor therefore uses instagram_basic with Page permissions. The Meta-maintained Instagram API collection documents a User Access Token for Page discovery and a derived Page Access Token for the linked Page/Instagram profile.

Threads remains on the separate graph.threads.net authorization family; threads_basic is sufficient for the basic profile/read authorization and token exchange/refresh path.

## Files

- src/public_presence_os/meta_read_only_runtime_contract.py
- config/meta_read_only_runtime_contract_policy.json
- tests/test_sa2_1_meta_read_only_runtime_contract.py
- this checkpoint document
- M62 registry entry

## Next granular unit

**S-A2.2 — normalized Meta read-only transport adapter**

It may consume only a validated S-A2.1 receipt plus caller-supplied secret material at the transport boundary. It must implement GET-only allowlisted requests, redact credentials from errors/receipts, preserve UNKNOWN for unavailable fields, and retain zero external-write authority.
