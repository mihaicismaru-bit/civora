import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  RepresentativeArtifactEvidenceError,
  createRepresentativeArtifactEvidenceFailureReceipt,
  verifyRepresentativeArtifactEvidence
} from "../core/representative-artifact-evidence.mjs";

const CLI = resolve("native/representative-artifact-evidence-cli.mjs");
const HEAD = "1".repeat(40);
const BYTES = Buffer.from("%PDF-1.4\nrepresentative implementation artifact\n%%EOF\n", "utf8");
const SHA = createHash("sha256").update(BYTES).digest("hex");

function digest(value) {
  const canonicalize = (item) => Array.isArray(item) ? item.map(canonicalize)
    : item && typeof item === "object"
      ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonicalize(item[key])]))
      : item;
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function inputs() {
  const candidate = {
    candidateId: "candidate-implementation-contract",
    artifactKind: "DOCUMENT",
    label: "Financing contract",
    method: "GET",
    url: "https://mysmis.example/read/contract.pdf",
    strategy: "DIRECT_URL_SAFE_GET",
    retrievable: true,
    nonRetrievableReason: null,
    automatedActionAllowed: false,
    provenance: { pageUrl: "https://mysmis.example/project/view", elementIndex: 2, fixtureOrCaptureId: "capture-live" }
  };
  const benchmarkEvidence = {
    schemaVersion: 1,
    status: "BENCHMARK_DISCOVERY_LIVE_VERIFIED_PENDING_RETRIEVAL_AND_DRAFT_TRAVERSAL",
    evidenceId: "a".repeat(64),
    admissionId: "b".repeat(64),
    handoffChainId: "c".repeat(64),
    sourceHead: HEAD,
    healthChallengeId: "health-live-020",
    tracks: [
      {
        track: "IMPLEMENTATION", projectSelector: "implementation-selector", commandId: "d".repeat(64),
        capturedAt: "2026-08-30T04:30:00.000Z", candidateCounts: { total: 1, retrievable: 1, nonRetrievable: 0 }, candidates: [candidate]
      },
      {
        track: "WRITING", projectSelector: "writing-selector", commandId: "e".repeat(64),
        capturedAt: "2026-08-30T04:31:00.000Z", candidateCounts: { total: 0, retrievable: 0, nonRetrievable: 0 }, candidates: []
      }
    ],
    pendingGates: [],
    invariants: {
      sameConnectorBuild: true, projectSpecificRuntimeCode: false, acceptedLiveResponses: 2,
      controlsClicked: 0, routeMutations: 0, mysmisWrites: 0, cdpAttached: false,
      arbitraryShell: false, artifactRetrievalAccepted: false, draftTraversalAccepted: false,
      functionalAcceptance: "NOT_CLAIMED"
    }
  };
  const retrievalObservation = {
    schemaVersion: 1,
    status: "ARTIFACT_RETRIEVAL_OBSERVED",
    observedVia: "LIVE_BRIDGE_TOOL",
    connectorBuildId: HEAD,
    healthChallengeId: benchmarkEvidence.healthChallengeId,
    commandId: benchmarkEvidence.tracks[0].commandId,
    projectSelector: benchmarkEvidence.tracks[0].projectSelector,
    track: "IMPLEMENTATION",
    candidateId: candidate.candidateId,
    originalFilename: "contract.pdf",
    sourceChannel: "LIVE_BRIDGE_DOWNLOAD",
    sha256: SHA,
    size: BYTES.length,
    capturedAt: "2026-08-30T04:32:00.000Z",
    safety: { readOnly: true, controlsClicked: 0, routeMutations: 0, mysmisWrites: 0, cdpAttached: false, arbitraryShell: false }
  };
  const intakeReceipt = {
    schemaVersion: 1, eventId: "f".repeat(64), status: "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING",
    classification: "NEW_ARTIFACT", version: 1, recordKey: "9".repeat(64), sha256: SHA,
    size: BYTES.length, magicFamily: "PDF", detectedMime: "application/pdf",
    objectRelativePath: `objects/sha256/${SHA.slice(0, 2)}/${SHA}`, originalFilename: "contract.pdf",
    projectCode: "implementation-selector", track: "IMPLEMENTATION", artifactKind: "CONTRACT",
    logicalName: "Financing contract", sourceChannel: "LIVE_BRIDGE_DOWNLOAD",
    committedAt: "2026-08-30T04:33:00.000Z", replay: false,
    drive: { state: "PENDING_ADAPTER", fileId: null, readbackSha256: null },
    mysmis: { writes: 0, controlsClicked: 0 }
  };
  const syncId = digest({ eventId: intakeReceipt.eventId, sha256: SHA, target: "IMPLEMENTATION" });
  const driveReceipt = {
    schemaVersion: 1, syncId, sourceEventId: intakeReceipt.eventId,
    status: "DRIVE_PERSISTED_RECONCILIATION_PENDING", track: "IMPLEMENTATION",
    projectCode: intakeReceipt.projectCode, recordKey: intakeReceipt.recordKey,
    artifactKind: intakeReceipt.artifactKind, logicalName: intakeReceipt.logicalName,
    version: 1, sha256: SHA, size: BYTES.length,
    drive: { state: "READBACK_VERIFIED", fileId: "drive-file-020", url: "https://drive.google.com/file/d/drive-file-020/view", uploadName: `${SHA}.pdf`, readbackSha256: SHA, readbackSize: BYTES.length },
    proposalRelativePath: `drive-sync/proposals/${syncId}.json`,
    reconciliation: { state: "PENDING_HUMAN_REVIEW", promoteProjectFacts: false, mutationsApplied: 0 },
    mysmis: { writes: 0, controlsClicked: 0 }, completedAt: "2026-08-30T04:34:00.000Z", replay: false
  };
  const proposal = {
    schemaVersion: 1, proposalId: `drive-${syncId}`, operation: "APPEND_ONLY_PROPOSAL",
    approvalState: "PENDING_HUMAN_REVIEW", evidenceState: "DRIVE_READBACK_VERIFIED",
    proposedAt: "2026-08-30T04:34:00.000Z", track: "IMPLEMENTATION", projectCode: intakeReceipt.projectCode,
    promoteProjectFacts: false,
    artifactRegistryAppend: {
      target: "IMPLEMENTATION_ARTIFACT_REGISTRY", mode: "APPEND_ONLY",
      artifact: {
        recordKey: intakeReceipt.recordKey, artifactKind: "CONTRACT", logicalName: "Financing contract",
        originalFilename: "contract.pdf", version: 1, classification: "NEW_ARTIFACT", sha256: SHA,
        size: BYTES.length, detectedMime: "application/pdf", driveFileId: "drive-file-020",
        driveUrl: driveReceipt.drive.url, driveReadbackSha256: SHA
      }
    },
    ssotReconciliation: {
      target: "IMPLEMENTATION_SSOT", action: "PROPOSE_ARTIFACT_LINK_ONLY", factPromotion: false,
      artifactRecordKey: intakeReceipt.recordKey, driveFileId: "drive-file-020", sha256: SHA
    },
    safety: { mysmisWrites: 0, controlsClicked: 0, registryMutations: 0, ssotMutations: 0 }
  };
  return { benchmarkEvidence, retrievalObservation, intakeReceipt, driveReceipt, proposal, readbackBytes: BYTES };
}

