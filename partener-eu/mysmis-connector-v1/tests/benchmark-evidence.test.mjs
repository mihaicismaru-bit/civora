import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import test from "node:test";
import { createBenchmarkAdmission } from "../core/benchmark-admission.mjs";
import {
  BenchmarkEvidenceError,
  createBenchmarkEvidenceFailureReceipt,
  verifyBenchmarkDiscoveryEvidence
} from "../core/benchmark-evidence.mjs";
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

const CLI = resolve("native/benchmark-evidence-cli.mjs");
const HEAD = "94b53d5380a2f10698cce0d423a68aaced92a0c6";
const PAIR = "c".repeat(64);
const MANIFEST = "d".repeat(64);
const NOW = Date.parse("2026-08-30T03:30:00.000Z");

function iso(milliseconds) {
  return new Date(milliseconds).toISOString();
}

function validChain(now = NOW) {
  const preflight = {
    schemaVersion: 1,
    attemptId: "ATTEMPT-MCLENOVO-EVIDENCE-019",
    recordedAt: iso(now - 180_000),
    status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
    sourceHead: HEAD,
    pairId: PAIR,
    manifestDigest: MANIFEST,
    payloadFileCount: 32,
    extensionFileCount: 11,
    agentFileCount: 28,
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
    authorizationId: "AUTH-MCLENOVO-EVIDENCE-019",
    approvalEvidenceRef: "EXTERNAL-APPROVAL-EVIDENCE-019",
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
  const authorization = {
    ...authorizationCore,
    authorizationDigest: computeInstallationAuthorizationDigest(authorizationCore)
  };
  const plan = createAuthorizedInstallationPlan({
    preflightReceipt: preflight,
    authorization,
    clock: () => new Date(now - 160_000)
  });
  const observation = {
    schemaVersion: 1,
    event: "INSTALLATION_OBSERVED",
    observationClass: "MCLENOVO_BOUNDED_LOCAL_OPERATOR",
    observationId: "OBS-MCLENOVO-EVIDENCE-019",
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
  return {
    schemaVersion: 1,
    mode: "APPEND_ONLY_ORDERED",
    records: [preflight, authorization, plan, observation, installed, challenge, response, health]
  };
}

function spec() {
  return {
    schemaVersion: 1,
    mode: "TWO_TRACK_GENERIC",
    requests: [
      { track: "IMPLEMENTATION", projectSelector: "310224", nonce: "12".repeat(32) },
      { track: "WRITING", projectSelector: "367944", nonce: "34".repeat(32) }
    ]
  };
}

function fixture() {
  const handoffChain = validChain();
  const benchmarkSpec = spec();
  const admission = createBenchmarkAdmission({
    handoffChain,
    benchmarkSpec,
    clock: () => new Date(NOW)
  });
  const responses = admission.commands.map((command, index) => ({
    schemaVersion: 1,
    commandId: command.commandId,
    nonceEcho: command.nonce,
    connectorBuildId: command.connectorBuildId,
    healthChallengeId: command.healthChallengeId,
    capturedAt: iso(NOW + 10_000 + index * 1_000),
    observedVia: "LIVE_BRIDGE_TOOL",
    snapshot: {
      project: { code: command.projectSelector, track: command.track },
      page: { url: `https://mysmis2021.gov.ro/project/${command.projectSelector}`, title: "Current project page" },
      capture: { id: `capture-${command.track.toLowerCase()}` },
      elements: [
        {
          tag: "a",
          text: command.track === "IMPLEMENTATION" ? "Descarcă contract" : "Descarcă cererea",
          href: `https://mysmis2021.gov.ro/files/${command.track.toLowerCase()}.pdf`,
          method: "GET",
          download: true
        },
        { tag: "button", text: "Salvează", method: "POST" }
      ]
    },
    reportedCandidateCount: 2,
    methodsObserved: ["GET", "HEAD"],
    safety: {
      readOnly: true,
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      cdpAttached: false,
      arbitraryShell: false
    }
  }));
  return { handoffChain, benchmarkSpec, admission, responses };
}

test("two exact live responses verify discovery but leave all later gates pending", () => {
  const receipt = verifyBenchmarkDiscoveryEvidence(fixture());
  assert.equal(receipt.status, "BENCHMARK_DISCOVERY_LIVE_VERIFIED_PENDING_RETRIEVAL_AND_DRAFT_TRAVERSAL");
  assert.equal(receipt.tracks.length, 2);
  assert.equal(receipt.invariants.acceptedLiveResponses, 2);
  assert.equal(receipt.invariants.artifactRetrievalAccepted, false);
  assert.equal(receipt.invariants.draftTraversalAccepted, false);
  assert.equal(receipt.invariants.functionalAcceptance, "NOT_CLAIMED");
});

test("runtime verifier contains no benchmark project identifiers", async () => {
  const source = await readFile(resolve("core/benchmark-evidence.mjs"), "utf8");
  assert.doesNotMatch(source, /310224|367944/u);
});

test("non-retrievable candidates keep explicit reasons", () => {
  const receipt = verifyBenchmarkDiscoveryEvidence(fixture());
  for (const track of receipt.tracks) {
    const blocked = track.candidates.find((candidate) => !candidate.retrievable);
    assert.equal(blocked.nonRetrievableReason, "WRITE_INTENT_CONTROL");
  }
});

test("tampered admission or unadmitted command is rejected", () => {
  const tampered = fixture();
  tampered.admission = { ...tampered.admission, admissionId: "0".repeat(64) };
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(tampered), (error) => error.code === "BENCHMARK_EVIDENCE_ADMISSION_MISMATCH");
  const unadmitted = fixture();
  unadmitted.responses[0].commandId = "0".repeat(64);
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(unadmitted), (error) => error.code === "BENCHMARK_EVIDENCE_COMMAND_NOT_ADMITTED");
});

