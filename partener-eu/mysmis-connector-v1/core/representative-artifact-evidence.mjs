import { createHash } from "node:crypto";
import { assertNoSensitivePersistence } from "./policy.mjs";

const SHA256 = /^[a-f0-9]{64}$/u;
const GIT_SHA = /^[a-f0-9]{40}$/u;
const OBSERVATION_KEYS = Object.freeze([
  "candidateId", "capturedAt", "commandId", "connectorBuildId", "healthChallengeId",
  "observedVia", "originalFilename", "projectSelector", "safety", "schemaVersion",
  "sha256", "size", "sourceChannel", "status", "track"
]);
const OBSERVATION_SAFETY_KEYS = Object.freeze([
  "arbitraryShell", "cdpAttached", "controlsClicked", "mysmisWrites", "readOnly", "routeMutations"
]);

export class RepresentativeArtifactEvidenceError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "RepresentativeArtifactEvidenceError";
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

function fail(code, message) {
  throw new RepresentativeArtifactEvidenceError(code, message);
}

function safeInputs(values) {
  try {
    values.forEach((value) => assertNoSensitivePersistence(value));
  } catch {
    fail("REPRESENTATIVE_ARTIFACT_SENSITIVE_FIELD_DENIED", "Sensitive artifact evidence is denied.");
  }
}

