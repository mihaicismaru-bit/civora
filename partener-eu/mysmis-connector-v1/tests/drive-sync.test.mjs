import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { syncCommittedObjectToDrive, DriveSyncError } from "../native/drive-sync.mjs";
import { intakeManualDownload } from "../native/intake.mjs";

const FIXED_TIME = "2026-08-29T12:00:00.000Z";
const clock = () => new Date(FIXED_TIME);
const pdf = (label) => Buffer.from(`%PDF-1.7\n% fixture ${label}\n1 0 obj\n<<>>\nendobj\n%%EOF\n`, "utf8");

async function workspace(t, track = "IMPLEMENTATION") {
  const root = await mkdtemp(join(tmpdir(), "mysmis-drive-sync-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const downloads = join(root, "downloads");
  const spool = join(root, "spool");
  await mkdir(downloads, { recursive: true });
  const source = join(downloads, "artifact.pdf");
  const bytes = pdf(track);
  await writeFile(source, bytes);
  const receipt = await intakeManualDownload({
    sourcePath: source,
    spoolRoot: spool,
    metadata: {
      projectCode: track === "WRITING" ? "367944" : "310224",
      track,
      artifactKind: track === "WRITING" ? "APPLICATION_EXPORT" : "CONTRACT",
      logicalName: "Benchmark artifact",
      originalFilename: "artifact.pdf",
      declaredMime: "application/pdf",
      expectedBytes: bytes.length,
      sourceChannel: "MANUAL_DOWNLOAD"
    },
    clock
  });
  return { root, spool, source, bytes, receipt };
}

function fakeDrive(bytes, overrides = {}) {
  const state = { uploads: [], downloads: [] };
  return {
    state,
    adapter: {
      async uploadCreateOnly(request) {
        state.uploads.push(request);
        return overrides.uploadResponse || {
          fileId: "drive-file-001",
          url: "https://drive.google.com/file/d/drive-file-001/view",
          createdNew: true
        };
      },
      async downloadRaw(request) {
        state.downloads.push(request);
        return overrides.readback || bytes;
      }
    }
  };
}

test("uploads one content-addressed IMPLEMENTATION object and proposes append-only reconciliation", async (t) => {
  const { spool, bytes, receipt } = await workspace(t);
  const drive = fakeDrive(bytes);
  const synced = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock });

  assert.equal(synced.status, "DRIVE_PERSISTED_RECONCILIATION_PENDING");
  assert.equal(synced.drive.state, "READBACK_VERIFIED");
  assert.equal(synced.drive.readbackSha256, receipt.sha256);
  assert.equal(synced.reconciliation.mutationsApplied, 0);
  assert.equal(synced.mysmis.writes, 0);
  assert.equal(drive.state.uploads.length, 1);
  assert.equal(drive.state.uploads[0].createOnly, true);
  assert.equal(drive.state.uploads[0].contentKey, receipt.sha256);
  assert.equal(drive.state.uploads[0].fileName, `${receipt.sha256}.pdf`);
  assert.equal(drive.state.downloads.length, 1);

  const proposal = JSON.parse(await readFile(join(spool, synced.proposalRelativePath), "utf8"));
  assert.equal(proposal.artifactRegistryAppend.target, "IMPLEMENTATION_ARTIFACT_REGISTRY");
  assert.equal(proposal.ssotReconciliation.target, "IMPLEMENTATION_SSOT");
  assert.equal(proposal.promoteProjectFacts, false);
  assert.equal(proposal.safety.registryMutations, 0);
});

test("keeps WRITING registry and SSOT targets separate", async (t) => {
  const { spool, bytes, receipt } = await workspace(t, "WRITING");
  const drive = fakeDrive(bytes);
  const synced = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock });
  const proposal = JSON.parse(await readFile(join(spool, synced.proposalRelativePath), "utf8"));
  assert.equal(proposal.track, "WRITING");
  assert.equal(proposal.artifactRegistryAppend.target, "WRITING_ARTIFACT_REGISTRY");
  assert.equal(proposal.ssotReconciliation.target, "WRITING_SSOT");
});

test("replay is idempotent and does not upload or read back twice", async (t) => {
  const { spool, bytes, receipt } = await workspace(t);
  const drive = fakeDrive(bytes);
  const first = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock });
  const replay = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock });
  assert.equal(replay.syncId, first.syncId);
  assert.equal(replay.replay, true);
  assert.equal(drive.state.uploads.length, 1);
  assert.equal(drive.state.downloads.length, 1);
});

test("resumes after an upload checkpoint without creating a duplicate Drive file", async (t) => {
  const { spool, bytes, receipt } = await workspace(t);
  const drive = fakeDrive(bytes);
  await assert.rejects(
    syncCommittedObjectToDrive({
      receipt,
      spoolRoot: spool,
      adapter: drive.adapter,
      clock,
      faultInjector: (phase) => {
        if (phase === "UPLOADED") throw new Error("simulated-process-stop");
      }
    }),
    /simulated-process-stop/u
  );
  const resumed = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock });
  assert.equal(resumed.drive.fileId, "drive-file-001");
  assert.equal(drive.state.uploads.length, 1);
  assert.equal(drive.state.downloads.length, 1);
});

test("fails closed on Drive readback mismatch and creates no proposal", async (t) => {
  const { spool, receipt } = await workspace(t);
  const drive = fakeDrive(Buffer.from("corrupted", "utf8"));
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock }),
    (error) => error instanceof DriveSyncError && error.code === "DRIVE_READBACK_INTEGRITY_MISMATCH"
  );
  const syncId = (await import("node:crypto")).createHash("sha256").update(JSON.stringify({
    eventId: receipt.eventId,
    sha256: receipt.sha256,
    target: receipt.track
  })).digest("hex");
  await assert.rejects(readFile(join(spool, "drive-sync", "proposals", `${syncId}.json`)), { code: "ENOENT" });
});

test("denies a changed local object before any Drive call", async (t) => {
  const { spool, receipt } = await workspace(t);
  await writeFile(join(spool, receipt.objectRelativePath), pdf("tampered"));
  const drive = fakeDrive(pdf("tampered"));
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: drive.adapter, clock }),
    (error) => error instanceof DriveSyncError && error.code === "SPOOL_OBJECT_INTEGRITY_MISMATCH"
  );
  assert.equal(drive.state.uploads.length, 0);
});

test("denies sensitive or credential-bearing upload responses", async (t) => {
  const { spool, bytes, receipt } = await workspace(t);
  const withSecretField = fakeDrive(bytes, {
    uploadResponse: { fileId: "drive-file-001", authorization: "Bearer denied" }
  });
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: withSecretField.adapter, clock }),
    /Sensitive field denied/u
  );

  const second = await workspace(t);
  const withCredentialUrl = fakeDrive(second.bytes, {
    uploadResponse: {
      fileId: "drive-file-002",
      url: "https://drive.google.com/file/d/drive-file-002/view?access_token=denied"
    }
  });
  await assert.rejects(
    syncCommittedObjectToDrive({
      receipt: second.receipt,
      spoolRoot: second.spool,
      adapter: withCredentialUrl.adapter,
      clock
    }),
    (error) => error instanceof DriveSyncError && error.code === "DRIVE_UPLOAD_RESPONSE_INVALID"
  );
});
