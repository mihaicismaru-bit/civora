import assert from "node:assert/strict";
import test from "node:test";
import {
  computeInstallationAuthorizationDigest,
  createAuthorizedInstallationPlan,
  InstallAuthorizationError,
  transitionInstallationState,
  validateInstallationAuthorization
} from "../native/install-authorization.mjs";

const NOW = () => new Date("2026-08-29T22:50:00.000Z");
const HEAD = "e0dfba9cbb77ebe64c5a29e3a5d372baa9c41f06";
const PAIR = "2e320c444192cd6f244b462df1d0ee9e2d101826786c336f2f293de373c6cc2a";
const MANIFEST = "0944a259739f0bde41e77a07ff4ba8c6993bff4032c24ea5a90d0b3089e4dbcf";

function preflight() {
  return {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-OFFLINE-013",
    recordedAt: "2026-08-29T22:45:00.000Z",
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    payloadFileCount: 23,
    extensionFileCount: 11,
    agentFileCount: 19,
    installState: "NOT_STARTED",
    rollbackState: "NOT_REQUIRED",
    browserInstallationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  };
}

function authorization(overrides = {}) {
  const value = {
    schemaVersion: 1,
    status: "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL",
    authorizationId: "AUTH-MCLENOVO-013",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-013",
    machineAlias: "MCLENOVO",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: "ATTEMPT-MCLENOVO-OFFLINE-013",
    operations: ["LOAD_UNPACKED_EXTENSION", "RUN_LIVE_HEALTH", "START_LOCAL_AGENT"],
    controls: {
      operatorPresenceRequired: true,
      browserInstallation: "MANUAL_BOUNDED",
      localAgentStart: "MANUAL_BOUNDED",
      nativeMessagingEnabled: false,
      mysmisAccessAllowed: false,
      mysmisWritesAllowed: 0,
      remoteShellAllowed: false,
      credentialAccessAllowed: false
    },
    issuedAt: "2026-08-29T22:45:00.000Z",
    expiresAt: "2026-08-29T23:00:00.000Z",
    ...overrides
  };
  return { ...value, authorizationDigest: computeInstallationAuthorizationDigest(value) };
}

function observation(event, extra = {}) {
  return {
    schemaVersion: 1,
    event,
    observationClass: "MCLENOVO_BOUNDED_LOCAL_OPERATOR",
    observationId: `OBS-${event}`,
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: "ATTEMPT-MCLENOVO-OFFLINE-013",
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    remoteShellUsed: false,
    credentialAccessPerformed: false,
    ...extra
  };
}

test("exact external authorization creates a non-executing installation plan", () => {
  const plan = createAuthorizedInstallationPlan({ preflightReceipt: preflight(), authorization: authorization(), clock: NOW });
  assert.equal(plan.status, "INSTALLATION_AUTHORIZED_PENDING_EXTERNAL_EXECUTION");
  assert.equal(plan.installState, "AUTHORIZED_NOT_STARTED");
  assert.equal(plan.externalExecutionRequired, true);
  assert.equal(plan.installationPerformed, false);
  assert.equal(plan.mysmisAccessPerformed, false);
  assert.equal(plan.liveEvidenceClaimed, false);
  assert.match(plan.planId, /^[a-f0-9]{64}$/u);
});

test("missing external authorization cannot be minted by the connector", () => {
  assert.throws(
    () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: null, clock: NOW }),
    (error) => error instanceof InstallAuthorizationError && error.code === "INSTALL_AUTH_RECORD_INVALID"
  );
});

test("authorization is bound to exact head, pair, manifest and attempt", () => {
  for (const overrides of [
    { sourceHead: "1".repeat(40) },
    { pairId: "1".repeat(64) },
    { manifestDigest: "1".repeat(64) },
    { attemptId: "ATTEMPT-OTHER" }
  ]) {
    assert.throws(
      () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: authorization(overrides), clock: NOW }),
      (error) => error.code === "INSTALL_AUTH_BINDING_MISMATCH"
    );
  }
});

test("extra operations and unknown authorization fields fail closed", () => {
  const operations = [...authorization().operations, "OPEN_MYSMIS"];
  assert.throws(
    () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: authorization({ operations }), clock: NOW }),
    (error) => error.code === "INSTALL_AUTH_SCOPE_INVALID"
  );
  const auth = authorization();
  auth.password = "never";
  assert.throws(
    () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: auth, clock: NOW }),
    (error) => error.code === "INSTALL_AUTH_RECORD_INVALID"
  );
});

test("write, credential, remote-shell and native-messaging permissions are denied", () => {
  for (const controls of [
    { mysmisWritesAllowed: 1 },
    { credentialAccessAllowed: true },
    { remoteShellAllowed: true },
    { nativeMessagingEnabled: true },
    { mysmisAccessAllowed: true }
  ]) {
    assert.throws(
      () => validateInstallationAuthorization({
        preflightReceipt: preflight(),
        authorization: authorization({ controls: { ...authorization().controls, ...controls } }),
        clock: NOW
      }),
      (error) => error.code === "INSTALL_AUTH_CONTROLS_INVALID"
    );
  }
});

