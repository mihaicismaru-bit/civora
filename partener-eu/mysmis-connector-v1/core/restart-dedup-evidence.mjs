import { createHash } from "node:crypto";
import { assertNoSensitivePersistence } from "./policy.mjs";

const SHA256 = /^[a-f0-9]{64}$/u;
const GIT_SHA = /^[a-f0-9]{40}$/u;
const RESTART_KEYS = Object.freeze([
  "adapterCallsDuringReplay", "healthChallengeId", "observedVia", "priorEvidenceId",
  "projectSelector", "replayObservedAt", "restartId", "restartedAt", "safety", "schemaVersion", "sourceHead",
  "stateRecovered", "status", "track"
]);
const ADAPTER_KEYS = Object.freeze(["downloadRaw", "uploadCreateOnly"]);
const SAFETY_KEYS = Object.freeze([
  "arbitraryShell", "controlsClicked", "mysmisWrites", "readOnly", "routeMutations"
]);

export class RestartDedupEvidenceError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "RestartDedupEvidenceError";
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
  throw new RestartDedupEvidenceError(code, message);
}

function date(value) {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function safeInputs(values) {
  try { values.forEach((value) => assertNoSensitivePersistence(value)); }
  catch { fail("RESTART_DEDUP_SENSITIVE_FIELD_DENIED", "Sensitive restart evidence is denied."); }
}

function assertBaseline(baseline) {
  if (!baseline
    || baseline.status !== "IMPLEMENTATION_REPRESENTATIVE_ARTIFACT_LIVE_VERIFIED_PENDING_RESTART_AND_GENERALIZATION"
    || !SHA256.test(baseline.evidenceId || "") || !GIT_SHA.test(baseline.sourceHead || "")
    || baseline.track !== "IMPLEMENTATION" || !SHA256.test(baseline.sha256 || "")
    || !Number.isSafeInteger(baseline.size) || baseline.size < 1
    || !Number.isSafeInteger(baseline.version) || baseline.version < 1
    || !SHA256.test(baseline.eventId || "") || !SHA256.test(baseline.recordKey || "")
    || typeof baseline.projectSelector !== "string" || !baseline.projectSelector
    || typeof baseline.drive?.fileId !== "string" || !baseline.drive.fileId
    || baseline.drive.readbackSha256 !== baseline.sha256 || baseline.drive.readbackSize !== baseline.size
    || !/^drive-[a-f0-9]{64}$/u.test(baseline.reconciliation?.proposalId || "")
    || baseline.reconciliation?.approvalState !== "PENDING_HUMAN_REVIEW"
    || baseline.reconciliation?.registryMutations !== 0 || baseline.reconciliation?.ssotMutations !== 0
    || baseline.reconciliation?.projectFactsPromoted !== false
    || baseline.safety?.mysmisWrites !== 0 || baseline.safety?.functionalAcceptance !== "NOT_CLAIMED") {
    fail("RESTART_DEDUP_BASELINE_INVALID", "A verified representative implementation artifact baseline is required.");
  }
}

function assertRestart(baseline, restart) {
  if (!exactKeys(restart, RESTART_KEYS) || !exactKeys(restart.adapterCallsDuringReplay, ADAPTER_KEYS)
    || !exactKeys(restart.safety, SAFETY_KEYS)) {
    fail("RESTART_DEDUP_RESTART_SHAPE_INVALID", "Restart observation must match the bounded live contract.");
  }
  if (restart.schemaVersion !== 1 || restart.status !== "LIVE_AGENT_RESTART_STATE_RECOVERED"
    || restart.observedVia !== "LIVE_BRIDGE_TOOL" || restart.sourceHead !== baseline.sourceHead
    || restart.healthChallengeId !== baseline.healthChallengeId || restart.priorEvidenceId !== baseline.evidenceId
    || restart.projectSelector !== baseline.projectSelector || restart.track !== "IMPLEMENTATION"
    || !SHA256.test(restart.restartId || "") || !date(restart.restartedAt) || !date(restart.replayObservedAt)
    || Date.parse(restart.replayObservedAt) < Date.parse(restart.restartedAt) || restart.stateRecovered !== true
    || restart.adapterCallsDuringReplay.uploadCreateOnly !== 0 || restart.adapterCallsDuringReplay.downloadRaw !== 0
    || restart.safety.readOnly !== true || restart.safety.controlsClicked !== 0
    || restart.safety.routeMutations !== 0 || restart.safety.mysmisWrites !== 0
    || restart.safety.arbitraryShell !== false) {
    fail("RESTART_DEDUP_RESTART_INVALID", "Restart must prove recovered state and zero replay adapter or MySMIS actions.");
  }
}

function assertReplay(baseline, restart, intake, sync) {
  const expectedSyncId = baseline.reconciliation.proposalId.slice("drive-".length);
  if (!intake || intake.status !== "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING" || intake.replay !== true
    || intake.eventId !== baseline.eventId || intake.recordKey !== baseline.recordKey
    || intake.projectCode !== baseline.projectSelector || intake.track !== "IMPLEMENTATION"
    || intake.sha256 !== baseline.sha256 || intake.size !== baseline.size || intake.version !== baseline.version
    || intake.mysmis?.writes !== 0 || intake.mysmis?.controlsClicked !== 0 || !date(intake.committedAt)) {
    fail("RESTART_DEDUP_INTAKE_REPLAY_INVALID", "Same-byte intake must replay the exact baseline record and version.");
  }
  if (!sync || sync.status !== "DRIVE_PERSISTED_RECONCILIATION_PENDING" || sync.replay !== true
    || sync.syncId !== expectedSyncId || sync.sourceEventId !== baseline.eventId
    || sync.recordKey !== baseline.recordKey || sync.projectCode !== baseline.projectSelector
    || sync.track !== "IMPLEMENTATION" || sync.sha256 !== baseline.sha256 || sync.size !== baseline.size
    || sync.version !== baseline.version || sync.drive?.fileId !== baseline.drive.fileId
    || sync.drive?.state !== "READBACK_VERIFIED" || sync.drive?.readbackSha256 !== baseline.sha256
    || sync.drive?.readbackSize !== baseline.size || sync.reconciliation?.mutationsApplied !== 0
    || sync.reconciliation?.promoteProjectFacts !== false
    || sync.mysmis?.writes !== 0 || sync.mysmis?.controlsClicked !== 0) {
    fail("RESTART_DEDUP_DRIVE_REPLAY_INVALID", "Drive replay must reuse the exact verified object without a new sync identity.");
  }
}

function syncIdFor(intake) {
  return digest({ eventId: intake.eventId, sha256: intake.sha256, target: intake.track });
}

function assertVersion(baseline, restart, intake, sync, proposal, rawBytes) {
  if (!intake || intake.status !== "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING" || intake.replay !== false
    || intake.track !== "IMPLEMENTATION" || intake.projectCode !== baseline.projectSelector
    || intake.recordKey !== baseline.recordKey || intake.eventId === baseline.eventId
    || !SHA256.test(intake.eventId || "") || !SHA256.test(intake.sha256 || "")
    || intake.sha256 === baseline.sha256 || !Number.isSafeInteger(intake.size) || intake.size < 1
    || intake.version !== baseline.version + 1
    || !["NEW_VERSION", "DEDUP_SHARED_BYTES_NEW_VERSION"].includes(intake.classification)
    || intake.mysmis?.writes !== 0 || intake.mysmis?.controlsClicked !== 0
    || !date(intake.committedAt) || Date.parse(intake.committedAt) < Date.parse(restart.restartedAt)) {
    fail("RESTART_DEDUP_VERSION_INTAKE_INVALID", "Changed bytes must create exactly the next logical artifact version.");
  }
  const syncId = syncIdFor(intake);
  if (!sync || sync.status !== "DRIVE_PERSISTED_RECONCILIATION_PENDING" || sync.replay !== false
    || sync.syncId !== syncId || sync.sourceEventId !== intake.eventId || sync.recordKey !== intake.recordKey
    || sync.projectCode !== intake.projectCode || sync.track !== intake.track || sync.sha256 !== intake.sha256
    || sync.size !== intake.size || sync.version !== intake.version || sync.drive?.state !== "READBACK_VERIFIED"
    || typeof sync.drive?.fileId !== "string" || !sync.drive.fileId || sync.drive.fileId === baseline.drive.fileId
    || sync.drive.readbackSha256 !== intake.sha256 || sync.drive.readbackSize !== intake.size
    || sync.reconciliation?.state !== "PENDING_HUMAN_REVIEW"
    || sync.reconciliation?.promoteProjectFacts !== false || sync.reconciliation?.mutationsApplied !== 0
    || sync.mysmis?.writes !== 0 || sync.mysmis?.controlsClicked !== 0) {
    fail("RESTART_DEDUP_VERSION_DRIVE_INVALID", "New version Drive receipt must bind the next bytes and remain reconciliation-pending.");
  }
  if (!proposal || proposal.proposalId !== `drive-${syncId}` || proposal.operation !== "APPEND_ONLY_PROPOSAL"
    || proposal.approvalState !== "PENDING_HUMAN_REVIEW" || proposal.evidenceState !== "DRIVE_READBACK_VERIFIED"
    || proposal.track !== "IMPLEMENTATION" || proposal.projectCode !== intake.projectCode
    || proposal.promoteProjectFacts !== false
    || proposal.artifactRegistryAppend?.target !== "IMPLEMENTATION_ARTIFACT_REGISTRY"
    || proposal.artifactRegistryAppend?.mode !== "APPEND_ONLY"
    || proposal.ssotReconciliation?.target !== "IMPLEMENTATION_SSOT"
    || proposal.ssotReconciliation?.action !== "PROPOSE_ARTIFACT_LINK_ONLY"
    || proposal.ssotReconciliation?.factPromotion !== false
    || proposal.safety?.mysmisWrites !== 0 || proposal.safety?.controlsClicked !== 0
    || proposal.safety?.registryMutations !== 0 || proposal.safety?.ssotMutations !== 0) {
    fail("RESTART_DEDUP_VERSION_PROPOSAL_INVALID", "New version proposal must remain untouched and append-only.");
  }
  const artifact = proposal.artifactRegistryAppend.artifact;
  const ssot = proposal.ssotReconciliation;
  if (!artifact || artifact.recordKey !== intake.recordKey || artifact.version !== intake.version
    || artifact.classification !== intake.classification || artifact.sha256 !== intake.sha256
    || artifact.size !== intake.size || artifact.driveFileId !== sync.drive.fileId
    || artifact.driveReadbackSha256 !== intake.sha256
    || ssot.artifactRecordKey !== intake.recordKey || ssot.driveFileId !== sync.drive.fileId
    || ssot.sha256 !== intake.sha256) {
    fail("RESTART_DEDUP_VERSION_BINDING_MISMATCH", "Version proposal does not match the verified intake and Drive object.");
  }
  const raw = Buffer.isBuffer(rawBytes) ? rawBytes : Buffer.from(rawBytes || []);
  const rawSha256 = createHash("sha256").update(raw).digest("hex");
  if (raw.length !== intake.size || rawSha256 !== intake.sha256) {
    fail("RESTART_DEDUP_VERSION_READBACK_MISMATCH", "New version raw Drive readback bytes do not match the receipts.");
  }
  return { syncId, rawSha256, rawSize: raw.length };
}

export function verifyRestartDedupVersionEvidence({
  representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt,
  versionIntakeReceipt, versionDriveReceipt, versionProposal, versionReadbackBytes
}) {
  safeInputs([
    representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt,
    versionIntakeReceipt, versionDriveReceipt, versionProposal
  ]);
  assertBaseline(representativeEvidence);
  assertRestart(representativeEvidence, restartObservation);
  assertReplay(representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt);
  const version = assertVersion(
    representativeEvidence, restartObservation, versionIntakeReceipt,
    versionDriveReceipt, versionProposal, versionReadbackBytes
  );
  const receipt = {
    schemaVersion: 1,
    status: "IMPLEMENTATION_LIVE_RESTART_RESUME_DEDUP_VERSIONING_VERIFIED_PENDING_WRITING_AND_GENERALIZATION",
    evidenceId: digest({
      priorEvidenceId: representativeEvidence.evidenceId,
      restartId: restartObservation.restartId,
      replayEventId: replayIntakeReceipt.eventId,
      versionEventId: versionIntakeReceipt.eventId,
      versionSyncId: version.syncId,
      versionSha256: version.rawSha256
    }),
    sourceHead: representativeEvidence.sourceHead,
    healthChallengeId: representativeEvidence.healthChallengeId,
    priorEvidenceId: representativeEvidence.evidenceId,
    restartId: restartObservation.restartId,
    projectSelector: representativeEvidence.projectSelector,
    track: "IMPLEMENTATION",
    replay: {
      eventId: replayIntakeReceipt.eventId,
      recordKey: replayIntakeReceipt.recordKey,
      version: replayIntakeReceipt.version,
      sha256: replayIntakeReceipt.sha256,
      driveFileId: replayDriveReceipt.drive.fileId,
      newIntakeVersionCreated: false,
      newDriveFileCreated: false,
      uploadCreateOnlyCalls: 0,
      downloadRawCalls: 0
    },
    changedBytesVersion: {
      eventId: versionIntakeReceipt.eventId,
      recordKey: versionIntakeReceipt.recordKey,
      classification: versionIntakeReceipt.classification,
      version: versionIntakeReceipt.version,
      sha256: version.rawSha256,
      size: version.rawSize,
      driveFileId: versionDriveReceipt.drive.fileId,
      proposalId: versionProposal.proposalId,
      rawReadbackVerified: true
    },
    pendingGates: [
      "WRITING_DRAFT_READ_ONLY_TRAVERSAL_SCHEMA_AND_VALUE_CAPTURE",
      "WRITING_APPLICATION_EXPORT_RETRIEVAL_WHEN_EXPOSED",
      "SECOND_PROJECT_GENERALIZATION_PER_TRACK"
    ],
    safety: {
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      registryMutations: 0,
      ssotMutations: 0,
      arbitraryShell: false,
      functionalAcceptance: "NOT_CLAIMED"
    }
  };
  assertNoSensitivePersistence(receipt);
  return Object.freeze(receipt);
}

export function createRestartDedupEvidenceFailureReceipt({ error, clock = () => new Date() }) {
  const errorCode = error instanceof RestartDedupEvidenceError && /^[A-Z0-9_]{1,100}$/u.test(error.code)
    ? error.code
    : "RESTART_DEDUP_EVIDENCE_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: "RESTART_DEDUP_VERSION_EVIDENCE_REJECTED_NO_ACCEPTANCE",
    errorCode,
    restartAccepted: false,
    sameByteReplayAccepted: false,
    dedupAccepted: false,
    versioningAccepted: false,
    mysmisWritesAccepted: 0,
    registryMutationsAccepted: 0,
    ssotMutationsAccepted: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}
