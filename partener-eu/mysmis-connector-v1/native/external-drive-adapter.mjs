import { randomUUID } from "node:crypto";
import { mkdir, open, readFile, rename } from "node:fs/promises";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";
import { assertNoSensitivePersistence } from "../core/policy.mjs";
import { DriveSyncError } from "./drive-sync.mjs";

const EXCHANGE_SCHEMA_VERSION = 1;

async function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(await readFile(filePath, "utf8"));
  } catch (error) {
    if (error.code === "ENOENT") return fallback;
    throw new DriveSyncError("EXTERNAL_DRIVE_RESPONSE_INVALID", "External Drive exchange JSON is invalid.");
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

function relativeObjectPath(spoolRoot, localPath) {
  const root = resolve(spoolRoot);
  const absolute = resolve(localPath);
  if (absolute !== root && !absolute.startsWith(`${root}${sep}`)) {
    throw new DriveSyncError("EXTERNAL_DRIVE_OBJECT_OUTSIDE_SPOOL", "Upload object must remain inside the spool.");
  }
  const value = relative(root, absolute);
  if (!value || isAbsolute(value) || value.startsWith(`..${sep}`) || value === "..") {
    throw new DriveSyncError("EXTERNAL_DRIVE_OBJECT_OUTSIDE_SPOOL", "Upload object path is invalid.");
  }
  return value;
}

function decodeBase64(value) {
  if (typeof value !== "string" || value.length === 0 || value.length % 4 !== 0
    || !/^[A-Za-z0-9+/]*={0,2}$/u.test(value)) {
    throw new DriveSyncError("EXTERNAL_DRIVE_READBACK_INVALID", "External response must contain canonical base64 readback bytes.");
  }
  const bytes = Buffer.from(value, "base64");
  if (bytes.toString("base64") !== value) {
    throw new DriveSyncError("EXTERNAL_DRIVE_READBACK_INVALID", "External readback base64 is not canonical.");
  }
  return bytes;
}

function assertSafeResponse(response, contentKey) {
  try {
    assertNoSensitivePersistence(response);
  } catch (error) {
    throw new DriveSyncError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  if (!response || response.schemaVersion !== EXCHANGE_SCHEMA_VERSION
    || response.state !== "UPLOAD_AND_READBACK_COMPLETE"
    || response.contentKey !== contentKey
    || typeof response.fileId !== "string"
    || !response.fileId) {
    throw new DriveSyncError("EXTERNAL_DRIVE_RESPONSE_INVALID", "External Drive response does not match its upload request.");
  }
}

export function createExternalDriveExchangeAdapter({
  spoolRoot,
  exchangeRoot,
  clock = () => new Date()
}) {
  if (!spoolRoot || !exchangeRoot) {
    throw new DriveSyncError("ARGUMENT_REQUIRED", "spoolRoot and exchangeRoot are required.");
  }
  const readbacks = new Map();

  return {
    async uploadCreateOnly(request) {
      assertNoSensitivePersistence(request.metadata);
      if (request.createOnly !== true || request.contentKey !== request.metadata?.sha256
        || !/^[a-f0-9]{64}$/u.test(request.contentKey)
        || !Number.isSafeInteger(request.metadata?.size)
        || request.metadata.size < 0) {
        throw new DriveSyncError("EXTERNAL_DRIVE_REQUEST_INVALID", "External upload must be create-only and content-addressed.");
      }

      const requestPath = join(exchangeRoot, "requests", `${request.contentKey}.json`);
      const responsePath = join(exchangeRoot, "responses", `${request.contentKey}.json`);
      const existingPlan = await readJson(requestPath);
      const plan = {
        schemaVersion: EXCHANGE_SCHEMA_VERSION,
        requestId: `drive-upload-${request.contentKey}`,
        state: "PENDING_EXTERNAL_DRIVE",
        createdAt: existingPlan?.createdAt || clock().toISOString(),
        operation: "CREATE_NEW_FILE_AND_RETURN_COMPLETE_RAW_READBACK",
        createOnly: true,
        contentKey: request.contentKey,
        sha256: request.metadata.sha256,
        size: request.metadata.size,
        fileName: request.fileName,
        mimeType: request.mimeType,
        spoolObjectRelativePath: relativeObjectPath(spoolRoot, request.localPath),
        sourceEventId: request.metadata.sourceEventId,
        track: request.metadata.track,
        requiredResponse: {
          schemaVersion: EXCHANGE_SCHEMA_VERSION,
          state: "UPLOAD_AND_READBACK_COMPLETE",
          contentKey: request.contentKey,
          fileId: "OBSERVED_DRIVE_FILE_ID",
          url: "OBSERVED_CREDENTIAL_FREE_HTTPS_URL",
          createdNew: true,
          readbackBase64: "COMPLETE_RAW_BYTES_BASE64"
        },
        safety: {
          mysmisWrites: 0,
          registryMutations: 0,
          ssotMutations: 0
        }
      };
      if (existingPlan && JSON.stringify(existingPlan) !== JSON.stringify(plan)) {
        throw new DriveSyncError("EXTERNAL_DRIVE_REQUEST_CONFLICT", "Existing external Drive request conflicts with the current plan.");
      }
      if (!existingPlan) await atomicWriteJson(requestPath, plan);

      const response = await readJson(responsePath);
      if (!response) {
        throw new DriveSyncError("EXTERNAL_DRIVE_UPLOAD_PENDING", "External Drive upload and raw readback are pending.", {
          requestRelativePath: relative(spoolRoot, requestPath),
          responseRelativePath: relative(spoolRoot, responsePath),
          contentKey: request.contentKey
        });
      }
      assertSafeResponse(response, request.contentKey);
      const raw = decodeBase64(response.readbackBase64);
      readbacks.set(response.fileId, raw);
      return {
        fileId: response.fileId,
        url: response.url,
        createdNew: response.createdNew !== false
      };
    },

    async downloadRaw({ fileId }) {
      if (!readbacks.has(fileId)) {
        throw new DriveSyncError("EXTERNAL_DRIVE_READBACK_MISSING", "No verified external readback is bound to this Drive file ID.");
      }
      return readbacks.get(fileId);
    }
  };
}