test("expired, future and overlong authorization windows fail closed", () => {
  for (const times of [
    { issuedAt: "2026-08-29T22:00:00.000Z", expiresAt: "2026-08-29T22:30:00.000Z" },
    { issuedAt: "2026-08-29T22:51:00.000Z", expiresAt: "2026-08-29T23:00:00.000Z" },
    { issuedAt: "2026-08-29T22:40:00.000Z", expiresAt: "2026-08-29T23:20:01.000Z" }
  ]) {
    assert.throws(
      () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: authorization(times), clock: NOW }),
      (error) => error.code === "INSTALL_AUTH_EXPIRED_OR_INVALID_WINDOW"
    );
  }
});

test("tampering after authorization digest creation is detected", () => {
  const auth = authorization();
  auth.approvalEvidenceRef = "CHANGED-EVIDENCE";
  assert.throws(
    () => validateInstallationAuthorization({ preflightReceipt: preflight(), authorization: auth, clock: NOW }),
    (error) => error.code === "INSTALL_AUTH_DIGEST_MISMATCH"
  );
});

test("external installation observation advances only to awaiting live health", () => {
  const plan = createAuthorizedInstallationPlan({ preflightReceipt: preflight(), authorization: authorization(), clock: NOW });
  const state = transitionInstallationState({
    current: plan,
    event: observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true }),
    clock: NOW
  });
  assert.equal(state.status, "EXTERNAL_INSTALLATION_RECORDED_AWAITING_LIVE_HEALTH");
  assert.equal(state.installationPerformed, true);
  assert.equal(state.liveEvidenceClaimed, false);
  assert.equal(state.mysmisAccessPerformed, false);
});

test("recorded failure requires complete receipt-preserving rollback", () => {
  const plan = createAuthorizedInstallationPlan({ preflightReceipt: preflight(), authorization: authorization(), clock: NOW });
  const failed = transitionInstallationState({
    current: plan,
    event: observation("INSTALLATION_FAILED", { errorCode: "EXTENSION_LOAD_FAILED" }),
    clock: NOW
  });
  assert.equal(failed.rollbackState, "REQUIRED");
  assert.throws(
    () => transitionInstallationState({
      current: failed,
      event: observation("ROLLBACK_OBSERVED", {
        extensionRemoved: true,
        localAgentStopped: true,
        connectorFolderRemoved: true,
        receiptsPreserved: false
      }),
      clock: NOW
    }),
    (error) => error.code === "INSTALL_ROLLBACK_INCOMPLETE"
  );
  const rolledBack = transitionInstallationState({
    current: failed,
    event: observation("ROLLBACK_OBSERVED", {
      extensionRemoved: true,
      localAgentStopped: true,
      connectorFolderRemoved: true,
      receiptsPreserved: true
    }),
    clock: NOW
  });
  assert.equal(rolledBack.status, "INSTALLATION_ROLLED_BACK_AWAITING_NEW_AUTHORIZATION");
  assert.equal(rolledBack.rollbackState, "COMPLETE");
  assert.equal(rolledBack.liveEvidenceClaimed, false);
});

test("unknown, write-bearing and credential-bearing observations are rejected", () => {
  const plan = createAuthorizedInstallationPlan({ preflightReceipt: preflight(), authorization: authorization(), clock: NOW });
  for (const event of [
    observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true, token: "never" }),
    observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true, mysmisWrites: 1 }),
    observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true, credentialAccessPerformed: true }),
    observation("RUN_SHELL")
  ]) {
    assert.throws(
      () => transitionInstallationState({ current: plan, event, clock: NOW }),
      (error) => error.code === "INSTALL_OBSERVATION_INVALID"
    );
  }
});

test("forged and expired current plans fail before observation", () => {
  const plan = createAuthorizedInstallationPlan({ preflightReceipt: preflight(), authorization: authorization(), clock: NOW });
  assert.throws(
    () => transitionInstallationState({
      current: { ...plan, planId: "f".repeat(64) },
      event: observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true }),
      clock: NOW
    }),
    (error) => error.code === "INSTALL_STATE_INVALID"
  );
  assert.throws(
    () => transitionInstallationState({
      current: { ...plan, expiresAt: "2026-08-29T22:49:59.000Z" },
      event: observation("INSTALLATION_OBSERVED", { extensionLoaded: true, localAgentStarted: true }),
      clock: NOW
    }),
    (error) => error.code === "INSTALL_AUTHORIZATION_EXPIRED_BEFORE_OBSERVATION"
  );
});
