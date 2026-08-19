# EUCONS Architecture v1

## Control plane

GitHub is the control plane and durable source of truth for development state:

- repository content and schemas;
- Git history and rollback;
- GitHub Actions orchestration;
- QA gates and receipts;
- static preview deployment;
- artifact/state registries.

## Logical architecture

```text
PARTENER verified projection ----\
Euroconsult evidence registry ----> EUCONS normalization -> public/commercial projections
Service registry -----------------/                         |        |        |
                                                            site     leads    content
                                                                     |        |
                                                                     CRM      social/email outboxes
                                                                     |
                                                                     matching -> offers
```

## Repository layout

```text
eucons/
  canon/
  brand/
  services/
  people/
  cases/
  opportunities/
  leads/
  crm/
  offers/
  editorial/
  social/
  analytics/
  legal/
  runtime/
  web/
  deployment/
  validation/
  ops/
```

Directories are materialized only when their first canonical artifact is introduced; empty directory placeholders are forbidden.

## State model

Every state-changing autonomous unit records:

- stable run id;
- source revision/input hashes;
- output artifact hashes where applicable;
- start/completion timestamps;
- status (`PASS`, `HOLD`, `FAIL`, `BLOCKED_EXTERNAL`);
- retry/recovery metadata;
- previous checkpoint.

Writes follow `prepare -> validate -> commit -> receipt`. A failed validation cannot advance the canonical checkpoint.

## Deployment abstraction

The web build must be static-first and deployable from a generated directory. GitHub Pages is the development preview target. Production deployment must not require a rewrite of EUCONS content schemas, business logic or build outputs.

Dynamic runtime concerns (lead submission, transactional email, CRM writes) are implemented behind provider-neutral adapter contracts and fully dry-run tested before final hosting selection.

## Security

- No secrets in repository content or generated static assets.
- No PII in committed test fixtures unless synthetic.
- Public build consumes only explicitly public projections.
- Any future secret-bearing adapter reads credentials from deployment secret storage/environment only.