test("missing or duplicate track evidence cannot pass", () => {
  const missing = fixture();
  missing.responses = missing.responses.slice(0, 1);
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(missing), (error) => error.code === "BENCHMARK_EVIDENCE_SHAPE_INVALID");
  const duplicate = fixture();
  duplicate.responses[1] = structuredClone(duplicate.responses[0]);
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(duplicate), (error) => error.code === "BENCHMARK_EVIDENCE_DUPLICATE_COMMAND");
});

test("offline, unsafe and sensitive responses fail closed", () => {
  const offline = fixture();
  offline.responses[0].observedVia = "OFFLINE_FIXTURE";
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(offline), (error) => error.code === "BENCHMARK_EVIDENCE_LIVE_SOURCE_REQUIRED");
  const unsafe = fixture();
  unsafe.responses[0].safety.mysmisWrites = 1;
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(unsafe), (error) => error.code === "BENCHMARK_EVIDENCE_RESPONSE_INVALID");
  const sensitive = fixture();
  sensitive.responses[0].snapshot.cookie = "denied";
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(sensitive), (error) => error.code === "BENCHMARK_EVIDENCE_SENSITIVE_FIELD_DENIED");
});

test("incomplete inventory and extra response fields are rejected", () => {
  const incomplete = fixture();
  incomplete.responses[0].reportedCandidateCount = 1;
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(incomplete), (error) => error.code === "BENCHMARK_EVIDENCE_RESPONSE_INVALID");
  const extra = fixture();
  extra.responses[0].unexpected = true;
  assert.throws(() => verifyBenchmarkDiscoveryEvidence(extra), (error) => error.code === "BENCHMARK_EVIDENCE_RESPONSE_SHAPE_INVALID");
});

test("failure receipt is sanitized and claims no accepted live evidence", () => {
  const receipt = createBenchmarkEvidenceFailureReceipt({
    error: new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_SENSITIVE_FIELD_DENIED", "TOP-SECRET")
  });
  assert.equal(receipt.status, "BENCHMARK_EVIDENCE_REJECTED_NO_ACCEPTANCE");
  assert.equal(receipt.acceptedLiveResponses, 0);
  assert.equal(receipt.functionalAcceptance, "NOT_CLAIMED");
  assert.doesNotMatch(JSON.stringify(receipt), /TOP-SECRET|token/u);
});

test("portable CLI verifies the chain without modifying inputs", async () => {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-benchmark-evidence-"));
  const input = fixture();
  const paths = Object.fromEntries(await Promise.all(Object.entries({
    chain: input.handoffChain,
    benchmarks: input.benchmarkSpec,
    admission: input.admission,
    responses: input.responses
  }).map(async ([key, value]) => {
    const path = resolve(root, `${key}.json`);
    await writeFile(path, JSON.stringify(value), "utf8");
    return [key, path];
  })));
  const before = await readdir(root);
  const result = spawnSync(process.execPath, [
    CLI,
    "--chain", paths.chain,
    "--benchmarks", paths.benchmarks,
    "--admission", paths.admission,
    "--responses", paths.responses
  ], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.equal(JSON.parse(result.stdout).invariants.functionalAcceptance, "NOT_CLAIMED");
  assert.deepEqual(await readdir(root), before);
});

test("CLI rejects unavailable inputs and has no execution or write primitive", async () => {
  const result = spawnSync(process.execPath, [CLI, "--shell", "cmd"], { encoding: "utf8" });
  assert.equal(result.status, 1);
  assert.equal(JSON.parse(result.stderr).status, "BENCHMARK_EVIDENCE_REJECTED_NO_ACCEPTANCE");
  const source = await readFile(CLI, "utf8");
  assert.doesNotMatch(source, /child_process|execFile|spawn|chrome\.|nativeMessaging|powershell|cmd\.exe/u);
  assert.doesNotMatch(source, /writeFile|appendFile|rename|unlink|mkdir/u);
  assert.doesNotMatch(source, /https?:|fetch\s*\(/u);
});
