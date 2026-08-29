# MySMIS Connector bounded installation handoff

This package is an offline-preflight artifact, not authorization to access MySMIS.

Before any installation:

1. Verify the exact Git source head, paired-build receipt, bundle manifest digest and every payload SHA-256.
2. Stop if the preflight reports a missing, changed, duplicate, symbolic-link or extra payload file.
3. Confirm that the MCLENOVO session is observable and that the user has authorized the bounded installation.
4. Do not enable `nativeMessaging`, debugger/CDP or external extension messaging unless a later persisted gate explicitly requires and authorizes it.
5. Do not read or persist cookies, passwords, MFA data, tokens or request Authorization headers.
6. MySMIS remains read-only: no Save, Submit, Delete, Sign, Upload or Modify.

Rollback:

1. Remove the unpacked extension from Edge/Chrome.
2. Stop the connector agent if it was started.
3. Delete only the newly created connector installation folder.
4. Preserve the bundle manifest, receipts, logs and Drive checkpoint as evidence.
5. Record the failure reason; do not retry changed bytes or bypass preflight.
