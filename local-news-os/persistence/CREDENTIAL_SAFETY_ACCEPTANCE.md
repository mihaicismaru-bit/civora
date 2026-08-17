# CIVORA Persistence Credential Safety V1 — PRS-039 acceptance

Scope: `CORE_GENERIC`.

Durable persistence may contain credential reference names and verification state only. Runtime credential values remain outside persistence regardless of provider, publication instance, deployment target, or social channel.

Acceptance invariants:

1. Credential reference names such as `FACEBOOK_PAGE_ACCESS_TOKEN` may be persisted when they are identifiers only.
2. Verification state such as `VERIFIED_PRESENT`, `UNCONFIRMED`, `MISSING`, or equivalent status metadata may be persisted without the underlying credential value.
3. External credential value fields including passwords, API keys, access/refresh/auth/bearer/OAuth tokens, client/app/webhook secrets and private keys are rejected fail-closed before any transport write.
4. Authorization Bearer material and private-key PEM material are rejected even when embedded in otherwise unstructured text.
5. Detection diagnostics expose only field/path and reason. They never echo the detected value.
6. Redacted/empty placeholders are accepted because no credential value is retained.
7. Internal persistence coordination fields such as the writer lease token are not treated as external service credentials.
8. The persistence writer returns `PERSISTENCE_BLOCKED`, `synchronized=false`, and performs zero target writes when credential-value material is detected.
9. The guard contains no Vâlcea identity, provider-specific secret name, geography, route, source, brand or instance pipeline fork.

Executable evidence:

- `python local-news-os/persistence/credential_safety.py --self-test`
- `python local-news-os/persistence/persistence_writer.py --self-test`
