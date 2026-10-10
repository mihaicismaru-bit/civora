import { createHash } from "node:crypto";
import { createDiscoverArtifactsCommand } from "./discover-command.mjs";
import { assertNoSensitivePersistence } from "./policy.mjs";
import { verifyHandoffChain } from "../native/handoff-chain.mjs";

const TRACKS = Object.freeze(["IMPLEMENTATION", "WRITING"]);
const SAFE_SELECTOR = /^[A-Za-z0-9._-]{1,64}$/u;
const SHA256 = /^[a-f0-9]{64}$/u;

export class BenchmarkAdmissionError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "BenchmarkAdmissionError";
    this.code = code;
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function validateSpec(spec) {
  try {
    assertNoSensitivePersistence(spec);
  } catch {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_SENSITIVE_FIELD_DENIED", "Sensitive benchmark fields are denied.");
  }
  if (!exactKeys(spec, ["schemaVersion", "mode", "requests"])
    || spec.schemaVersion !== 1
    || spec.mode !== "TWO_TRACK_GENERIC"
    || !Array.isArray(spec.requests)
    || spec.requests.length !== TRACKS.length) {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_SPEC_INVALID", "Exactly one generic request per benchmark track is required.");
  }
  const observedTracks = [];
  const selectors = new Set();
  for (const request of spec.requests) {
    if (!exactKeys(request, ["track", "projectSelector", "nonce"])
      || !TRACKS.includes(request.track)
      || !SAFE_SELECTOR.test(request.projectSelector)
      || !SHA256.test(request.nonce)) {
      throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_REQUEST_INVALID", "Benchmark request shape or opaque selector is invalid.");
    }
    observedTracks.push(request.track);
    selectors.add(request.projectSelector);
  }
  if (new Set(observedTracks).size !== TRACKS.length
    || !TRACKS.every((track) => observedTracks.includes(track))
    || selectors.size !== TRACKS.length) {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_TRACK_SEPARATION_INVALID", "Both distinct benchmark tracks and selectors are required.");
  }
  return [...spec.requests].sort((a, b) => TRACKS.indexOf(a.track) - TRACKS.indexOf(b.track));
}

function assertFreshLiveHealth(chain, now) {
  const challenge = chain.records[5];
  const health = chain.records[7];
  const expiresAt = Date.parse(challenge.expiresAt);
  const observedAt = Date.parse(health.observedAt);
  if (!Number.isFinite(expiresAt)
    || !Number.isFinite(observedAt)
    || now > expiresAt
    || now < observedAt
    || now - observedAt > 120_000) {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_LIVE_HEALTH_STALE", "Benchmark admission requires current live HEALTH evidence.");
  }
}

export function createBenchmarkAdmission({ handoffChain, benchmarkSpec, clock = () => new Date() }) {
  let handoff;
  try {
    handoff = verifyHandoffChain({ chain: handoffChain });
  } catch (error) {
    throw new BenchmarkAdmissionError(
      error?.code === "HANDOFF_CHAIN_SENSITIVE_FIELD_DENIED"
        ? "BENCHMARK_ADMISSION_SENSITIVE_FIELD_DENIED"
        : "BENCHMARK_ADMISSION_HANDOFF_INVALID",
      "A complete verified live handoff chain is required."
    );
  }
  if (handoff.status !== "HANDOFF_CHAIN_LIVE_HEALTH_VERIFIED_PENDING_BENCHMARKS"
    || handoff.liveHealthVerified !== true
    || handoff.benchmarkTraversalPerformed !== false
    || handoff.functionalAcceptance !== "NOT_CLAIMED") {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_HANDOFF_INVALID", "Handoff status is not eligible for benchmark admission.");
  }
  const requests = validateSpec(benchmarkSpec);
  const now = clock();
  assertFreshLiveHealth(handoffChain, now.getTime());
  const healthReceipt = handoffChain.records[7];
  const commands = requests.map((request) => createDiscoverArtifactsCommand({
    connectorBuildId: handoff.sourceHead,
    healthReceipt,
    executionClass: "LIVE_BRIDGE",
    projectSelector: request.projectSelector,
    track: request.track,
    clock: () => now,
    nonce: request.nonce
  }));
  const admissionId = digest({
    handoffChainId: handoff.chainId,
    sourceHead: handoff.sourceHead,
    commands: commands.map((command) => command.commandId)
  });
  const receipt = {
    schemaVersion: 1,
    status: "BENCHMARK_COMMANDS_ADMITTED_NOT_EXECUTED",
    admissionId,
    handoffChainId: handoff.chainId,
    sourceHead: handoff.sourceHead,
    healthChallengeId: healthReceipt.challengeId,
    issuedAt: now.toISOString(),
    tracks: [...TRACKS],
    commands,
    invariants: {
      sameConnectorBuild: commands.every((command) => command.connectorBuildId === handoff.sourceHead),
      projectSpecificRuntimeCode: false,
      executionPerformed: false,
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      cdpAttached: false,
      arbitraryShell: false,
      functionalAcceptance: "NOT_CLAIMED"
    }
  };
  assertNoSensitivePersistence(receipt);
  return Object.freeze(receipt);
}

export function createBenchmarkAdmissionFailureReceipt({ error, clock = () => new Date() }) {
  const errorCode = error instanceof BenchmarkAdmissionError && /^[A-Z0-9_]{1,80}$/u.test(error.code)
    ? error.code
    : "BENCHMARK_ADMISSION_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: "BENCHMARK_ADMISSION_REJECTED_NO_EXECUTION",
    errorCode,
    commandsIssued: 0,
    executionPerformed: false,
    controlsClicked: 0,
    routeMutations: 0,
    mysmisWrites: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}

export const BENCHMARK_ADMISSION_TRACKS = TRACKS;
