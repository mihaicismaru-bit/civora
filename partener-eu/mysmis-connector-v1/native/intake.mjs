import { createHash, randomUUID } from "node:crypto";
import {
  copyFile,
  lstat,
  mkdir,
  open,
  readFile,
  rename,
  rm,
  stat,
  unlink,
  writeFile
} from "node:fs/promises";
import { createReadStream } from "node:fs";
import { basename, dirname, join, relative } from "node:path";
import { pipeline } from "node:stream/promises";
import { Transform } from "node:stream";
import { assertNoSensitivePersistence } from "../core/policy.mjs";
import { detectMagic, validateMime } from "./magic.mjs";

const INDEX_VERSION = 1;
const MAX_PREFIX_BYTES = 8192;

export class IntakeError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "IntakeError";
    this.code = code;
    this.details = details;
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function canonicalJson(value) {
  return JSON.stringify(canonicalize(value));
}

function digestText(value) {
  return createHash("sha256").update(value).digest("hex");
}

function normalizeMetadata(input = {}) {
  assertNoSensitivePersistence(input);
  const metadata = {
    projectCode: input.projectCode == null ? null : String(input.projectCode).slice(0, 64),
    track: input.track == null ? null : String(input.track).slice(0, 32),
    artifactKind: String(input.artifactKind || "OTHER").slice(0, 64),
    logicalName: String(input.logicalName || input.originalFilename || "unnamed-artifact").slice(0, 260),
    originalFilename: basename(String(input.originalFilename || input.logicalName || "download.bin")).slice(0, 260),
    sourceChannel: String(input.sourceChannel || "MANUAL_DOWNLOAD").slice(0, 64),
    browserDownloadId: Number.isInteger(input.browserDownloadId) ? input.browserDownloadId : null,
    declaredMime: input.declaredMime == null ? null : String(input.declaredMime).slice(0, 160),
    expectedBytes: Number.isSafeInteger(input.expectedBytes) && input.expectedBytes >= 0 ? input.expectedBytes : null,
    captureId: input.captureId == null ? null : String(input.captureId).slice(0, 160)
  };
  assertNoSensitivePersistence(metadata);
  return metadata;
}

async function hashFileAndReadPrefix(filePath) {
  const before = await stat(filePath, { bigint: true });
  const hash = createHash("sha256");
  const chunks = [];
  let captured = 0;
  const tap = new Transform({
    transform(chunk, _encoding, callback) {
      hash.update(chunk);
      if (captured < MAX_PREFIX_BYTES) {
        const remaining = MAX_PREFIX_BYTES - captured;
        const portion = chunk.subarray(0, remaining);
        chunks.push(portion);
        captured += portion.length;
      }
      callback(null, chunk);
    }
  });
  await pipeline(createReadStream(filePath), tap, new Transform({
    transform(_chunk, _encoding, callback) { callback(); }
  }));
  const after = await stat(filePath, { bigint: true });
  if (before.size !== after.size || before.mtimeNs !== after.mtimeNs) {
    throw new IntakeError("FILE_CHANGED_DURING_HASH", "Source changed while hashing; retry after download completion.");
  }
  return {
    sha256: hash.digest("hex"),
    size: Number(after.size),
    mtimeNs: after.mtimeNs.toString(),
    prefix: Buffer.concat(chunks)
  };
}

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw new IntakeError("CORRUPT_STATE_JSON", `Cannot parse state file ${basename(filePath)}.`, { cause: error.message });
  }
}

