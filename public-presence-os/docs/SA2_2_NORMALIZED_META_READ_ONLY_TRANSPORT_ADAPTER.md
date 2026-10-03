# S-A2.2 — NORMALIZED META READ-ONLY TRANSPORT ADAPTER

Date: 2026-09-30  
Parent: S-A2.1 runtime credential/env contract.

## Status

**IMPLEMENTED / GET-ONLY ALLOWLIST / RESPONSE NORMALIZATION / NETWORK EXECUTION OFF**

## Purpose

S-A2.2 converts the verified Meta identity bindings into deterministic read-only request plans and normalizes returned identity/binding evidence without enabling live transport.

The allowlist contains exactly four operations:

1. FACEBOOK_MANAGED_PAGES
2. FACEBOOK_PAGE_IDENTITY
3. INSTAGRAM_PROFILE
4. THREADS_PROFILE

No arbitrary endpoint, method, host, field list or token reference can be supplied by callers.

## Current Meta route evidence

The Instagram lane remains on Instagram API with Facebook Login. The current Meta-maintained Instagram API collection documents graph.facebook.com /me/accounts for managed Page discovery and the Page Access Token derived from the linked Page. The same collection requires a linked Professional Instagram account for this route.

The Threads lane remains on graph.threads.net. The current Meta-maintained Threads collection documents GET /me with profile fields under threads_basic.

S-A2.2 requests no access_token field from Meta. If a supplied response nevertheless contains access_token at the normalized boundary, it fails closed.

## Normalization

The normalizer:

- requires exact stable ID match for Facebook Page, Instagram Professional and Threads;
- requires the Facebook Page to resolve to Instagram ID 17841429701593250;
- maps absent optional fields to UNKNOWN instead of inventing values;
- sorts task values deterministically;
- binds the normalized record to a SHA-256 of the source response;
- rejects secret-bearing response payloads.

## Authority boundary

This unit does not perform HTTP requests. It does not resolve environment variables or tokens.

- request-plan compilation: ON
- response normalization: ON
- method allowlist: GET only
- network execution: OFF
- token resolution: OFF
- external writes: OFF
- publish: OFF
- deploy: OFF
- global kill switch: required

## Artifacts

- src/public_presence_os/meta_read_only_transport.py
- config/meta_read_only_transport_policy.json
- tests/test_sa2_2_meta_read_only_transport.py
- this checkpoint
- M63 registry entry

## Next granular unit

**S-A2.3 — incremental read cursor + event-log ingestion contract.**

It will consume normalized read-only records, persist cursor/event identity without credential material, enforce idempotent replay/deduplication, and keep unavailable metrics as UNKNOWN. Live network execution remains a separate explicit gate.
