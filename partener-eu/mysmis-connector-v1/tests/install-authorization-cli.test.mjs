import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { computeInstallationAuthorizationDigest } from "../native/install-authorization.mjs";

const CLI = resolve("native/install-authorization-cli.mjs");
const HEAD = "9caa9a5c2fb8ed26a361d9edc0e16f8fcce0e0c5";
const PAIR = "d".repeat(64);
const MANIFEST = "e".repeat(64);

function preflight() {
  return {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-CLI-015",
    recordedAt: new Date().toISOString(),
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    payloadFileCount: 25,
    extensionFileCount: 11,
    agentFileCount: 21,
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
  const now = Date.now();
  const value = {
    schemaVersion: 1,
    status: "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL",
    authorizationId: "AUTH-MCLENOVO-CLI-015",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-CLI-015",
    machineAlias: "MCLENOVO",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: "ATTEMPT-MCLENOVO-CLI-015",
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
    expiresAt: new Date(now + 10 * 60_000).toISOString(),
    ...overrides
  };
  return { ...value, authorizationDigest: computeInstallationAuthorizationDigest(value) };
}

async function inputs(auth = authorization()) {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-install-auth-cli-"));
  const preflightPath = resolve(root, "preflight.json");
  const authorizationPath = resolve(root, "authorization.json");
  await writeFile(preflightPath, JSON.stringify(preflight()), "utf8");
  await writeFile(authorizationPath, JSON.stringify(auth), "utf8");
  return { root, preflightPath, authorizationPath };
}

function run(preflightPath, authorizationPath) {
  return spawnSync(process.execPath, [CLI, "--preflight", preflightPath, "--authorization", authorizationPath], {
    encoding: "utf8"
  });
}

test("portable CLI emits only a non-executing bounded plan for exact authorization", async () => {
  const value = await inputs();
  const before = await readdir(value.root);
  const result = run(value.preflightPath, value.authorizationPath);
  assert.equal(result.status, 0);
  assert.equal(result.stderr, "");
  const plan = JSON.parse(result.stdout);
  assert.equal(plan.status, "INSTALLATION_AUTHORIZED_PENDING_EXTERNAL_EXECUTION");
  assert.equal(plan.installState, "AUTHORIZED_NOT_STARTED");
  assert.equal(plan.installationPerformed, false);
  assert.equal(plan.mysmisAccessPerformed, false);
  assert.equal(plan.mysmisWrites, 0);
  assert.deepEqual(await readdir(value.root), before);
});

test("missing input fails with a sanitized no-execution receipt", async () => {
  const value = await inputs();
  const missing = resolve(value.root, "private-missing-authorization.json");
  const result = run(value.preflightPath, missing);
  assert.equal(result.status, 1);
  assert.equal(result.stdout, "");
  const receipt = JSON.parse(result.stderr);
  assert.equal(receipt.status, "INSTALL_AUTHORIZATION_REJECTED_NO_EXECUTION");
  assert.equal(receipt.errorCode, "INSTALL_AUTH_INPUT_UNAVAILABLE");
  assert.equal(receipt.installationPerformed, false);
  assert.doesNotMatch(result.stderr, /private-missing|\.json|ENOENT/u);
});

test("malformed JSON is rejected without echoing its content", async () => {
  const value = await inputs();
  const marker = "SECRET-MALFORMED-CONTENT";
  await writeFile(value.authorizationPath, `{${marker}`, "utf8");
  const result = run(value.preflightPath, value.authorizationPath);
  const receipt = JSON.parse(result.stderr);
  assert.equal(receipt.errorCode, "INSTALL_AUTH_INPUT_INVALID");
  assert.doesNotMatch(result.stderr, new RegExp(marker, "u"));
});

test("tampered authorization digest is rejected without approval content", async () => {
  const auth = authorization();
  auth.approvalEvidenceRef = "TOP-SECRET-CHANGED-EVIDENCE";
  const value = await inputs(auth);
  const result = run(value.preflightPath, value.authorizationPath);
  const receipt = JSON.parse(result.stderr);
  assert.equal(receipt.errorCode, "INSTALL_AUTH_DIGEST_MISMATCH");
  assert.doesNotMatch(result.stderr, /TOP-SECRET|approvalEvidenceRef/u);
});

test("expired authorization is rejected as no execution", async () => {
  const auth = authorization({
    issuedAt: "2026-01-01T00:00:00.000Z",
    expiresAt: "2026-01-01T00:10:00.000Z"
  });
  const value = await inputs(auth);
  const result = run(value.preflightPath, value.authorizationPath);
  const receipt = JSON.parse(result.stderr);
  assert.equal(receipt.errorCode, "INSTALL_AUTH_EXPIRED_OR_INVALID_WINDOW");
  assert.equal(receipt.liveEvidenceClaimed, false);
});

test("unknown or incomplete arguments are rejected before input reads", () => {
  for (const args of [[], ["--shell", "cmd", "--authorization", "x"], ["--preflight", "x"]]) {
    const result = spawnSync(process.execPath, [CLI, ...args], { encoding: "utf8" });
    assert.equal(result.status, 1);
    assert.equal(JSON.parse(result.stderr).errorCode, "INSTALL_AUTH_ARGUMENTS_INVALID");
  }
});

test("CLI source has no installation, browser-control or process-execution primitive", async () => {
  const source = await readFile(CLI, "utf8");
  assert.doesNotMatch(source, /child_process|execFile|spawn|chrome\.|nativeMessaging|powershell|cmd\.exe/u);
  assert.doesNotMatch(source, /writeFile|appendFile|rename|unlink|mkdir/u);
  assert.doesNotMatch(source, /https?:|fetch\s*\(/u);
  assert.equal(execFileSync(process.execPath, ["--check", CLI], { encoding: "utf8" }), "");
});
