# AI4WORK STEP / NF-RUN-001 — live account readback packet

**Status:** CONTROL ARTIFACT / NOT NEED EVIDENCE / COLLECTION DISABLED

This packet reduces the remaining pre-PROD work to account-specific factual readback. It must never contain passwords, MFA codes, API tokens, private keys, session cookies, full support-login links or respondent data. Screenshots/evidence may redact customer IDs and unrelated domains while preserving the setting name, effective value, service/domain identity and timestamp where available.

## 1. cPanel Raw Access — eucons.ro

Capture the **effective** settings for the actual eucons.ro cPanel account, not provider defaults:

- service/account is the one currently serving `eucons.ro`;
- Raw Access enabled/disabled state;
- automatic archive state and archive destination;
- retention/rotation behavior and effective maximum retention;
- authorised roles/persons that can read Raw Access archives;
- evidence that questionnaire bodies, raw idempotency keys and answers are not intentionally application-logged;
- confirmation that answers/direct identifiers are never placed in query strings;
- confirmation that IP/User-Agent/Raw Access are excluded from the analytical store and NF06.

**Acceptance rule:** effective Raw Access retention must be **0–7 days**. Provider-level configurability is not sufficient evidence of the live value.

## 2. Cloudflare / reverse-proxy state

Read back the effective state for `eucons.ro` and `api.eucons.ro`:

- whether each hostname is proxied, DNS-only, or not present in Cloudflare;
- if proxied, which account/zone controls it and which technical/security logs are enabled or retained;
- whether a Cloudflare component can introduce additional request logging or analytics for the research path;
- whether any commercial analytics/pixels are attached to the dedicated research pages or endpoint.

A valid result may be `NOT_IN_PATH`, but that state must be positively verified. Do not infer Cloudflare use merely from provider documentation.

## 3. Current service/account and processor chain

Freeze the actual current mapping:

- controller: EUROCONSULT SRL, CUI 14250864;
- processor: Claus Web SRL, Shared Hosting/cPanel service serving eucons.ro;
- current non-secret account/service reference sufficient to identify the contract/service;
- controller-to-provider instruction reference;
- DPA + Annex 4 + Annex 5 binding references already frozen in NF-RUN-001;
- active subprocessor/service-component subset **actually used** for eucons.ro, with purpose, processing location and Chapter V mechanism where applicable;
- authorised roles that may access respondent-level research data;
- CRM row-level access = forbidden; employer row-level access = forbidden.

Do not promote the whole Annex 4 nominal list as active. Only the verified active subset belongs in the live processor-chain attestation.

## 4. Research-only store isolation

Read back the production paths/configuration without exposing secrets or respondent data:

- canonical research location;
- canonical commercial/CRM data location;
- canonical webroot;
- proof the three are non-overlapping, including symlink/alias check;
- research store is outside webroot and separate from CRM/commercial storage;
- filesystem/database access roles limited to designated research administration;
- direct identifiers and response-to-contact linkage keys are forbidden;
- commercial tracking remains forbidden;
- deletion adapter/reference used for receipt-keyed erasure.

Expected candidate default is `/home/eucons/eucons-research/ai4work-step`, but the live value must be read back rather than assumed.

## 5. Backup / deletion / restore binding

The frozen Claus Web Annex 5 establishes the Shared Hosting standard ceiling of **maximum 92 days** for residual backup unless overridden by offer/order/panel/technical annex. Close the account-specific gap by proving:

- whether an account-specific override exists;
- effective maximum residual backup period is <=92 days;
- deleted research data do not enter a renewed backup lifecycle after live deletion;
- ordinary restore does not silently reintroduce erased or held records into active analysis;
- authorised recovery/legal/incident restoration is separately controlled and reconciled before analytical use.

## 6. Article 13 and rights live readback

After a reversible candidate deployment/staging path is available, capture the exact rendered research surface before any real collection:

- adults and employers routes show the dedicated AI4WORK Article 13 notice before questions;
- `privacy@eucons.ro` is displayed consistently;
- commercial privacy/lead receiver is not used for research;
- requester verification wording uses only `response_id + private verification code`;
- private verification code is retained by the respondent, while only its SHA-256 digest is stored server-side;
- no name/e-mail/CRM/IP/device lookup is introduced for rights authentication;
- Article 15 controller-context template is operational alongside the respondent-record copy.

Independent inbound delivery of `privacy@eucons.ro` must be evidenced without inventing a successful test. No external message is sent from this workflow without explicit user approval.

## 7. Provider-bound TEST TWIN smoke — NON-EVIDENCE

Only after 1–6 are bound, run synthetic fixtures on the same provider/runtime path as PROD and mark them permanently `TEST_TWIN_NON_EVIDENCE`:

- submit;
- canonical export;
- rights verification/access;
- hold/restriction;
- rectification;
- erasure;
- replay suppression and <=24h marker expiry;
- NF06 rejection as NON-EVIDENCE.

The smoke must write **no PROD need evidence** and perform **no real dissemination**.

## Completion boundary

When these live readbacks are frozen as immutable operational evidence and the exact-head gates pass, request a fresh explicit **`collection-only v0.2`** approval. That approval may authorize only real dissemination/collection; it must not authorize merge, deploy, canonicalization or publication by implication.
