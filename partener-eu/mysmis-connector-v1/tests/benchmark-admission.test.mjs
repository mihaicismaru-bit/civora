import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import {
  BenchmarkAdmissionError,
  createBenchmarkAdmission,
  createBenchmarkAdmissionFailureReceipt
} from "../core/benchmark-admission.mjs";
import {
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES,
  validateBridgeHealthResponse
} from "../core/bridge-health.mjs";
import {
  computeInstallationAuthorizationDigest,
  createAuthorizedInstallationPlan,
  transitionInstallationState
} from "../native/install-authorization.mjs";

const CLI = resolve("native/benchmark-admission-cli.mjs");
const HEAD = "a2a913d1a28bfa2f9dd26de2593ae6e31de67fc2";
const PAIR = "c".repeat(64);
const MANIFEST = "d".repeat(64);

function iso(milliseconds) {
  return new Date(milliseconds).toISOString();
}

function validChain(now = Date.parse("2026-08-30T02:30:00.000Z")) {
  const preflight = {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-ADMISSION-018",
    recordedAt: iso(now - 180_000),
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    payloadFileCount: 30,
    extensionFileCount: 11,
    agentFileCount: 26,
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
    authorizationId: "AUTH-MCLENOVO-ADMISSION-018",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-ADMISSION-018",
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
    issuedAt: iso(now - 170_000),
    expiresAt: iso(now + 600_000)
  };
  const authorization = { ...core, authorizationDigest: computeInstallationAuthorizationDigest(core) };
  const plan = createAuthorizedInstallationPlan({
    preflightReceipt: preflight,
    authorization,
    clock: () => new Date(now - 160_000)
  });
  const observation = {
    schemaVersion: 1,
    event: "INSTALLATION_OBSERVED",
    observationClass: "MCLENOVO_BOUNDED_LOCAL_OPERATOR",
    observationId: "OBS-MCLENOVO-ADMISSION-018",
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
    clock: () => new Date(now - 150_000)
  });
  const challenge = createBridgeHealthChallenge({
    connectorBuildId: HEAD,
    clock: () => new Date(now - 30_000),
    nonce: "ab".repeat(32)
  });
  const response = {
    schemaVersion: 1,
    protocolVersion: 1,
    challengeId: challenge.challengeId,
    nonceEcho: challenge.nonce,
    targetLabel: challenge.targetLabel,
    connectorBuildId: HEAD,
    agentBuildId: HEAD,
    respondedAt: iso(now - 20_000),
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
    clock: () => new Date(now - 10_000)
  });
  return { schemaVersion: 1, mode: "APPEND_ONLY_ORDERED", records: [preflight, authorization, plan, observation, installed, challenge, response, health] };
}

function spec(overrides = {}) {
  return {
    schemaVersion: 1,
    mode: "TWO_TRACK_GENERIC",
    requests: [
      { track: "IMPLEMENTATION", projectSelector: "310224", nonce: "12".repeat(32) },
      { track: "WRITING", projectSelector: "367944", nonce: "34".repeat(32) }
    ],
    ...overrides
  };
}

test("fresh verified handoff admits two non-executed generic discovery commands", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  const receipt = createBenchmarkAdmission({ handoffChain: validChain(now), benchmarkSpec: spec(), clock: () => new Date(now) });
  assert.equal(receipt.status, "BENCHMARK_COMMANDS_ADMITTED_NOT_EXECUTED");
  assert.equal(receipt.commands.length, 2);
  assert.ok(receipt.commands.every((command) => command.connectorBuildId === HEAD));
  assert.ok(receipt.commands.every((command) => command.executionClass === "LIVE_BRIDGE"));
  assert.equal(receipt.invariants.executionPerformed, false);
  assert.equal(receipt.invariants.functionalAcceptance, "NOT_CLAIMED");
});

test("runtime gate contains no benchmark project identifiers", async () => {
  const source = await readFile(resolve("core/benchmark-admission.mjs"), "utf8");
  assert.doesNotMatch(source, /310224|367944/u);
});

test("invalid, incomplete or offline-only handoff evidence is rejected", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  for (const chain of [null, { ...validChain(now), records: validChain(now).records.slice(0, 7) }]) {
    assert.throws(
      () => createBenchmarkAdmission({ handoffChain: chain, benchmarkSpec: spec(), clock: () => new Date(now) }),
      (error) => error.code === "BENCHMARK_ADMISSION_HANDOFF_INVALID"
    );
  }
  const offline = validChain(now);
  offline.records[7] = validateBridgeHealthResponse({
    challenge: offline.records[5],
    response: offline.records[6],
    observedVia: "OFFLINE_FIXTURE",
    clock: () => new Date(now - 10_000)
  });
  assert.throws(
    () => createBenchmarkAdmission({ handoffChain: offline, benchmarkSpec: spec(), clock: () => new Date(now) }),
    (error) => error.code === "BENCHMARK_ADMISSION_HANDOFF_INVALID"
  );
});

