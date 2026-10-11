import { createHash } from "node:crypto";
import { createBenchmarkAdmission } from "./benchmark-admission.mjs";
import { validateDiscoverArtifactsResponse } from "./discover-command.mjs";
import { assertNoSensitivePersistence } from "./policy.mjs";

const TRACKS = Object.freeze(["IMPLEMENTATION", "WRITING"]);
const RESPONSE_KEYS = Object.freeze([
  "capturedAt", "commandId", "connectorBuildId", "healthChallengeId", "methodsObserved",
  "nonceEcho", "observedVia", "reportedCandidateCount", "safety", "schemaVersion", "snapshot"
]);

export class BenchmarkEvidenceError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "BenchmarkEvidenceError";
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

function same(left, right) {
  return JSON.stringify(canonicalize(left)) === JSON.stringify(canonicalize(right));
}

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function assertInputs(admission, responses) {
  try {
    assertNoSensitivePersistence(admission);
    assertNoSensitivePersistence(responses);
  } catch {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_SENSITIVE_FIELD_DENIED", "Sensitive benchmark evidence is denied.");
  }
  if (!admission || admission.status !== "BENCHMARK_COMMANDS_ADMITTED_NOT_EXECUTED"
    || !Array.isArray(admission.commands) || admission.commands.length !== TRACKS.length
    || !Array.isArray(responses) || responses.length !== TRACKS.length) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_SHAPE_INVALID", "Exactly two admitted commands and two live responses are required.");
  }
  if (responses.some((response) => !exactKeys(response, RESPONSE_KEYS))) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_RESPONSE_SHAPE_INVALID", "Live response fields must match the bounded discovery contract.");
  }
  if (responses.some((response) => response.observedVia !== "LIVE_BRIDGE_TOOL")) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_LIVE_SOURCE_REQUIRED", "Offline or unspecified observations cannot satisfy live evidence.");
  }
}

export function verifyBenchmarkDiscoveryEvidence({ handoffChain, benchmarkSpec, admission, responses }) {
  assertInputs(admission, responses);
  let expectedAdmission;
  try {
    expectedAdmission = createBenchmarkAdmission({
      handoffChain,
      benchmarkSpec,
      clock: () => new Date(admission.issuedAt)
    });
  } catch {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_ADMISSION_INVALID", "The exact live handoff and admission could not be recomputed.");
  }
  if (!same(expectedAdmission, admission)) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_ADMISSION_MISMATCH", "Admission is not the exact recomputed two-track receipt.");
  }

  const commandById = new Map(admission.commands.map((command) => [command.commandId, command]));
  if (commandById.size !== TRACKS.length || new Set(responses.map((response) => response.commandId)).size !== TRACKS.length) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_DUPLICATE_COMMAND", "Every admitted command requires one distinct response.");
  }

  const results = responses.map((response) => {
    const command = commandById.get(response.commandId);
    if (!command) {
      throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_COMMAND_NOT_ADMITTED", "Response does not belong to this admission.");
    }
    try {
      return validateDiscoverArtifactsResponse({
        command,
        response,
        observedVia: response.observedVia,
        clock: () => new Date(response.capturedAt)
      });
    } catch (error) {
      throw new BenchmarkEvidenceError(
        error?.code === "SENSITIVE_PERSISTENCE_DENIED"
          ? "BENCHMARK_EVIDENCE_SENSITIVE_FIELD_DENIED"
          : "BENCHMARK_EVIDENCE_RESPONSE_INVALID",
        "A discovery response failed exact live validation."
      );
    }
  }).sort((left, right) => TRACKS.indexOf(left.project.track) - TRACKS.indexOf(right.project.track));

  if (!TRACKS.every((track) => results.some((result) => result.project.track === track))
    || results.some((result) => result.liveVerified !== true
      || result.status !== "DISCOVERY_LIVE_VERIFIED"
      || result.connectorBuildId !== admission.sourceHead
      || result.healthChallengeId !== admission.healthChallengeId)) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_TRACK_OR_BUILD_MISMATCH", "Both tracks must use the same admitted live build and health challenge.");
  }

  const receipt = {
    schemaVersion: 1,
    status: "BENCHMARK_DISCOVERY_LIVE_VERIFIED_PENDING_RETRIEVAL_AND_DRAFT_TRAVERSAL",
    evidenceId: digest({ admissionId: admission.admissionId, results }),
    admissionId: admission.admissionId,
    handoffChainId: admission.handoffChainId,
    sourceHead: admission.sourceHead,
    healthChallengeId: admission.healthChallengeId,
    tracks: results.map((result) => ({
      track: result.project.track,
      projectSelector: result.project.code,
      commandId: result.commandId,
      capturedAt: result.capturedAt,
      candidateCounts: result.counts,
      candidates: result.candidates
    })),
    pendingGates: [
      "IMPLEMENTATION_REPRESENTATIVE_ARTIFACT_RETRIEVAL_AND_DRIVE_PROVENANCE",
      "WRITING_DRAFT_READ_ONLY_TRAVERSAL_SCHEMA_AND_VALUE_CAPTURE",
      "WRITING_APPLICATION_EXPORT_RETRIEVAL_WHEN_EXPOSED",
      "LIVE_RESTART_RESUME_AND_DEDUP_VERSIONING",
      "SECOND_PROJECT_GENERALIZATION_PER_TRACK"
    ],
    invariants: {
      sameConnectorBuild: true,
      projectSpecificRuntimeCode: false,
      acceptedLiveResponses: TRACKS.length,
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      cdpAttached: false,
      arbitraryShell: false,
      artifactRetrievalAccepted: false,
      draftTraversalAccepted: false,
      functionalAcceptance: "NOT_CLAIMED"
    }
  };
  assertNoSensitivePersistence(receipt);
  return Object.freeze(receipt);
}

export function createBenchmarkEvidenceFailureReceipt({ error, clock = () => new Date() }) {
  const errorCode = error instanceof BenchmarkEvidenceError && /^[A-Z0-9_]{1,80}$/u.test(error.code)
    ? error.code
    : "BENCHMARK_EVIDENCE_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: "BENCHMARK_EVIDENCE_REJECTED_NO_ACCEPTANCE",
    errorCode,
    acceptedLiveResponses: 0,
    artifactRetrievalAccepted: false,
    draftTraversalAccepted: false,
    mysmisWritesAccepted: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}

export const BENCHMARK_EVIDENCE_TRACKS = TRACKS;
