import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import test from "node:test";
import {
  RestartDedupEvidenceError,
  createRestartDedupEvidenceFailureReceipt,
  verifyRestartDedupVersionEvidence
} from "../core/restart-dedup-evidence.mjs";

const CLI = resolve("native/restart-dedup-evidence-cli.mjs");
const HEAD = "2".repeat(40);
const OLD_BYTES = Buffer.from("%PDF-1.4\nbaseline\n%%EOF\n");
const NEW_BYTES = Buffer.from("%PDF-1.4\nchanged version\n%%EOF\n");
const OLD_SHA = createHash("sha256").update(OLD_BYTES).digest("hex");
const NEW_SHA = createHash("sha256").update(NEW_BYTES).digest("hex");

function digest(value) {
  const canonicalize = (item) => Array.isArray(item) ? item.map(canonicalize)
    : item && typeof item === "object"
      ? Object.fromEntries(Object.keys(item).sort().map((key) => [key, canonicalize(item[key])]))
      : item;
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

function fixture() {
  const baselineSyncId = "3".repeat(64);
  const representativeEvidence = {
    schemaVersion: 1,
    status: "IMPLEMENTATION_REPRESENTATIVE_ARTIFACT_LIVE_VERIFIED_PENDING_RESTART_AND_GENERALIZATION",
    evidenceId: "4".repeat(64), sourceHead: HEAD, healthChallengeId: "health-021",
    benchmarkEvidenceId: "5".repeat(64), track: "IMPLEMENTATION", projectSelector: "implementation-selector",
    commandId: "6".repeat(64), candidateId: "candidate-contract", retrievalCapturedAt: "2026-08-30T05:10:00.000Z",
    eventId: "7".repeat(64), recordKey: "8".repeat(64), classification: "NEW_ARTIFACT",
    version: 1, sha256: OLD_SHA, size: OLD_BYTES.length, detectedMime: "application/pdf",
    drive: { fileId: "drive-old", url: "https://drive.google.com/file/d/drive-old/view", readbackSha256: OLD_SHA, readbackSize: OLD_BYTES.length },
    reconciliation: { proposalId: `drive-${baselineSyncId}`, approvalState: "PENDING_HUMAN_REVIEW", registryMutations: 0, ssotMutations: 0, projectFactsPromoted: false },
    pendingGates: [],
    safety: { observedVia: "LIVE_BRIDGE_TOOL", controlsClicked: 0, routeMutations: 0, mysmisWrites: 0, cdpAttached: false, arbitraryShell: false, functionalAcceptance: "NOT_CLAIMED" }
  };
  const restartObservation = {
    schemaVersion: 1, status: "LIVE_AGENT_RESTART_STATE_RECOVERED", observedVia: "LIVE_BRIDGE_TOOL",
    sourceHead: HEAD, healthChallengeId: "health-021", priorEvidenceId: representativeEvidence.evidenceId,
    projectSelector: representativeEvidence.projectSelector, track: "IMPLEMENTATION", restartId: "9".repeat(64),
    restartedAt: "2026-08-30T05:11:00.000Z", replayObservedAt: "2026-08-30T05:12:00.000Z",
    stateRecovered: true, adapterCallsDuringReplay: { uploadCreateOnly: 0, downloadRaw: 0 },
    safety: { readOnly: true, controlsClicked: 0, routeMutations: 0, mysmisWrites: 0, arbitraryShell: false }
  };
  const replayIntakeReceipt = {
    schemaVersion: 1, eventId: representativeEvidence.eventId, status: "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING",
    classification: "NEW_ARTIFACT", version: 1, recordKey: representativeEvidence.recordKey,
    sha256: OLD_SHA, size: OLD_BYTES.length, magicFamily: "PDF", detectedMime: "application/pdf",
    objectRelativePath: "objects/old", originalFilename: "contract.pdf", projectCode: "implementation-selector",
    track: "IMPLEMENTATION", artifactKind: "CONTRACT", logicalName: "Financing contract",
    sourceChannel: "LIVE_BRIDGE_DOWNLOAD", committedAt: "2026-08-30T05:10:30.000Z", replay: true,
    drive: { state: "PENDING_ADAPTER", fileId: null, readbackSha256: null }, mysmis: { writes: 0, controlsClicked: 0 }
  };
  const replayDriveReceipt = {
    schemaVersion: 1, syncId: baselineSyncId, sourceEventId: representativeEvidence.eventId,
    status: "DRIVE_PERSISTED_RECONCILIATION_PENDING", track: "IMPLEMENTATION",
    projectCode: "implementation-selector", recordKey: representativeEvidence.recordKey,
    artifactKind: "CONTRACT", logicalName: "Financing contract", version: 1, sha256: OLD_SHA,
    size: OLD_BYTES.length, drive: { state: "READBACK_VERIFIED", fileId: "drive-old", url: representativeEvidence.drive.url, uploadName: `${OLD_SHA}.pdf`, readbackSha256: OLD_SHA, readbackSize: OLD_BYTES.length },
    proposalRelativePath: "drive-sync/proposals/old.json",
    reconciliation: { state: "PENDING_HUMAN_REVIEW", promoteProjectFacts: false, mutationsApplied: 0 },
    mysmis: { writes: 0, controlsClicked: 0 }, completedAt: "2026-08-30T05:10:40.000Z", replay: true
  };
  const versionIntakeReceipt = {
    ...replayIntakeReceipt, eventId: "a".repeat(64), classification: "NEW_VERSION", version: 2,
    sha256: NEW_SHA, size: NEW_BYTES.length, objectRelativePath: "objects/new",
    committedAt: "2026-08-30T05:13:00.000Z", replay: false
  };
  const versionSyncId = digest({ eventId: versionIntakeReceipt.eventId, sha256: NEW_SHA, target: "IMPLEMENTATION" });
  const versionDriveReceipt = {
    ...replayDriveReceipt, syncId: versionSyncId, sourceEventId: versionIntakeReceipt.eventId,
    version: 2, sha256: NEW_SHA, size: NEW_BYTES.length,
    drive: { state: "READBACK_VERIFIED", fileId: "drive-new", url: "https://drive.google.com/file/d/drive-new/view", uploadName: `${NEW_SHA}.pdf`, readbackSha256: NEW_SHA, readbackSize: NEW_BYTES.length },
    proposalRelativePath: `drive-sync/proposals/${versionSyncId}.json`,
    completedAt: "2026-08-30T05:14:00.000Z", replay: false
  };
  const versionProposal = {
    schemaVersion: 1, proposalId: `drive-${versionSyncId}`, operation: "APPEND_ONLY_PROPOSAL",
    approvalState: "PENDING_HUMAN_REVIEW", evidenceState: "DRIVE_READBACK_VERIFIED",
    proposedAt: "2026-08-30T05:14:00.000Z", track: "IMPLEMENTATION",
    projectCode: "implementation-selector", promoteProjectFacts: false,
    artifactRegistryAppend: {
      target: "IMPLEMENTATION_ARTIFACT_REGISTRY", mode: "APPEND_ONLY",
      artifact: {
        recordKey: representativeEvidence.recordKey, artifactKind: "CONTRACT", logicalName: "Financing contract",
        originalFilename: "contract.pdf", version: 2, classification: "NEW_VERSION", sha256: NEW_SHA,
        size: NEW_BYTES.length, detectedMime: "application/pdf", driveFileId: "drive-new",
        driveUrl: versionDriveReceipt.drive.url, driveReadbackSha256: NEW_SHA
      }
    },
    ssotReconciliation: { target: "IMPLEMENTATION_SSOT", action: "PROPOSE_ARTIFACT_LINK_ONLY", factPromotion: false, artifactRecordKey: representativeEvidence.recordKey, driveFileId: "drive-new", sha256: NEW_SHA },
    safety: { mysmisWrites: 0, controlsClicked: 0, registryMutations: 0, ssotMutations: 0 }
  };
  return {
    representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt,
    versionIntakeReceipt, versionDriveReceipt, versionProposal, versionReadbackBytes: NEW_BYTES
  };
}

test("verifies restart replay without upload and exact next-byte version", () => {
  const receipt = verifyRestartDedupVersionEvidence(fixture());
  assert.equal(receipt.status, "IMPLEMENTATION_LIVE_RESTART_RESUME_DEDUP_VERSIONING_VERIFIED_PENDING_WRITING_AND_GENERALIZATION");
  assert.equal(receipt.replay.newDriveFileCreated, false);
  assert.equal(receipt.changedBytesVersion.version, 2);
  assert.equal(receipt.safety.functionalAcceptance, "NOT_CLAIMED");
});

test("rejects offline restart observations", () => {
  const value = fixture(); value.restartObservation.observedVia = "OFFLINE_FIXTURE";
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /Restart must prove/u);
});