test("accepts exact live implementation retrieval through raw Drive readback", () => {
  const receipt = verifyRepresentativeArtifactEvidence(inputs());
  assert.equal(receipt.status, "IMPLEMENTATION_REPRESENTATIVE_ARTIFACT_LIVE_VERIFIED_PENDING_RESTART_AND_GENERALIZATION");
  assert.equal(receipt.sha256, SHA);
  assert.equal(receipt.safety.functionalAcceptance, "NOT_CLAIMED");
});

test("rejects an offline retrieval observation", () => {
  const value = inputs();
  value.retrievalObservation.observedVia = "OFFLINE_FIXTURE";
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), RepresentativeArtifactEvidenceError);
});

test("rejects a different project-track binding", () => {
  const value = inputs();
  value.retrievalObservation.projectSelector = "other-selector";
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /admitted IMPLEMENTATION/u);
});

test("rejects a non-retrievable discovery candidate", () => {
  const value = inputs();
  value.benchmarkEvidence.tracks[0].candidates[0].retrievable = false;
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /safe retrievable/u);
});

test("rejects any MySMIS write in retrieval evidence", () => {
  const value = inputs();
  value.retrievalObservation.safety.mysmisWrites = 1;
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /zero-write/u);
});

test("rejects altered raw Drive readback bytes", () => {
  const value = inputs();
  value.readbackBytes = Buffer.from("altered");
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /Raw Drive readback/u);
});

test("rejects a sync receipt not derived from the intake event", () => {
  const value = inputs();
  value.driveReceipt.syncId = "0".repeat(64);
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /Drive receipt/u);
});

test("rejects a proposal that claims a Registry mutation", () => {
  const value = inputs();
  value.proposal.safety.registryMutations = 1;
  assert.throws(() => verifyRepresentativeArtifactEvidence(value), /append-only/u);
});

test("sanitizes a missing-live-input failure", () => {
  const failure = createRepresentativeArtifactEvidenceFailureReceipt({
    error: new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_INPUT_UNAVAILABLE", "private path"),
    clock: () => new Date("2026-08-30T04:40:00.000Z")
  });
  assert.equal(failure.status, "REPRESENTATIVE_ARTIFACT_EVIDENCE_REJECTED_NO_ACCEPTANCE");
  assert.equal(failure.functionalAcceptance, "NOT_CLAIMED");
  assert.doesNotMatch(JSON.stringify(failure), /private path/u);
});

test("CLI accepts the exact six bounded inputs and emits no files", async () => {
  const root = await mkdtemp(join(tmpdir(), "representative-artifact-"));
  const value = inputs();
  const pairs = [
    ["benchmark-evidence", value.benchmarkEvidence], ["retrieval", value.retrievalObservation],
    ["intake", value.intakeReceipt], ["sync", value.driveReceipt], ["proposal", value.proposal]
  ];
  const argv = [];
  for (const [name, item] of pairs) {
    const path = join(root, `${name}.json`);
    await writeFile(path, JSON.stringify(item));
    argv.push(`--${name}`, path);
  }
  const raw = join(root, "readback.pdf");
  await writeFile(raw, BYTES);
  argv.push("--readback", raw);
  const result = spawnSync(process.execPath, [CLI, ...argv], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).sha256, SHA);
});
