import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import {
  computeInstallationAuthorizationDigest,
  createAuthorizedInstallationPlan,
  transitionInstallationState
} from "../native/install-authorization.mjs";

const CLI = resolve("native/install-observation-cli.mjs");
const HEAD = "0697ea2a99b374f55fb39ab77e5118afe449c078";
const PAIR = "a".repeat(64);
const MANIFEST = "b".repeat(64);

function currentPlan() {
  const now = Date.now();
  const preflightReceipt = {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-OBS-016",
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    installState: "NOT_STARTED",
    rollbackState: "NOT_REQUIRED",
    browserInstallationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  };
  const core = {
    schemaVersion: 1,
    status: "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL",
    authorizationId: "AUTH-MCLENOVO-OBS-016",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-OBS-016",
    machineAlias: "MCLENOVO",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: preflightReceipt.attemptId,
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
    issuedAt: new Date(now - 60_000).toISOString(),
    expiresAt: new Date(now + 10 * 60_000).toISOString()
  };
  const authorization = { ...core, authorizationDigest: computeInstallationAuthorizationDigest(core) };
  return createAuthorizedInstallationPlan({ preflightReceipt, authorization });
}

function observation(event, extra = {}) {
  return {
    schemaVersion: 1,
    event,
    observationClass: "MCLENOVO_BOUNDED_LOCAL_OPERATOR",
    observationId: `OBS-${event}-016`,
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: "ATTEMPT-MCLENOVO-OBS-016",
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    remoteShellUsed: false,
    credentialAccessPerformed: false,
    ...extra
  };
}

async function inputs(current, event) {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-install-observation-cli-"));
  const currentPath = resolve(root, "current.json");
  const observationPath = resolve(root, "observation.json");
  await writeFile(currentPath, JSON.stringify(current), "utf8");
  await writeFile(observationPath, JSON.stringify(event), "utf8");
  return { root, currentPath, observationPath };
}

function run(currentPath, observationPath) {
  return spawnSync(process.execPath, [CLI, "--current", currentPath, "--observation", observationPath], { encoding: "utf8" });
}

test("bounded external success observation advances only to awaiting live health", async () => {
  const value = await inputs(currentPlan(), observation("INSTALLATION_OBSERVED", {
    extensionLoaded: true,
    localAgentStarted: true
  }));
  const before = await readdir(value.root);
  const result = run(value.currentPath, value.observationPath);
  assert.equal(result.status, 0);
  const next = JSON.parse(result.stdout);
  assert.equal(next.status, "EXTERNAL_INSTALLATION_RECORDED_AWAITING_LIVE_HEALTH");
  assert.equal(next.liveEvidenceClaimed, false);
  assert.equal(next.mysmisAccessPerformed, false);
  assert.deepEqual(await readdir(value.root), before);
});

test("bounded failure observation advances only to rollback required", async () => {
  const value = await inputs(currentPlan(), observation("INSTALLATION_FAILED", { errorCode: "EXTENSION_LOAD_FAILED" }));
  const result = run(value.currentPath, value.observationPath);
  assert.equal(result.status, 0);
  const next = JSON.parse(result.stdout);
  assert.equal(next.status, "INSTALLATION_FAILED_ROLLBACK_REQUIRED");
  assert.equal(next.rollbackState, "REQUIRED");
  assert.equal(next.installationPerformed, false);
});

test("complete external rollback observation preserves receipts and closes failure", async () => {
  const failed = transitionInstallationState({
    current: currentPlan(),
    event: observation("INSTALLATION_FAILED", { errorCode: "AGENT_START_FAILED" })
  });
  const value = await inputs(failed, observation("ROLLBACK_OBSERVED", {
    extensionRemoved: true,
    localAgentStopped: true,
    connectorFolderRemoved: true,
    receiptsPreserved: true
  }));
  const result = run(value.currentPath, value.observationPath);
  assert.equal(result.status, 0);
  const next = JSON.parse(result.stdout);
  assert.equal(next.status, "INSTALLATION_ROLLED_BACK_AWAITING_NEW_AUTHORIZATION");
  assert.equal(next.rollbackState, "COMPLETE");
  assert.equal(next.liveEvidenceClaimed, false);
});

test("forged and expired plans produce sanitized no-execution receipts", async () => {
  for (const current of [
    { ...currentPlan(), planId: "f".repeat(64) },
    { ...currentPlan(), expiresAt: "2026-01-01T00:00:00.000Z" }
  ]) {
    const value = await inputs(current, observation("INSTALLATION_OBSERVED", {
      extensionLoaded: true,
      localAgentStarted: true
    }));
    const result = run(value.currentPath, value.observationPath);
    assert.equal(result.status, 1);
    const receipt = JSON.parse(result.stderr);
    assert.equal(receipt.status, "INSTALL_OBSERVATION_REJECTED_NO_EXECUTION");
    assert.equal(receipt.installationPerformed, false);
    assert.equal(receipt.liveEvidenceClaimed, false);
  }
});

test("write, credential and unknown observation content is rejected without echo", async () => {
  const event = observation("INSTALLATION_OBSERVED", {
    extensionLoaded: true,
    localAgentStarted: true,
    token: "TOP-SECRET-TOKEN"
  });
  const value = await inputs(currentPlan(), event);
  const result = run(value.currentPath, value.observationPath);
  const receipt = JSON.parse(result.stderr);
  assert.equal(receipt.errorCode, "INSTALL_OBSERVATION_INVALID");
  assert.doesNotMatch(result.stderr, /TOP-SECRET|token/u);
});

test("missing, malformed and invalid arguments fail before transition", async () => {
  const value = await inputs(currentPlan(), observation("INSTALLATION_FAILED", { errorCode: "FAILED" }));
  const missing = run(value.currentPath, resolve(value.root, "missing-private.json"));
  assert.equal(JSON.parse(missing.stderr).errorCode, "INSTALL_OBSERVATION_INPUT_UNAVAILABLE");
  await writeFile(value.observationPath, "{PRIVATE-MALFORMED", "utf8");
  const malformed = run(value.currentPath, value.observationPath);
  assert.equal(JSON.parse(malformed.stderr).errorCode, "INSTALL_OBSERVATION_INPUT_INVALID");
  const invalid = spawnSync(process.execPath, [CLI, "--shell", "cmd"], { encoding: "utf8" });
  assert.equal(JSON.parse(invalid.stderr).errorCode, "INSTALL_OBSERVATION_ARGUMENTS_INVALID");
});

test("observation CLI has no installation, browser, process, network or write primitive", async () => {
  const source = await readFile(CLI, "utf8");
  assert.doesNotMatch(source, /child_process|execFile|spawn|chrome\.|nativeMessaging|powershell|cmd\.exe/u);
  assert.doesNotMatch(source, /writeFile|appendFile|rename|unlink|mkdir/u);
  assert.doesNotMatch(source, /https?:|fetch\s*\(/u);
  assert.equal(execFileSync(process.execPath, ["--check", CLI], { encoding: "utf8" }), "");
});