test("rejects replay adapter calls after restart", () => {
  const value = fixture(); value.restartObservation.adapterCallsDuringReplay.uploadCreateOnly = 1;
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /zero replay adapter/u);
});

test("rejects same-byte replay that creates another version", () => {
  const value = fixture(); value.replayIntakeReceipt.version = 2;
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /exact baseline record/u);
});

test("rejects replay that changes the Drive file identity", () => {
  const value = fixture(); value.replayDriveReceipt.drive.fileId = "duplicate-drive-file";
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /reuse the exact verified object/u);
});

test("rejects changed bytes without next logical version", () => {
  const value = fixture(); value.versionIntakeReceipt.version = 3;
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /next logical artifact version/u);
});

test("rejects corrupted version readback", () => {
  const value = fixture(); value.versionReadbackBytes = Buffer.from("corrupt");
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /raw Drive readback/u);
});

test("rejects Registry or SSOT mutation claims", () => {
  const value = fixture(); value.versionProposal.safety.ssotMutations = 1;
  assert.throws(() => verifyRestartDedupVersionEvidence(value), /untouched and append-only/u);
});

test("failure receipt is sanitized and claims no acceptance", () => {
  const receipt = createRestartDedupEvidenceFailureReceipt({
    error: new RestartDedupEvidenceError("RESTART_DEDUP_INPUT_UNAVAILABLE", "private path"),
    clock: () => new Date("2026-08-30T05:20:00.000Z")
  });
  assert.equal(receipt.status, "RESTART_DEDUP_VERSION_EVIDENCE_REJECTED_NO_ACCEPTANCE");
  assert.equal(receipt.functionalAcceptance, "NOT_CLAIMED");
  assert.doesNotMatch(JSON.stringify(receipt), /private path/u);
});

test("CLI reads only the exact eight bounded inputs", async () => {
  const root = await mkdtemp(join(tmpdir(), "restart-dedup-"));
  const value = fixture();
  const pairs = [
    ["representative", value.representativeEvidence], ["restart", value.restartObservation],
    ["replay-intake", value.replayIntakeReceipt], ["replay-sync", value.replayDriveReceipt],
    ["version-intake", value.versionIntakeReceipt], ["version-sync", value.versionDriveReceipt],
    ["version-proposal", value.versionProposal]
  ];
  const argv = [];
  for (const [name, item] of pairs) {
    const path = join(root, `${name}.json`); await writeFile(path, JSON.stringify(item)); argv.push(`--${name}`, path);
  }
  const raw = join(root, "version.pdf"); await writeFile(raw, NEW_BYTES); argv.push("--version-readback", raw);
  const result = spawnSync(process.execPath, [CLI, ...argv], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(result.stdout).changedBytesVersion.sha256, NEW_SHA);
});
