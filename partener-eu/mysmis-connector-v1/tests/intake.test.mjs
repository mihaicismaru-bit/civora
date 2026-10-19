import assert from "node:assert/strict";
import { mkdtemp, mkdir, readFile, rm, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";
import {
  inspectSpool,
  intakeManualDownload,
  IntakeError,
  validateManualDownload
} from "../native/intake.mjs";

const FIXED_TIME = "2026-08-29T11:00:00.000Z";
const clock = () => new Date(FIXED_TIME);
const pdf = (label) => Buffer.from(`%PDF-1.7\n% fixture ${label}\n1 0 obj\n<<>>\nendobj\n%%EOF\n`, "utf8");

async function workspace(t) {
  const root = await mkdtemp(join(tmpdir(), "mysmis-intake-test-"));
  t.after(() => rm(root, { recursive: true, force: true }));
  const downloads = join(root, "downloads");
  const spool = join(root, "spool");
  await mkdir(downloads, { recursive: true });
  return { root, downloads, spool };
}

function metadata(overrides = {}) {
  return {
    projectCode: "310224",
    track: "IMPLEMENTATION",
    artifactKind: "CONTRACT",
    logicalName: "Financing contract",
    originalFilename: "contract.pdf",
    declaredMime: "application/pdf",
    sourceChannel: "MANUAL_DOWNLOAD",
    ...overrides
  };
}

test("commits a validated manual PDF into a content-addressed restart-safe spool", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  const bytes = pdf("v1");
  await writeFile(source, bytes);
  const receipt = await intakeManualDownload({
    sourcePath: source,
    spoolRoot: spool,
    metadata: metadata({ expectedBytes: bytes.length }),
    clock
  });

  assert.equal(receipt.status, "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING");
  assert.equal(receipt.classification, "NEW_ARTIFACT");
  assert.equal(receipt.version, 1);
  assert.equal(receipt.magicFamily, "PDF");
  assert.equal(receipt.mysmis.writes, 0);
  assert.deepEqual(await readFile(source), bytes);
  assert.deepEqual(await readFile(join(spool, receipt.objectRelativePath)), bytes);
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 1, recordCount: 1, versionCount: 1 });
});

test("replay is idempotent and same bytes do not create another version", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  await writeFile(source, pdf("v1"));
  const first = await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  const replay = await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  assert.equal(replay.eventId, first.eventId);
  assert.equal(replay.replay, true);
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 1, recordCount: 1, versionCount: 1 });
});

test("resumes the same planned version after a crash following object persistence", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  await writeFile(source, pdf("crash-resume"));
  await assert.rejects(
    intakeManualDownload({
      sourcePath: source,
      spoolRoot: spool,
      metadata: metadata(),
      clock,
      faultInjector: (phase) => {
        if (phase === "OBJECT_PERSISTED") throw new Error("simulated-process-stop");
      }
    }),
    /simulated-process-stop/u
  );
  const resumed = await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  assert.equal(resumed.classification, "NEW_ARTIFACT");
  assert.equal(resumed.version, 1);
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 1, recordCount: 1, versionCount: 1 });
});

test("new bytes for the same logical artifact create version two", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  await writeFile(source, pdf("v1"));
  await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  await writeFile(source, pdf("v2"));
  const second = await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  assert.equal(second.classification, "NEW_VERSION");
  assert.equal(second.version, 2);
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 2, recordCount: 1, versionCount: 2 });
});

test("same bytes across artifact records reuse one content object", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "document.pdf");
  await writeFile(source, pdf("shared"));
  await intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata(), clock });
  const shared = await intakeManualDownload({
    sourcePath: source,
    spoolRoot: spool,
    metadata: metadata({ artifactKind: "APPLICATION", logicalName: "Current application", originalFilename: "application.pdf" }),
    clock
  });
  assert.equal(shared.classification, "DEDUP_SHARED_BYTES");
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 1, recordCount: 2, versionCount: 2 });
});

test("310224 HTML route response fails closed as non-binary", async (t) => {
  const { downloads, spool } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  const html = Buffer.from("<!doctype html><html><body>DOSAR_CONTRACT</body></html>", "utf8");
  await writeFile(source, html);
  await assert.rejects(
    intakeManualDownload({ sourcePath: source, spoolRoot: spool, metadata: metadata({ expectedBytes: html.length }), clock }),
    (error) => error instanceof IntakeError
      && error.code === "VALIDATION_FAILED"
      && error.details.reasons.includes("NON_BINARY_HTML_DENIED")
      && error.details.reasons.includes("PDF_EXTENSION_MAGIC_MISMATCH")
  );
  assert.deepEqual(await inspectSpool(spool), { schemaVersion: 1, objectCount: 0, recordCount: 0, versionCount: 0 });
});

test("size and MIME mismatches are explicit integrity failures", async (t) => {
  const { downloads } = await workspace(t);
  const source = join(downloads, "report.pdf");
  const bytes = pdf("report");
  await writeFile(source, bytes);
  const result = await validateManualDownload(source, metadata({ declaredMime: "application/zip", expectedBytes: bytes.length + 1 }));
  assert.equal(result.validation.ok, false);
  assert.ok(result.validation.reasons.includes("DECLARED_MIME_MAGIC_MISMATCH"));
  assert.ok(result.validation.reasons.includes("EXPECTED_SIZE_MISMATCH"));
});

test("sensitive metadata and symlink sources are denied", async (t) => {
  const { downloads } = await workspace(t);
  const source = join(downloads, "contract.pdf");
  await writeFile(source, pdf("v1"));
  await assert.rejects(
    validateManualDownload(source, { ...metadata(), authorization: "Bearer denied" }),
    /Sensitive field denied/u
  );
  const link = join(downloads, "linked-contract.pdf");
  await symlink(source, link);
  await assert.rejects(
    validateManualDownload(link, metadata()),
    (error) => error instanceof IntakeError && error.code === "SYMLINK_DENIED"
  );
});
