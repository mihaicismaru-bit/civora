# EUCONS PHP runtime adapter

This adapter is the E29 shared-hosting binding for the canonical EUCONS lead intake. It exists because the authorized `eucons.ro` cPanel environment exposes PHP but no Python/Node application runtime.

## Canonical ownership

Business logic, schemas and validation remain under `civora/eucons`. The PHP adapter reads the canonical E11 `lead_contract.json` and `forms.json` directly. No business content is maintained in cPanel.

## Production layout

Recommended cPanel Git clone:

- repository: `https://github.com/mihaicismaru-bit/civora.git`
- clone root: `/home/eucons/civora-runtime`
- `api.eucons.ro` document root: `/home/eucons/civora-runtime/eucons/runtime/php/public`
- default PII storage root: `/home/eucons/eucons-data`

The data root is outside the public document root and outside Git. The runtime fails closed if the configured data root is placed under the active web document root.

## HTTP contract

- `POST https://api.eucons.ro/api/leads`
- exact browser origins: `https://eucons.ro`, `https://www.eucons.ro`
- accepted transport: form-urlencoded or multipart form data
- success: HTTP 202 with only `status`, `request_id`, `next_action`
- no PII in response receipts or application logs

## Activation gate

Do not treat the endpoint as production-enabled until all are true:

1. `api.eucons.ro` points to the authorized hosting IP;
2. HTTPS is valid;
3. cPanel serves this validated CIVORA head;
4. `/home/eucons/eucons-data` is writable;
5. a synthetic live POST passes;
6. the public EUCONS build has been post-processed with `deployment/activate_php_runtime.py` and redeployed.

No credential is stored in this repository.