async function atomicWriteJson(filePath, value) {
  await mkdir(dirname(filePath), { recursive: true });
  const temporary = `${filePath}.tmp-${randomUUID()}`;
  const handle = await open(temporary, "wx", 0o600);
  try {
    await handle.writeFile(`${JSON.stringify(value, null, 2)}\n`, "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
  await rename(temporary, filePath);
}

async function withLock(spoolRoot, callback) {
  await mkdir(spoolRoot, { recursive: true });
  const lockPath = join(spoolRoot, ".intake.lock");
  let handle;
  try {
    handle = await open(lockPath, "wx", 0o600);
    await handle.writeFile(`${process.pid}\n`, "utf8");
  } catch (error) {
    if (error.code === "EEXIST") {
      throw new IntakeError("INTAKE_LOCKED", "Another intake transaction holds the spool lock.");
    }
    throw error;
  }
  try {
    return await callback();
  } finally {
    await handle.close();
    await unlink(lockPath).catch(() => {});
  }
}

function emptyIndex() {
  return { schemaVersion: INDEX_VERSION, objects: {}, records: {} };
}

function recordKey(metadata) {
  return digestText(canonicalJson({
    projectCode: metadata.projectCode,
    track: metadata.track,
    artifactKind: metadata.artifactKind,
    logicalName: metadata.logicalName
  }));
}

function classify(index, key, sha256) {
  const record = index.records[key];
  const objectExists = Boolean(index.objects[sha256]);
  if (!record) {
    return { classification: objectExists ? "DEDUP_SHARED_BYTES" : "NEW_ARTIFACT", version: 1 };
  }
  const existing = record.versions.find((version) => version.sha256 === sha256);
  if (existing) return { classification: "DUPLICATE_SAME_BYTES", version: existing.version };
  return { classification: objectExists ? "DEDUP_SHARED_BYTES_NEW_VERSION" : "NEW_VERSION", version: record.versions.length + 1 };
}

async function persistObject(sourcePath, objectPath, expectedSha) {
  await mkdir(dirname(objectPath), { recursive: true });
  try {
    const existing = await hashFileAndReadPrefix(objectPath);
    if (existing.sha256 !== expectedSha) {
      throw new IntakeError("SPOOL_OBJECT_HASH_CONFLICT", "Existing content-addressed object has the wrong hash.");
    }
    return "EXISTING_VERIFIED";
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }

  const temporary = `${objectPath}.tmp-${randomUUID()}`;
  await copyFile(sourcePath, temporary);
  const copied = await hashFileAndReadPrefix(temporary);
  if (copied.sha256 !== expectedSha) {
    await rm(temporary, { force: true });
    throw new IntakeError("COPY_HASH_MISMATCH", "Copied bytes do not match the source SHA-256.");
  }
  const handle = await open(temporary, "r");
  await handle.sync();
  await handle.close();
  try {
    await rename(temporary, objectPath);
  } catch (error) {
    await rm(temporary, { force: true });
    if (error.code !== "EEXIST") throw error;
  }
  return "CREATED_VERIFIED";
}

function applyPlan(index, plan, metadata, validation, objectRelativePath, observedAt) {
  if (!index.objects[validation.sha256]) {
    index.objects[validation.sha256] = {
      sha256: validation.sha256,
      size: validation.size,
      magicFamily: validation.magicFamily,
      detectedMime: validation.detectedMime,
      relativePath: objectRelativePath,
      firstSeenAt: observedAt
    };
  }
  if (!index.records[plan.recordKey]) {
    index.records[plan.recordKey] = {
      recordKey: plan.recordKey,
      projectCode: metadata.projectCode,
      track: metadata.track,
      artifactKind: metadata.artifactKind,
      logicalName: metadata.logicalName,
      versions: []
    };
  }
  const versions = index.records[plan.recordKey].versions;
  if (!versions.some((version) => version.sha256 === validation.sha256)) {
    versions.push({ version: plan.version, sha256: validation.sha256, observedAt });
    versions.sort((a, b) => a.version - b.version);
  }
  return index;
}

export async function validateManualDownload(sourcePath, metadataInput = {}) {
  const metadata = normalizeMetadata(metadataInput);
  const source = await lstat(sourcePath).catch((error) => {
    if (error.code === "ENOENT") throw new IntakeError("SOURCE_NOT_FOUND", "Manual download source does not exist.");
    throw error;
  });
  if (source.isSymbolicLink()) throw new IntakeError("SYMLINK_DENIED", "Symbolic link sources are denied.");
  if (!source.isFile()) throw new IntakeError("SOURCE_NOT_REGULAR_FILE", "Manual download source must be a regular file.");
  const hashed = await hashFileAndReadPrefix(sourcePath);
  const magic = detectMagic(hashed.prefix);
  const mime = validateMime({ magic, declaredMime: metadata.declaredMime, filename: metadata.originalFilename });
  const reasons = [...mime.reasons];
  if (metadata.expectedBytes != null && metadata.expectedBytes !== hashed.size) reasons.push("EXPECTED_SIZE_MISMATCH");
  const validation = {
    ok: reasons.length === 0,
    reasons: [...new Set(reasons)],
    sha256: hashed.sha256,
    size: hashed.size,
    sourceMtimeNs: hashed.mtimeNs,
    magicFamily: mime.magicFamily,
    detectedMime: mime.detectedMime,
    declaredMime: mime.declaredMime
  };
  return { metadata, validation };
}

export async function intakeManualDownload({
  sourcePath,
  spoolRoot,
  metadata: metadataInput = {},
  clock = () => new Date(),
  faultInjector = null
}) {
  if (!sourcePath || !spoolRoot) throw new IntakeError("ARGUMENT_REQUIRED", "sourcePath and spoolRoot are required.");
  const { metadata, validation } = await validateManualDownload(sourcePath, metadataInput);
  if (!validation.ok) {
    throw new IntakeError("VALIDATION_FAILED", "Manual download failed integrity validation.", validation);
  }

  return withLock(spoolRoot, async () => {
    const observedAt = clock().toISOString();
    const eventId = digestText(canonicalJson({ metadata, sha256: validation.sha256, size: validation.size }));
    const receiptPath = join(spoolRoot, "receipts", `${eventId}.json`);
    const existingReceipt = await readJson(receiptPath, null);
    if (existingReceipt) return { ...existingReceipt, replay: true };

    const checkpointPath = join(spoolRoot, "checkpoints", `${eventId}.json`);
    const indexPath = join(spoolRoot, "index.json");
    const objectRelativePath = join("objects", "sha256", validation.sha256.slice(0, 2), validation.sha256);
    const objectPath = join(spoolRoot, objectRelativePath);
    let checkpoint = await readJson(checkpointPath, null);
    let index = await readJson(indexPath, emptyIndex());
    if (index.schemaVersion !== INDEX_VERSION) {
      throw new IntakeError("INDEX_VERSION_UNSUPPORTED", `Expected index schema ${INDEX_VERSION}.`);
    }

    if (!checkpoint) {
      const key = recordKey(metadata);
      const decision = classify(index, key, validation.sha256);
      checkpoint = {
        schemaVersion: 1,
        eventId,
        phase: "PLANNED",
        plannedAt: observedAt,
        plan: { recordKey: key, ...decision },
        metadata,
        validation,
        objectRelativePath
      };
      await atomicWriteJson(checkpointPath, checkpoint);
    }

    const objectState = await persistObject(sourcePath, objectPath, validation.sha256);
    checkpoint.phase = "OBJECT_PERSISTED";
    checkpoint.objectState = objectState;
    await atomicWriteJson(checkpointPath, checkpoint);
    if (faultInjector) await faultInjector("OBJECT_PERSISTED");

    index = applyPlan(index, checkpoint.plan, metadata, validation, objectRelativePath, observedAt);
    await atomicWriteJson(indexPath, index);
    checkpoint.phase = "INDEX_COMMITTED";
    await atomicWriteJson(checkpointPath, checkpoint);
    if (faultInjector) await faultInjector("INDEX_COMMITTED");

    const receipt = {
      schemaVersion: 1,
      eventId,
      status: "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING",
      classification: checkpoint.plan.classification,
      version: checkpoint.plan.version,
      recordKey: checkpoint.plan.recordKey,
      sha256: validation.sha256,
      size: validation.size,
      magicFamily: validation.magicFamily,
      detectedMime: validation.detectedMime,
      objectRelativePath,
      originalFilename: metadata.originalFilename,
      projectCode: metadata.projectCode,
      track: metadata.track,
      artifactKind: metadata.artifactKind,
      logicalName: metadata.logicalName,
      sourceChannel: metadata.sourceChannel,
      committedAt: observedAt,
      replay: false,
      drive: { state: "PENDING_ADAPTER", fileId: null, readbackSha256: null },
      mysmis: { writes: 0, controlsClicked: 0 }
    };
    assertNoSensitivePersistence(receipt);
    await atomicWriteJson(receiptPath, receipt);
    checkpoint.phase = "COMMITTED";
    checkpoint.receiptRelativePath = relative(spoolRoot, receiptPath);
    await atomicWriteJson(checkpointPath, checkpoint);
    return receipt;
  });
}

export async function inspectSpool(spoolRoot) {
  const index = await readJson(join(spoolRoot, "index.json"), emptyIndex());
  return {
    schemaVersion: index.schemaVersion,
    objectCount: Object.keys(index.objects).length,
    recordCount: Object.keys(index.records).length,
    versionCount: Object.values(index.records).reduce((sum, record) => sum + record.versions.length, 0)
  };
}
