# MySMIS Connector bounded installation handoff

This package is an offline-preflight artifact, not authorization to access MySMIS.

Before any installation:

1. Extract the ZIP to a new empty folder and run `CONTROL\\VERIFY_OFFLINE.cmd` from Command Prompt. It only verifies bytes and emits a JSON receipt; it does not install anything.
2. Verify that the receipt status is `INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED` and archive it before continuing.
3. Verify the exact Git source head, paired-build receipt, bundle manifest digest and every payload SHA-256.
4. Stop if the preflight reports a missing, changed, duplicate, symbolic-link or extra payload/control file.
5. Confirm that the MCLENOVO session is observable and that the user has authorized the bounded installation.
6. Load `PAYLOAD` as an unpacked Edge/Chrome extension and record only its public installed extension ID.
7. Generate the exact-build handoff plan with:
   `node PAYLOAD\native\mclenovo-handoff-cli.mjs --bundle . --extension-id <installed-extension-id>`
   The command only reads the two attested bundle controls and prints a deterministic plan; it does not start the runtime.
8. In the extension options page, paste only the printed `extensionConfig`. A digest or extension-ID mismatch leaves the connector disabled.
9. Start the agent only with the verified plan and an explicit local Drive mailbox root:
   `node PAYLOAD\native\mclenovo-runtime-cli.mjs --plan <verified-plan.json> --mailbox-root <local-drive-mailbox-root>`
10. The first permitted live command is `HEALTH`. Do not place a benchmark command in `COMMAND_INBOX` until its HEALTH result is persisted and read back from Drive.
11. Do not enable `nativeMessaging`, debugger/CDP or external extension messaging.
12. Do not read or persist cookies, passwords, MFA data, tokens or request Authorization headers.
13. MySMIS remains read-only: no Save, Submit, Delete, Sign, Upload or Modify.

Rollback:

1. Remove the unpacked extension from Edge/Chrome.
2. Stop the connector agent if it was started.
3. Delete only the newly created connector installation folder.
4. Preserve the bundle manifest, receipts, logs and Drive checkpoint as evidence.
5. Record the failure reason; do not retry changed bytes or bypass preflight.
