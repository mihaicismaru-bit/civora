# MySMIS Connector bounded installation handoff

This package is an offline-preflight artifact, not authorization to access MySMIS.

Before any installation:

1. Extract the ZIP to a new empty folder and run `CONTROL\\VERIFY_OFFLINE.cmd` from Command Prompt. It only verifies bytes and emits a JSON receipt; it does not install anything.
2. Verify that the receipt status is `INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED` and archive it before continuing.
3. Verify the exact Git source head, paired-build receipt, bundle manifest digest and every payload SHA-256.
4. Stop if the preflight reports a missing, changed, duplicate, symbolic-link or extra payload/control file.
5. Confirm that the MCLENOVO session is observable and that the user has authorized the bounded installation.
6. Do not enable `nativeMessaging`, debugger/CDP or external extension messaging unless a later persisted gate explicitly requires and authorizes it.
7. Do not read or persist cookies, passwords, MFA data, tokens or request Authorization headers.
8. MySMIS remains read-only: no Save, Submit, Delete, Sign, Upload or Modify.
9. The Drive command mailbox component does not authorize installation or live dispatch. Do not
   place commands in `COMMAND_INBOX` until a later exact-build package binds the poller to the
   attested fixed dispatcher and persists that authorization.

Rollback:

1. Remove the unpacked extension from Edge/Chrome.
2. Stop the connector agent if it was started.
3. Delete only the newly created connector installation folder.
4. Preserve the bundle manifest, receipts, logs and Drive checkpoint as evidence.
5. Record the failure reason; do not retry changed bytes or bypass preflight.
