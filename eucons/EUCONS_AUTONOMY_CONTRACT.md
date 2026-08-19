# EUCONS Autonomy Contract v1

## Authorization

EUCONS development is authorized to continue without routine owner intervention until `PRODUCTION_READY`.

## Autonomous permissions

The development loop may autonomously:

- choose implementation details consistent with Product Canon and Architecture;
- create/update EUCONS code, schemas, fixtures, documentation and workflows;
- repair failing EUCONS tests and regressions;
- reuse generic CIVORA/PARTENER components through explicit contracts;
- open pull requests and merge EUCONS-only changes after required validation is green;
- create and update preview deployments;
- generate synthetic test data;
- advance the canonical checkpoint only after acceptance gates pass.

## Merge safety rule

Autonomous merge is allowed only when all are true:

1. diff is EUCONS-only or a clearly shared CIVORA primitive with regression coverage for affected siblings;
2. required checks are green;
3. no secrets or real PII are introduced;
4. no unverified commercial/funding claim is promoted;
5. the change is backward-compatible with published EUCONS contracts or includes a tested migration;
6. the branch head reviewed is the branch head merged.

If any condition is false, keep the change isolated and record `HOLD`/`FAIL` with recovery instructions.

## No-owner-interruption rule

Do not request owner decisions for styling details, copy variants, technical library choices, internal priority, retry strategy, test repairs or normal PR lifecycle.

## Permitted final blockers

The only acceptable owner-required blockers at development closure are external ownership/authentication actions that cannot be delegated safely, such as:

- DNS or production hosting account authorization;
- LinkedIn organization/app authorization;
- Facebook Page/Meta app authorization;
- commercial mailbox/API authorization when required.

These blockers must not prevent adapters, contracts, dry-runs and failure/retry behavior from being completed and validated first.

## Stop condition

Do not stop at `MVP` or `looks complete`. Stop autonomous development only at:

- `PRODUCTION_READY`; or
- `BLOCKED_EXTERNAL_ONLY`, when every remaining item is one of the permitted external owner actions above.
