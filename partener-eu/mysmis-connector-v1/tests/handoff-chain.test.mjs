import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import {
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES,
  validateBridgeHealthResponse
} from "../core/bridge-health.mjs";
import {
  createHandoffChainFailureReceipt,
  HandoffChainError,
  verifyHandoffChain
} from "../native/handoff-chain.mjs";
import {
  computeInstallationAuthorizationDigest,
  createAuthorizedInstallationPlan,
  transitionInstallationState
} from "../native/install-authorization.mjs";

const CLI = resolve("native/handoff-chain-cli.mjs");
const HEAD = "80e7f9fbb86a25e3430b98f5e77c45b2e4503e50";
const PAIR = "a".repeat(64);
const MANIFEST = "b".repeat(64);

function validChain() {
  const preflight = {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-CHAIN-017",
    recordedAt: "2026-08-30T01:00:00.000Z",
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    payloadFileCount: 28,
    extensionFileCount: 11,
    agentFileCount: 24,
    installState: "NOT_STARTED",
    rollbackState: "NOT_REQUIRED",
    browserInstallationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  };
  const authorizationCore = {
    schemaVersion: 1,
    status: "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL",
    authorizationId: "AUTH-MCLENOVO-CHAIN-017",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-CHAIN-017",
    machineAlias: "MCLENOVO",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: preflight.attemptId,
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
    issuedAt: "2026-08-30T01:01:00.000Z",
    expiresAt: "2026-08-30T01:20:00.000Z"
  };
  const authorization = {
    ...authorizationCore,
    authorizationDigest: computeInstallationAuthorizationDigest(authorizationCore)
  };
  const plan = createAuthorizedInstallationPlan({
    preflightReceipt: preflight,
    authorization,
    clock: () => new Date("2026-08-30T01:02:00.000Z")
  });
  const observation = {
    schemaVersion: 1,
    event: "INSTALLATION_OBSERVED",
    observationClass: "MCLENOVO_BOUNDED_LOCAL_OPERATOR",
    observationId: "OBS-MCLENOVO-CHAIN-017",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    attemptId: preflight.attemptId,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    remoteShellUsed: false,
    credentialAccessPerformed: false,
    extensionLoaded: true,
    localAgentStarted: true
  };
  const installed = transitionInstallationState({
    current: plan,
    event: observation,
    clock: () => new Date("2026-08-30T01:03:00.000Z")
  });
  const challenge = createBridgeHealthChallenge({
    connectorBuildId: HEAD,
    clock: () => new Date("2026-08-30T01:04:00.000Z"),
    nonce: "cd".repeat(32)
  });
  const response = {
    schemaVersion: 1,
    protocolVersion: 1,
    challengeId: challenge.challengeId,
    nonceEcho: challenge.nonce,
    targetLabel: challenge.targetLabel,
    connectorBuildId: HEAD,
    agentBuildId: HEAD,
    respondedAt: "2026-08-30T01:04:30.000Z",
    capabilities: READ_ONLY_BRIDGE_CAPABILITIES.map((name) => ({
      name,
      mode: name === "OBSERVE_DOWNLOADS" ? "OBSERVE" : "READ_ONLY"
    })),
    runtime: {
      browserFamily: "EDGE",
      manifestVersion: 3,
      extensionReady: true,
      nativeAgentReady: true,
      authenticatedSessionPresent: true,
      mysmisOriginPresent: true
    },
    safety: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false
    }
  };
  const health = validateBridgeHealthResponse({
    challenge,
    response,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: () => new Date("2026-08-30T01:04:40.000Z")
  });
  return {
    schemaVersion: 1,
    mode: "APPEND_ONLY_ORDERED",
    records: [preflight, authorization, plan, observation, installed, challenge, response, health]
  };
}

test("recomputes the complete exact-build live handoff chain without accepting benchmarks", () => {
  const receipt = verifyHandoffChain({ chain: validChain() });
  assert.equal(receipt.status, "HANDOFF_CHAIN_LIVE_HEALTH_VERIFIED_PENDING_BENCHMARKS");
  assert.equal(receipt.liveHealthVerified, true);
  assert.equal(receipt.benchmarkTraversalPerformed, false);
  assert.equal(receipt.functionalAcceptance, "NOT_CLAIMED");
  assert.equal(receipt.mysmisWrites, 0);
  assert.match(receipt.chainId, /^[a-f0-9]{64}$/u);
});