test("stale live health cannot admit benchmark commands", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  assert.throws(
    () => createBenchmarkAdmission({ handoffChain: validChain(now), benchmarkSpec: spec(), clock: () => new Date(now + 180_000) }),
    (error) => error.code === "BENCHMARK_ADMISSION_LIVE_HEALTH_STALE"
  );
});

test("duplicate or missing tracks and selectors fail separation", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  for (const requests of [
    [spec().requests[0], { ...spec().requests[1], track: "IMPLEMENTATION" }],
    [spec().requests[0], { ...spec().requests[1], projectSelector: "310224" }]
  ]) {
    assert.throws(
      () => createBenchmarkAdmission({ handoffChain: validChain(now), benchmarkSpec: spec({ requests }), clock: () => new Date(now) }),
      (error) => error.code === "BENCHMARK_ADMISSION_TRACK_SEPARATION_INVALID"
    );
  }
});

test("unknown, sensitive and malformed spec fields fail closed", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  for (const benchmarkSpec of [
    { ...spec(), token: "TOP-SECRET" },
    { ...spec(), requests: [{ ...spec().requests[0], extra: true }, spec().requests[1]] },
    { ...spec(), mode: "RUN_ALL_PROJECTS" }
  ]) {
    assert.throws(
      () => createBenchmarkAdmission({ handoffChain: validChain(now), benchmarkSpec, clock: () => new Date(now) }),
      (error) => error instanceof BenchmarkAdmissionError
    );
  }
});

test("admitted commands preserve current-page GET/HEAD and zero-action restrictions", () => {
  const now = Date.parse("2026-08-30T02:30:00.000Z");
  const receipt = createBenchmarkAdmission({ handoffChain: validChain(now), benchmarkSpec: spec(), clock: () => new Date(now) });
  for (const command of receipt.commands) {
    assert.deepEqual(command.scope.allowedMethods, ["GET", "HEAD"]);
    assert.equal(command.scope.pageContext, "CURRENT_PAGE_ONLY");
    assert.equal(command.restrictions.controlsClicked, 0);
    assert.equal(command.restrictions.routeMutations, 0);
    assert.equal(command.restrictions.mysmisWrites, 0);
    assert.equal(command.restrictions.cdpAttached, false);
    assert.equal(command.restrictions.arbitraryShell, false);
  }
});

test("failure receipt is sanitized and claims no commands or execution", () => {
  const receipt = createBenchmarkAdmissionFailureReceipt({
    error: new BenchmarkAdmissionError("BENCHMARK_ADMISSION_SENSITIVE_FIELD_DENIED", "TOP-SECRET")
  });
  assert.equal(receipt.status, "BENCHMARK_ADMISSION_REJECTED_NO_EXECUTION");
  assert.equal(receipt.commandsIssued, 0);
  assert.equal(receipt.executionPerformed, false);
  assert.doesNotMatch(JSON.stringify(receipt), /TOP-SECRET|token/u);
});

test("portable CLI emits admission without modifying either input", async () => {
  const now = Date.now();
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-benchmark-admission-"));
  const chainPath = resolve(root, "chain.json");
  const specPath = resolve(root, "benchmarks.json");
  await writeFile(chainPath, JSON.stringify(validChain(now)), "utf8");
  await writeFile(specPath, JSON.stringify(spec()), "utf8");
  const before = await readdir(root);
  const result = spawnSync(process.execPath, [CLI, "--chain", chainPath, "--benchmarks", specPath], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout).status, "BENCHMARK_COMMANDS_ADMITTED_NOT_EXECUTED");
  assert.deepEqual(await readdir(root), before);
});

test("CLI input failures are sanitized and source has no execution primitives", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-benchmark-admission-invalid-"));
  const malformed = resolve(root, "malformed.json");
  await writeFile(malformed, "{TOP-SECRET", "utf8");
  for (const result of [
    spawnSync(process.execPath, [CLI, "--chain", resolve(root, "missing.json"), "--benchmarks", malformed], { encoding: "utf8" }),
    spawnSync(process.execPath, [CLI, "--shell", "cmd"], { encoding: "utf8" })
  ]) {
    assert.equal(result.status, 1);
    assert.equal(JSON.parse(result.stderr).status, "BENCHMARK_ADMISSION_REJECTED_NO_EXECUTION");
    assert.doesNotMatch(result.stderr, /TOP-SECRET|missing\.json/u);
  }
  const source = await readFile(CLI, "utf8");
  assert.doesNotMatch(source, /child_process|execFile|spawn|chrome\.|nativeMessaging|powershell|cmd\.exe/u);
  assert.doesNotMatch(source, /writeFile|appendFile|rename|unlink|mkdir/u);
  assert.doesNotMatch(source, /https?:|fetch\s*\(/u);
  assert.equal(execFileSync(process.execPath, ["--check", CLI], { encoding: "utf8" }), "");
});
