# Română pentru Muncă — lead API

Target architecture:
- Landing: https://partener.eu/romana-pentru-munca/
- API: Cloudflare Worker
- Database: Cloudflare D1
- Table: rpm_leads

## One-time Cloudflare setup

1. Create D1:
   npx wrangler@latest d1 create partener-rpm-leads --location=eeur

2. Put the returned database_id in wrangler.toml.

3. Apply schema:
   npx wrangler@latest d1 execute partener-rpm-leads --remote --file=schema.sql

4. Replace IP_SALT with a random secret (prefer a Worker secret in production):
   npx wrangler@latest secret put IP_SALT

5. Deploy:
   npx wrangler@latest deploy

6. Copy the Worker URL and set it in the landing's data-api attribute.

## Lead lifecycle
NEW -> CONTACTED -> QUALIFIED -> WON / LOST

## Privacy
Only business lead data needed for quotation is stored. Raw IP is not stored; only a salted SHA-256 hash is persisted for abuse analysis.

## Evidence, tests and deployment guard

The checked-in `wrangler.toml` still has `REPLACE_WITH_D1_DATABASE_ID`.
**This is a deploy-time blocker, not proof that the existing remote Worker has no D1.**
Do not guess the D1 identifier or commit Cloudflare credentials.

1. Run `node partener-eu/ops/test_rpm_lead_worker.mjs` in repository root.
   This is a **mocked in-memory contract only**; it does not submit leads or access production.
2. In the authorized Cloudflare account, confirm the exact D1 database binding and
   `rpm_leads` schema; replace the placeholder only with the actual database ID
   returned by Cloudflare, and provision `IP_SALT` as a Worker secret.
3. Deploy the Worker through authorized Cloudflare tooling, preserving its current
   hostname, CORS, privacy and fallback contracts.
4. Run `python partener-eu/ops/probe_rpm_lead_health.py` from a network with
   access to the live Worker, or dispatch `PARTENER.EU RPM Lead Contract`
   with `live_health=true`.
   `GET /health` executes read-only `SELECT lead_id FROM rpm_leads LIMIT 0`.
   `READY` proves only that the D1 binding and table can be read.
5. An **actual POST → D1 insertion → CRM/status readback** remains
   `HUMAN_AUTHORIZED_E2E_PENDING` until a controlled test with an explicitly
   authorized synthetic lead and cleanup is performed. Do not call it PASS from
   mock tests or read-only health alone.

Failures in D1 `prepare/bind/run` return HTTP 503
`PERSISTENCE_UNAVAILABLE` and **never a success confirmation**.
The landing retains its email fallback; failures must not expose personal details,
SQL, tokens or D1 internals.
