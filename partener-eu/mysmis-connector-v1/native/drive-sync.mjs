import { createHash, randomUUID } from "node:crypto";
import { createReadStream } from "node:fs";
import { lstat, mkdir, open, readFile, rename, unlink } from "node:fs/promises";
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { assertNoSensitivePersistence } from "../core/policy.mjs";

const SYNC_SCHEMA_VERSION = 1;
const TRACK_TARGETS = Object.freeze({
  WRITING: Object.freeze({
    artifactRegistry: "WRITING_ARTIFACT_REGISTRY",
    ssot: "WRITING_SSOT"
  }),
  IMPLEMENTATION: Object.freeze({
    artifactRegistry: "IMPLEMENTATION_ARTIFACT_REGISTRY",
    ssot: "IMPLEMENTATION_SSOT"
  })
});

export class DriveSyncError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "DriveSyncError";
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

function digest(value) {
  return createHash("sha256").update(JSON.stringify(canonicalize(value))).digest("hex");
}

async function readJson(filePath, fallback) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw new DriveSyncError("CORRUPT_DRIVE_SYNC_STATE", `Cannot parse ${basename(filePath)}.`, {
      cause: error.message
    });
  }
}

async function atomicWriteJson(filePath, value) {
  assertNoSensitivePersistence(value);
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
  const syncRoot = join(spoolRoot, "drive-sync");
  await mkdir(syncRoot, { recursive: true });
  const lockPath = join(syncRoot, ".sync.lock");
  let handle;
  try {
    handle = await open(lockPath, "wx", 0o600);
    await handle.writeFile(`${process.pid}\n`, "utf8");
  } catch (error) {
    if (error.code === "EEXIST") {
      throw new DriveSyncError("DRIVE_SYNC_LOCKED", "Another Drive sync transaction holds the spool lock.");
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

function assertReceipt(receipt) {
  assertNoSensitivePersistence(receipt);
  if (!receipt || receipt.status !== "LOCAL_INTAKE_COMMITTED_DRIVE_PENDING") {
    throw new DriveSyncError("LOCAL_RECEIPT_REQUIRED", "A committed, Drive-pending local intake receipt is required.");
  }
  for (const field of ["eventId", "sha256", "objectRelativePath", "recordKey"]) {
    if (typeof receipt[field] !== "string" || !receipt[field]) {
      throw new DriveSyncError("LOCAL_RECEIPT_INVALID", `Local receipt is missing ${field}.`);
    }
  }
  if (!/^[a-f0-9]{64}$/u.test(receipt.sha256) || !Number.isSafeInteger(receipt.size) || receipt.size < 0) {
    throw new DriveSyncError("LOCAL_RECEIPT_INVALID", "Local receipt hash or size is invalid.");
  }
  if (!TRACK_TARGETS[receipt.track]) {
    throw new DriveSyncError("TRACK_UNSUPPORTED", "Drive reconciliation requires WRITING or IMPLEMENTATION track.");
  }
  if (receipt.mysmis?.writes !== 0 || receipt.mysmis?.controlsClicked !== 0) {
    throw new DriveSyncError("MYSMIS_ZERO_WRITE_EVIDENCE_REQUIRED", "Local receipt does not prove zero MySMIS writes.");
  }
}

function objectPathInsideSpool(spoolRoot, objectRelativePath) {
  if (isAbsolute(objectRelativePath)) {
    throw new DriveSyncError("OBJECT_PATH_OUTSIDE_SPOOL", "Content object path must be relative to the spool.");
  }
  const root = resolve(spoolRoot);
  const objectPath = resolve(root, objectRelativePath);
  if (objectPath !== root && !objectPath.startsWith(`${root}${sep}`)) {
    throw new DriveSyncError("OBJECT_PATH_OUTSIDE_SPOOL", "Content object path escapes the spool.");
  }
  return objectPath;
}

async function hashIterable(iterable) {
  const hash = createHash("sha256");
  let size = 0;
  for await (const value of iterable) {
    const chunk = Buffer.isBuffer(value) ? value : Buffer.from(value);
    hash.update(chunk);
    size += chunk.length;
  }
  return { sha256: hash.digest("hex"), size };
}

async function hashFile(filePath) {
  const source = await lstat(filePath).catch((error) => {
    if (error.code === "ENOENT") {
      throw new DriveSyncError("SPOOL_OBJECT_MISSING", "The committed content object is missing.");
    }
    throw error;
  });
  if (source.isSymbolicLink() || !source.isFile()) {
    throw new DriveSyncError("SPOOL_OBJECT_NOT_REGULAR_FILE", "The committed content object must be a regular file.");
  }
  return hashIterable(createReadStream(filePath));
}

async function hashReadback(value) {
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) {
    return hashIterable([value]);
  }
  if (value instanceof ArrayBuffer) return hashIterable([new Uint8Array(value)]);
  if (value && typeof value[Symbol.asyncIterator] === "function") return hashIterable(value);
  if (value && typeof value[Symbol.iterator] === "function" && typeof value !== "string") {
    return hashIterable(value);
  }
  throw new DriveSyncError("DRIVE_READBACK_INVALID", "Drive adapter must return raw bytes or a byte stream.");
}

function uploadExtension(receipt) {
  const fromOriginal = extname(receipt.originalFilename || "").toLowerCase();
  if (/^\.[a-z0-9]{1,10}$/u.test(fromOriginal)) return fromOriginal;
  const byMime = {
    "application/pdf": ".pdf",
    "application/zip": ".zip",
    "application/json": ".json",
    "image/png": ".png",
    "image/jpeg": ".jpg"
  };
  return byMime[receipt.detectedMime] || ".bin";
}

function normalizeUploadResponse(response) {
  try {
    assertNoSensitivePersistence(response);
  } catch (error) {
    throw new DriveSyncError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  if (!response || typeof response.fileId !== "string" || !response.fileId.trim()) {
    throw new DriveSyncError("DRIVE_UPLOAD_RESPONSE_INVALID", "Drive create-only upload did not return a file ID.");
  }
  let url = null;
  if (response.url != null) {
    try {
      const parsed = new URL(String(response.url));
      if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.search || parsed.hash) {
        throw new Error("unsafe-url");
      }
      url = parsed.toString();
    } catch {
      throw new DriveSyncError("DRIVE_UPLOAD_RESPONSE_INVALID", "Drive URL must be a credential-free HTTPS URL.");
    }
  }
  return {
    fileId: response.fileId.trim().slice(0, 512),
    url,
    createdNew: response.createdNew !== false
  };
}

function buildProposal({ receipt, drive, syncId, proposedAt }) {
  const targets = TRACK_TARGETS[receipt.track];
  return {
    schemaVersion: SYNC_SCHEMA_VERSION,
    proposalId: `drive-${syncId}`,
    operation: "APPEND_ONLY_PROPOSAL",
    approvalState: "PENDING_HUMAN_REVIEW",
    evidenceState: "DRIVE_READBACK_VERIFIED",
    proposedAt,
    track: receipt.track,
    projectCode: receipt.projectCode,
    promoteProjectFacts: false,
    artifactRegistryAppend: {
      target: targets.artifactRegistry,
      mode: "APPEND_ONLY",
      artifact: {
        recordKey: receipt.recordKey,
        artifactKind: receipt.artifactKind,
        logicalName: receipt.logicalName,
        originalFilename: receipt.originalFilename,
        version: receipt.version,
        classification: receipt.classification,
        sha256: receipt.sha256,
        size: receipt.size,
        detectedMime: receipt.detectedMime,
        driveFileId: drive.fileId,
        driveUrl: drive.url,
        driveReadbackSha256: drive.readbackSha256
      }
    },
    ssotReconciliation: {
      target: targets.ssot,
      action: "PROPOSE_ARTIFACT_LINK_ONLY",
      factPromotion: false,
      artifactRecordKey: receipt.recordKey,
      driveFileId: drive.fileId,
      sha256: receipt.sha256
    },
    safety: {
      mysmisWrites: 0,
      controlsClicked: 0,
      registryMutations: 0,
      ssotMutations: 0
    }
  };
}

async function recordFailure(checkpointPath, checkpoint, error, clock) {
  checkpoint.lastFailure = {
    code: error.code || "DRIVE_SYNC_FAILED",
    recordedAt: clock().toISOString()
  };
  await atomicWriteJson(checkpointPath, checkpoint);
}

export async function syncCommittedObjectToDrive({
  receipt,
  spoolRoot,
  adapter,
  clock = () => new Date(),
  faultInjector = null
}) {
  if (!spoolRoot || !adapter) {
    throw new DriveSyncError("ARGUMENT_REQUIRED", "spoolRoot and adapter are required.");
  }
  assertReceipt(receipt);
  if (typeof adapter.uploadCreateOnly !== "function" || typeof adapter.downloadRaw !== "function") {
    throw new DriveSyncError("DRIVE_ADAPTER_INVALID", "Adapter requires uploadCreateOnly and downloadRaw methods.");
  }

  const objectPath = objectPathInsideSpool(spoolRoot, receipt.objectRelativePath);
  const localIntegrity = await hashFile(objectPath);
  if (localIntegrity.sha256 !== receipt.sha256 || localIntegrity.size !== receipt.size) {
    throw new DriveSyncError("SPOOL_OBJECT_INTEGRITY_MISMATCH", "Content object no longer matches its committed receipt.", {
      expectedSha256: receipt.sha256,
      expectedSize: receipt.size,
      actualSha256: localIntegrity.sha256,
      actualSize: localIntegrity.size
    });
  }

  return withLock(spoolRoot, async () => {
    const syncId = digest({ eventId: receipt.eventId, sha256: receipt.sha256, target: receipt.track });
    const syncRoot = join(spoolRoot, "drive-sync");
    const checkpointPath = join(syncRoot, "checkpoints", `${syncId}.json`);
    const receiptPath = join(syncRoot, "receipts", `${syncId}.json`);
    const proposalPath = join(syncRoot, "proposals", `${syncId}.json`);
    const existing = await readJson(receiptPath, null);
    if (existing) return { ...existing, replay: true };

    let checkpoint = await readJson(checkpointPath, null);
    if (!checkpoint) {
      checkpoint = {
        schemaVersion: SYNC_SCHEMA_VERSION,
        syncId,
        eventId: receipt.eventId,
        phase: "PLANNED",
        plannedAt: clock().toISOString(),
        track: receipt.track,
        projectCode: receipt.projectCode,
        recordKey: receipt.recordKey,
        sha256: receipt.sha256,
        size: receipt.size,
        objectRelativePath: receipt.objectRelativePath,
        uploadName: `${receipt.sha256}${uploadExtension(receipt)}`
      };
      await atomicWriteJson(checkpointPath, checkpoint);
    }
    if (checkpoint.schemaVersion !== SYNC_SCHEMA_VERSION
      || checkpoint.eventId !== receipt.eventId
      || checkpoint.sha256 !== receipt.sha256
      || checkpoint.size !== receipt.size
      || checkpoint.track !== receipt.track) {
      throw new DriveSyncError("DRIVE_SYNC_CHECKPOINT_CONFLICT", "Drive sync checkpoint conflicts with the local receipt.");
    }

    if (checkpoint.phase === "PLANNED") {
      let response;
      try {
        response = await adapter.uploadCreateOnly({
          localPath: objectPath,
          fileName: checkpoint.uploadName,
          mimeType: receipt.detectedMime,
          createOnly: true,
          contentKey: receipt.sha256,
          metadata: {
            sha256: receipt.sha256,
            size: receipt.size,
            sourceEventId: receipt.eventId,
            track: receipt.track
          }
        });
        checkpoint.drive = normalizeUploadResponse(response);
        checkpoint.phase = "UPLOADED";
        checkpoint.uploadedAt = clock().toISOString();
        delete checkpoint.lastFailure;
        await atomicWriteJson(checkpointPath, checkpoint);
      } catch (error) {
        const safeError = error instanceof DriveSyncError
          ? error
          : new DriveSyncError("DRIVE_UPLOAD_FAILED", "Drive create-only upload failed.");
        await recordFailure(checkpointPath, checkpoint, safeError, clock);
        throw safeError;
      }
      if (faultInjector) await faultInjector("UPLOADED", checkpoint.drive);
    }

    if (checkpoint.phase === "UPLOADED") {
      try {
        const raw = await adapter.downloadRaw({ fileId: checkpoint.drive.fileId });
        const readback = await hashReadback(raw);
        if (readback.sha256 !== receipt.sha256 || readback.size !== receipt.size) {
          throw new DriveSyncError("DRIVE_READBACK_INTEGRITY_MISMATCH", "Drive readback does not match the committed object.", {
            expectedSha256: receipt.sha256,
            expectedSize: receipt.size,
            actualSha256: readback.sha256,
            actualSize: readback.size
          });
        }
        checkpoint.drive.readbackSha256 = readback.sha256;
        checkpoint.drive.readbackSize = readback.size;
        checkpoint.phase = "READBACK_VERIFIED";
        checkpoint.readbackVerifiedAt = clock().toISOString();
        delete checkpoint.lastFailure;
        await atomicWriteJson(checkpointPath, checkpoint);
      } catch (error) {
        const safeError = error instanceof DriveSyncError
          ? error
          : new DriveSyncError("DRIVE_READBACK_FAILED", "Drive raw readback failed.");
        await recordFailure(checkpointPath, checkpoint, safeError, clock);
        throw safeError;
      }
      if (faultInjector) await faultInjector("READBACK_VERIFIED", checkpoint.drive);
    }

    if (checkpoint.phase === "READBACK_VERIFIED") {
      const proposedAt = clock().toISOString();
      const proposal = buildProposal({ receipt, drive: checkpoint.drive, syncId, proposedAt });
      await atomicWriteJson(proposalPath, proposal);
      checkpoint.phase = "PROPOSAL_PERSISTED";
      checkpoint.proposalRelativePath = relative(spoolRoot, proposalPath);
      await atomicWriteJson(checkpointPath, checkpoint);
      if (faultInjector) await faultInjector("PROPOSAL_PERSISTED", proposal);
    }

    const completedAt = clock().toISOString();
    const syncReceipt = {
      schemaVersion: SYNC_SCHEMA_VERSION,
      syncId,
      sourceEventId: receipt.eventId,
      status: "DRIVE_PERSISTED_RECONCILIATION_PENDING",
      track: receipt.track,
      projectCode: receipt.projectCode,
      recordKey: receipt.recordKey,
      artifactKind: receipt.artifactKind,
      logicalName: receipt.logicalName,
      version: receipt.version,
      sha256: receipt.sha256,
      size: receipt.size,
      drive: {
        state: "READBACK_VERIFIED",
        fileId: checkpoint.drive.fileId,
        url: checkpoint.drive.url,
        uploadName: checkpoint.uploadName,
        readbackSha256: checkpoint.drive.readbackSha256,
        readbackSize: checkpoint.drive.readbackSize
      },
      proposalRelativePath: checkpoint.proposalRelativePath,
      reconciliation: {
        state: "PENDING_HUMAN_REVIEW",
        promoteProjectFacts: false,
        mutationsApplied: 0
      },
      mysmis: { writes: 0, controlsClicked: 0 },
      completedAt,
      replay: false
    };
    await atomicWriteJson(receiptPath, syncReceipt);
    checkpoint.phase = "COMMITTED";
    checkpoint.receiptRelativePath = relative(spoolRoot, receiptPath);
    await atomicWriteJson(checkpointPath, checkpoint);
    return syncReceipt;
  });
}
