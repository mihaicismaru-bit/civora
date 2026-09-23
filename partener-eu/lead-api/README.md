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
