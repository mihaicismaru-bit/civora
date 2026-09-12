import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import { DriveSyncError, syncCommittedObjectToDrive } from "../native/drive-sync.mjs";
import { createExternalDriveExchangeAdapter } from "../native/external-drive-adapter.mjs";
import { intakeManualDownload } from "../native/intake.mjs";

const FIXED_TIME = "2026-08-29T13:00:00.000Z";
const clock = () => new Date(FIXED_TIME);
const bytes = Buffer.from("%PDF-1.7\n% harmless external Drive fixture\n%%EOF\n", "utf8");

async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), "mysmis-external-drive-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const downloads = join(root, "downloads");
  const spool = join(root, "spool");
  const exchange = join(spool, "external-drive-exchange");
  await mkdir(downloads, { recursive: true });
  const source = join(downloads, "harmless.pdf");
  await writeFile(source, bytes);
  const receipt = await intakeManualDownload({
    sourcePath: source,
    spoolRoot: spool,
    metadata: {
      projectCode: "367944",
      track: "WRITING",
      artifactKind: "CONNECTOR_TEST_OBJECT",
      logicalName: "Harmless external Drive roundtrip",
      originalFilename: "harmless.pdf",
      declaredMime: "application/pdf",
      expectedBytes: bytes.length,
      sourceChannel: "MANUAL_DOWNLOAD"
    },
    clock
  });
  return { root, spool, exchange, receipt };
}

function adapter(spool, exchange) {
  return createExternalDriveExchangeAdapter({ spoolRoot: spool, exchangeRoot: exchange, clock });
}

async function writeResponse(exchange, receipt, overrides = {}) {
  const responsePath = join(exchange, "responses", `${receipt.sha256}.json`);
  await mkdir(join(exchange, "responses"), { recursive: true });
  await writeFile(responsePath, `${JSON.stringify({
    schemaVersion: 1,
    state: "UPLOAD_AND_READBACK_COMPLETE",
    contentKey: receipt.sha256,
    fileId: "observed-drive-file-001",
    url: "https://drive.google.com/file/d/observed-drive-file-001/view",
    createdNew: true,
    readbackBase64: bytes.toString("base64"),
    ...overrides
  }, null, 2)}\n`, "utf8");
}

test("emits a bridge-safe create-only plan without an absolute local path", async (t) => {
  const { spool, exchange, receipt } = await workspace(t);
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error instanceof DriveSyncError && error.code === "EXTERNAL_DRIVE_UPLOAD_PENDING"
  );
  const plan = JSON.parse(await readFile(join(exchange, "requests", `${receipt.sha256}.json`), "utf8"));
  assert.equal(plan.createOnly, true);
  assert.equal(plan.contentKey, receipt.sha256);
  assert.equal(plan.size, receipt.size);
  assert.equal(plan.spoolObjectRelativePath.startsWith("objects/"), true);
  assert.equal(JSON.stringify(plan).includes(spool), false);
});

test("completes the same sync state machine from an observed Drive response", async (t) => {
  const { spool, exchange, receipt } = await workspace(t);
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error.code === "EXTERNAL_DRIVE_UPLOAD_PENDING"
  );
  await writeResponse(exchange, receipt);
  const synced = await syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock });
  assert.equal(synced.status, "DRIVE_PERSISTED_RECONCILIATION_PENDING");
  assert.equal(synced.drive.fileId, "observed-drive-file-001");
  assert.equal(synced.drive.readbackSha256, receipt.sha256);
  assert.equal(synced.reconciliation.mutationsApplied, 0);
  const persisted = await readFile(join(spool, "drive-sync", "checkpoints", `${synced.syncId}.json`), "utf8");
  assert.equal(persisted.includes("readbackBase64"), false);
});

test("remote readback corruption remains fail-closed", async (t) => {
  const { spool, exchange, receipt } = await workspace(t);
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error.code === "EXTERNAL_DRIVE_UPLOAD_PENDING"
  );
  await writeResponse(exchange, receipt, { readbackBase64: Buffer.from("corrupt", "utf8").toString("base64") });
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error instanceof DriveSyncError && error.code === "DRIVE_READBACK_INTEGRITY_MISMATCH"
  );
});

test("sensitive response fields are rejected before checkpoint persistence", async (t) => {
  const { spool, exchange, receipt } = await workspace(t);
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error.code === "EXTERNAL_DRIVE_UPLOAD_PENDING"
  );
  await writeResponse(exchange, receipt, { authorization: "denied" });
  await assert.rejects(
    syncCommittedObjectToDrive({ receipt, spoolRoot: spool, adapter: adapter(spool, exchange), clock }),
    (error) => error instanceof DriveSyncError && error.code === "SENSITIVE_PERSISTENCE_DENIED"
  );
});