function validDate(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function assertDiscovery(benchmarkEvidence, observation) {
  if (!benchmarkEvidence
    || benchmarkEvidence.status !== "BENCHMARK_DISCOVERY_LIVE_VERIFIED_PENDING_RETRIEVAL_AND_DRAFT_TRAVERSAL"
    || !SHA256.test(benchmarkEvidence.evidenceId || "")
    || !GIT_SHA.test(benchmarkEvidence.sourceHead || "")
    || typeof benchmarkEvidence.healthChallengeId !== "string"
    || !Array.isArray(benchmarkEvidence.tracks)
    || benchmarkEvidence.tracks.length !== 2
    || benchmarkEvidence.invariants?.sameConnectorBuild !== true
    || benchmarkEvidence.invariants?.acceptedLiveResponses !== 2
    || benchmarkEvidence.invariants?.mysmisWrites !== 0
    || benchmarkEvidence.invariants?.functionalAcceptance !== "NOT_CLAIMED") {
    fail("REPRESENTATIVE_ARTIFACT_DISCOVERY_EVIDENCE_INVALID", "Verified two-track live discovery evidence is required.");
  }
  if (!exactKeys(observation, OBSERVATION_KEYS) || !exactKeys(observation.safety, OBSERVATION_SAFETY_KEYS)) {
    fail("REPRESENTATIVE_ARTIFACT_OBSERVATION_SHAPE_INVALID", "Retrieval observation must match the bounded contract.");
  }
  if (observation.schemaVersion !== 1
    || observation.status !== "ARTIFACT_RETRIEVAL_OBSERVED"
    || observation.observedVia !== "LIVE_BRIDGE_TOOL"
    || observation.track !== "IMPLEMENTATION"
    || observation.connectorBuildId !== benchmarkEvidence.sourceHead
    || observation.healthChallengeId !== benchmarkEvidence.healthChallengeId
    || !SHA256.test(observation.sha256 || "")
    || !Number.isSafeInteger(observation.size) || observation.size < 1
    || !validDate(observation.capturedAt)
    || typeof observation.originalFilename !== "string" || !observation.originalFilename
    || typeof observation.sourceChannel !== "string" || !observation.sourceChannel) {
    fail("REPRESENTATIVE_ARTIFACT_OBSERVATION_INVALID", "Retrieval observation is not exact live IMPLEMENTATION evidence.");
  }
  const safety = observation.safety;
  if (safety.readOnly !== true || safety.controlsClicked !== 0 || safety.routeMutations !== 0
    || safety.mysmisWrites !== 0 || safety.cdpAttached !== false || safety.arbitraryShell !== false) {
    fail("REPRESENTATIVE_ARTIFACT_ZERO_WRITE_REQUIRED", "Retrieval evidence must prove read-only zero-write operation.");
  }
  const implementation = benchmarkEvidence.tracks.find((track) => track.track === "IMPLEMENTATION");
  const writing = benchmarkEvidence.tracks.find((track) => track.track === "WRITING");
  if (!implementation || !writing || implementation.projectSelector !== observation.projectSelector
    || implementation.commandId !== observation.commandId || !validDate(implementation.capturedAt)
    || Date.parse(observation.capturedAt) < Date.parse(implementation.capturedAt)) {
    fail("REPRESENTATIVE_ARTIFACT_TRACK_BINDING_INVALID", "Retrieval must bind to the admitted IMPLEMENTATION discovery result.");
  }
  const candidates = Array.isArray(implementation.candidates) ? implementation.candidates : [];
  const candidate = candidates.find((item) => item.candidateId === observation.candidateId);
  if (!candidate || candidate.retrievable !== true || candidate.nonRetrievableReason !== null
    || candidate.strategy !== "DIRECT_URL_SAFE_GET" || !["GET", "HEAD"].includes(candidate.method)
    || candidate.automatedActionAllowed !== false) {
    fail("REPRESENTATIVE_ARTIFACT_CANDIDATE_INVALID", "Representative bytes must bind to a safe retrievable GET/HEAD candidate.");
  }
  return candidate;
}

function assertIntake(intake, observation) {
  if (!intake || intake.status !== "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING"
    || intake.track !== "IMPLEMENTATION" || intake.projectCode !== observation.projectSelector
    || intake.originalFilename !== observation.originalFilename || intake.sourceChannel !== observation.sourceChannel
    || intake.sha256 !== observation.sha256 || intake.size !== observation.size
    || !SHA256.test(intake.eventId || "") || !SHA256.test(intake.recordKey || "")
    || !Number.isSafeInteger(intake.version) || intake.version < 1
    || intake.drive?.state !== "PENDING_ADAPTER" || intake.drive?.fileId !== null
    || intake.mysmis?.writes !== 0 || intake.mysmis?.controlsClicked !== 0
    || !validDate(intake.committedAt) || Date.parse(intake.committedAt) < Date.parse(observation.capturedAt)) {
    fail("REPRESENTATIVE_ARTIFACT_INTAKE_MISMATCH", "Local intake receipt does not match the observed representative bytes.");
  }
}

function expectedSyncId(intake) {
  return digest({ eventId: intake.eventId, sha256: intake.sha256, target: intake.track });
}

function assertDrive(sync, proposal, intake) {
  const syncId = expectedSyncId(intake);
  if (!sync || sync.status !== "DRIVE_PERSISTED_RECONCILIATION_PENDING" || sync.syncId !== syncId
    || sync.sourceEventId !== intake.eventId || sync.track !== intake.track || sync.projectCode !== intake.projectCode
    || sync.recordKey !== intake.recordKey || sync.artifactKind !== intake.artifactKind
    || sync.logicalName !== intake.logicalName || sync.version !== intake.version
    || sync.sha256 !== intake.sha256 || sync.size !== intake.size
    || sync.drive?.state !== "READBACK_VERIFIED" || typeof sync.drive?.fileId !== "string" || !sync.drive.fileId
    || sync.drive.readbackSha256 !== intake.sha256 || sync.drive.readbackSize !== intake.size
    || sync.reconciliation?.state !== "PENDING_HUMAN_REVIEW"
    || sync.reconciliation?.promoteProjectFacts !== false || sync.reconciliation?.mutationsApplied !== 0
    || sync.mysmis?.writes !== 0 || sync.mysmis?.controlsClicked !== 0 || sync.replay !== false
    || !validDate(sync.completedAt) || Date.parse(sync.completedAt) < Date.parse(intake.committedAt)) {
    fail("REPRESENTATIVE_ARTIFACT_DRIVE_RECEIPT_MISMATCH", "Drive receipt is not an exact verified readback of the local intake.");
  }
  if (!proposal || proposal.proposalId !== `drive-${syncId}` || proposal.operation !== "APPEND_ONLY_PROPOSAL"
    || proposal.approvalState !== "PENDING_HUMAN_REVIEW" || proposal.evidenceState !== "DRIVE_READBACK_VERIFIED"
    || proposal.track !== intake.track || proposal.projectCode !== intake.projectCode
    || proposal.promoteProjectFacts !== false
    || proposal.artifactRegistryAppend?.target !== "IMPLEMENTATION_ARTIFACT_REGISTRY"
    || proposal.artifactRegistryAppend?.mode !== "APPEND_ONLY"
    || proposal.ssotReconciliation?.target !== "IMPLEMENTATION_SSOT"
    || proposal.ssotReconciliation?.action !== "PROPOSE_ARTIFACT_LINK_ONLY"
    || proposal.ssotReconciliation?.factPromotion !== false
    || proposal.safety?.mysmisWrites !== 0 || proposal.safety?.controlsClicked !== 0
    || proposal.safety?.registryMutations !== 0 || proposal.safety?.ssotMutations !== 0) {
    fail("REPRESENTATIVE_ARTIFACT_PROPOSAL_INVALID", "Only the untouched append-only IMPLEMENTATION proposal is admissible.");
  }
  const artifact = proposal.artifactRegistryAppend.artifact;
  const ssot = proposal.ssotReconciliation;
  if (!artifact || artifact.recordKey !== intake.recordKey || artifact.artifactKind !== intake.artifactKind
    || artifact.logicalName !== intake.logicalName || artifact.originalFilename !== intake.originalFilename
    || artifact.version !== intake.version || artifact.classification !== intake.classification
    || artifact.sha256 !== intake.sha256 || artifact.size !== intake.size
    || artifact.detectedMime !== intake.detectedMime || artifact.driveFileId !== sync.drive.fileId
    || artifact.driveUrl !== sync.drive.url || artifact.driveReadbackSha256 !== intake.sha256
    || ssot.artifactRecordKey !== intake.recordKey || ssot.driveFileId !== sync.drive.fileId
    || ssot.sha256 !== intake.sha256) {
    fail("REPRESENTATIVE_ARTIFACT_PROPOSAL_BINDING_MISMATCH", "Proposal bindings do not match the verified bytes and Drive object.");
  }
}

export function verifyRepresentativeArtifactEvidence({ benchmarkEvidence, retrievalObservation, intakeReceipt, driveReceipt, proposal, readbackBytes }) {
  safeInputs([benchmarkEvidence, retrievalObservation, intakeReceipt, driveReceipt, proposal]);
  const candidate = assertDiscovery(benchmarkEvidence, retrievalObservation);
  assertIntake(intakeReceipt, retrievalObservation);
  assertDrive(driveReceipt, proposal, intakeReceipt);
  const raw = Buffer.isBuffer(readbackBytes) ? readbackBytes : Buffer.from(readbackBytes || []);
  const rawSha256 = createHash("sha256").update(raw).digest("hex");
  if (raw.length !== intakeReceipt.size || rawSha256 !== intakeReceipt.sha256) {
    fail("REPRESENTATIVE_ARTIFACT_RAW_READBACK_MISMATCH", "Raw Drive readback bytes do not match the persisted evidence.");
  }
  const receipt = {
    schemaVersion: 1,
    status: "IMPLEMENTATION_REPRESENTATIVE_ARTIFACT_LIVE_VERIFIED_PENDING_RESTART_AND_GENERALIZATION",
    evidenceId: digest({
      benchmarkEvidenceId: benchmarkEvidence.evidenceId,
      candidateId: candidate.candidateId,
      eventId: intakeReceipt.eventId,
      syncId: driveReceipt.syncId,
      sha256: rawSha256
    }),
    sourceHead: benchmarkEvidence.sourceHead,
    healthChallengeId: benchmarkEvidence.healthChallengeId,
    benchmarkEvidenceId: benchmarkEvidence.evidenceId,
    track: "IMPLEMENTATION",
    projectSelector: retrievalObservation.projectSelector,
    commandId: retrievalObservation.commandId,
    candidateId: candidate.candidateId,
    retrievalCapturedAt: retrievalObservation.capturedAt,
    eventId: intakeReceipt.eventId,
    recordKey: intakeReceipt.recordKey,
    classification: intakeReceipt.classification,
    version: intakeReceipt.version,
    sha256: rawSha256,
    size: raw.length,
    detectedMime: intakeReceipt.detectedMime,
    drive: {
      fileId: driveReceipt.drive.fileId,
      url: driveReceipt.drive.url,
      readbackSha256: driveReceipt.drive.readbackSha256,
      readbackSize: driveReceipt.drive.readbackSize
    },
    reconciliation: {
      proposalId: proposal.proposalId,
      approvalState: "PENDING_HUMAN_REVIEW",
      registryMutations: 0,
      ssotMutations: 0,
      projectFactsPromoted: false
    },
    pendingGates: [
      "LIVE_RESTART_RESUME_AND_DEDUP_VERSIONING",
      "WRITING_DRAFT_READ_ONLY_TRAVERSAL_SCHEMA_AND_VALUE_CAPTURE",
      "WRITING_APPLICATION_EXPORT_RETRIEVAL_WHEN_EXPOSED",
      "SECOND_PROJECT_GENERALIZATION_PER_TRACK"
    ],
    safety: {
      observedVia: "LIVE_BRIDGE_TOOL",
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

export function createRepresentativeArtifactEvidenceFailureReceipt({ error, clock = () => new Date() }) {
  const errorCode = error instanceof RepresentativeArtifactEvidenceError && /^[A-Z0-9_]{1,100}$/u.test(error.code)
    ? error.code
    : "REPRESENTATIVE_ARTIFACT_EVIDENCE_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: "REPRESENTATIVE_ARTIFACT_EVIDENCE_REJECTED_NO_ACCEPTANCE",
    errorCode,
    artifactRetrievalAccepted: false,
    driveReadbackAccepted: false,
    registryMutationsAccepted: 0,
    ssotMutationsAccepted: 0,
    mysmisWritesAccepted: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}