test("missing or reordered records fail closed", () => {
  const missing = validChain();
  missing.records.pop();
  assert.throws(() => verifyHandoffChain({ chain: missing }), (error) => error.code === "HANDOFF_CHAIN_SHAPE_INVALID");
  const reordered = validChain();
  [reordered.records[5], reordered.records[6]] = [reordered.records[6], reordered.records[5]];
  assert.throws(() => verifyHandoffChain({ chain: reordered }), (error) => error.code === "HANDOFF_CHAIN_ORDER_INVALID");
});

test("mixed component builds are rejected", () => {
  const chain = validChain();
  chain.records[6] = { ...chain.records[6], agentBuildId: "1".repeat(40) };
  assert.throws(() => verifyHandoffChain({ chain }), (error) => error.code === "HANDOFF_CHAIN_BUILD_MISMATCH");
});

test("offline-only health cannot be promoted into the live chain", () => {
  const chain = validChain();
  chain.records[7] = validateBridgeHealthResponse({
    challenge: chain.records[5],
    response: chain.records[6],
    observedVia: "OFFLINE_FIXTURE",
    clock: () => new Date("2026-08-30T01:04:40.000Z")
  });
  assert.throws(() => verifyHandoffChain({ chain }), (error) => error.code === "HANDOFF_CHAIN_ORDER_INVALID");
});

test("tampered derived states and non-monotonic records fail closed", () => {
  const forged = validChain();
  forged.records[2] = { ...forged.records[2], planId: "f".repeat(64) };
  assert.throws(() => verifyHandoffChain({ chain: forged }), (error) => error.code === "HANDOFF_CHAIN_PLAN_MISMATCH");
  const stale = validChain();
  stale.records[6] = { ...stale.records[6], respondedAt: "2026-08-30T01:03:30.000Z" };
  assert.throws(() => verifyHandoffChain({ chain: stale }), (error) => /BRIDGE_|HANDOFF_CHAIN_/u.test(error.code));
});

test("sensitive fields are denied and sanitized failure receipts never echo content", () => {
  const chain = validChain();
  chain.records[3] = { ...chain.records[3], token: "TOP-SECRET" };
  assert.throws(() => verifyHandoffChain({ chain }), (error) => error.code === "HANDOFF_CHAIN_SENSITIVE_FIELD_DENIED");
  const receipt = createHandoffChainFailureReceipt({
    error: new HandoffChainError("HANDOFF_CHAIN_SENSITIVE_FIELD_DENIED", "TOP-SECRET")
  });
  assert.equal(receipt.status, "HANDOFF_CHAIN_REJECTED_NO_EXECUTION");
  assert.doesNotMatch(JSON.stringify(receipt), /TOP-SECRET|token/u);
});

test("portable CLI verifies inputs without modifying their directory", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-handoff-chain-cli-"));
  const path = resolve(root, "chain.json");
  await writeFile(path, JSON.stringify(validChain()), "utf8");
  const before = await readdir(root);
  const result = spawnSync(process.execPath, [CLI, "--chain", path], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout).status, "HANDOFF_CHAIN_LIVE_HEALTH_VERIFIED_PENDING_BENCHMARKS");
  assert.deepEqual(await readdir(root), before);
});

test("CLI missing, malformed and unsafe arguments emit sanitized no-execution receipts", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-handoff-chain-cli-invalid-"));
  const malformed = resolve(root, "private-malformed.json");
  await writeFile(malformed, "{TOP-SECRET", "utf8");
  for (const result of [
    spawnSync(process.execPath, [CLI, "--chain", resolve(root, "missing-private.json")], { encoding: "utf8" }),
    spawnSync(process.execPath, [CLI, "--chain", malformed], { encoding: "utf8" }),
    spawnSync(process.execPath, [CLI, "--shell", "cmd"], { encoding: "utf8" })
  ]) {
    assert.equal(result.status, 1);
    assert.equal(JSON.parse(result.stderr).status, "HANDOFF_CHAIN_REJECTED_NO_EXECUTION");
    assert.doesNotMatch(result.stderr, /TOP-SECRET|private-malformed|missing-private/u);
  }
});

test("handoff CLI has no installation, browser, process, network or write primitive", async () => {
  const source = await readFile(CLI, "utf8");
  assert.doesNotMatch(source, /child_process|execFile|spawn|chrome\.|nativeMessaging|powershell|cmd\.exe/u);
  assert.doesNotMatch(source, /writeFile|appendFile|rename|unlink|mkdir/u);
  assert.doesNotMatch(source, /https?:|fetch\s*\(/u);
  assert.equal(execFileSync(process.execPath, ["--check", CLI], { encoding: "utf8" }), "");
});
