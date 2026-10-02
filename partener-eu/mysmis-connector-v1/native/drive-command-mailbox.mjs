import { createHash, randomUUID } from "node:crypto";
import {
  lstat,
  mkdir,
  open,
  readFile,
  readdir,
  rename,
  rm,
  writeFile
} from "node:fs/promises";
import path from "node:path";

import { assertNoSensitivePersistence } from "../core/policy.mjs";

const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const COMMAND_ID_PATTERN = /^[a-f0-9]{64}$/u;
const COMMAND_FILE_PATTERN = /^([a-f0-9]{64})\.command\.json$/u;
const FIXED_OPERATIONS = new Set(["HEALTH", "DISCOVER_ARTIFACTS"]);
const MAX_COMMAND_BYTES = 1024 * 1024;
const MAX_WINDOW_MS = 300_000;
const CLAIM_LEASE_MS = 120_000;
const DANGEROUS_KEYS = new Set([
  "argv",
  "arguments",
  "commandline",
  "eval",
  "executable",
  "javascript",
  "powershell",
  "script",
  "sourcecode"
]);

export const DRIVE_MAILBOX_LAYOUT = Object.freeze({
  inbox: "COMMAND_INBOX",
  processing: "PROCESSING",
  outbox: "RESULT_OUTBOX",
  archive: "ARCHIVE",
  state: "STATE"
});

export class DriveCommandMailboxError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "DriveCommandMailboxError";
    this.code = code;
    this.details = details;
  }
}

function normalizeKey(value) {
  return String(value).toLowerCase().replace(/[^a-z]/gu, "");
}

function assertNoExecutablePayload(value, currentPath = "root") {
  if (value == null) return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoExecutablePayload(item, `${currentPath}[${index}]`));
    return;
  }
  if (typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = normalizeKey(key);
    if (DANGEROUS_KEYS.has(normalized)) {
      throw new DriveCommandMailboxError(
        "MAILBOX_EXECUTABLE_PAYLOAD_DENIED",
        `Executable payload field denied at ${currentPath}.${key}.`
      );
    }
    if (normalized.includes("shell") && child !== false && child != null) {
      throw new DriveCommandMailboxError(
        "MAILBOX_REMOTE_SHELL_DENIED",
        `Shell field denied at ${currentPath}.${key}.`
      );
    }
    assertNoExecutablePayload(child, `${currentPath}.${key}`);
  }
}

function parseTime(value, code) {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) {
    throw new DriveCommandMailboxError(code, "Mailbox command timestamp is invalid.");
  }
  return milliseconds;
}

function identifyCommand(command) {
  if (command?.intent === "HEALTH_CHECK_ONLY") {
    return { operation: "HEALTH", commandId: command.challengeId };
  }
  return { operation: command?.operation, commandId: command?.commandId };
}

function assertMailboxSafety(command) {
  if (command?.restrictions?.readOnly !== true
    || command?.restrictions?.arbitraryShell !== false
    || command?.restrictions?.mysmisWrites !== 0
    || command?.restrictions?.controlsClicked !== 0) {
    throw new DriveCommandMailboxError(
      "MAILBOX_SAFETY_INVALID",
      "Mailbox commands must preserve read-only, zero-write, zero-click and no-shell restrictions."
    );
  }
  if (command.operation === "DISCOVER_ARTIFACTS"
    && (command.restrictions.routeMutations !== 0 || command.restrictions.cdpAttached !== false)) {
    throw new DriveCommandMailboxError(
      "MAILBOX_DISCOVERY_SAFETY_INVALID",
      "Discovery must preserve zero route mutations and no CDP attachment."
    );
  }
}

export function validateDriveMailboxCommand({ command, sourceHead, expectedCommandId, clock = () => new Date() }) {
  if (!BUILD_PATTERN.test(sourceHead)) {
    throw new DriveCommandMailboxError("MAILBOX_SOURCE_HEAD_INVALID", "Mailbox source head must be an exact Git SHA.");
  }
  try {
    assertNoSensitivePersistence(command);
  } catch (error) {
    throw new DriveCommandMailboxError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  assertNoExecutablePayload(command);
  const identity = identifyCommand(command);
  if (!FIXED_OPERATIONS.has(identity.operation)) {
    throw new DriveCommandMailboxError(
      "MAILBOX_OPERATION_DENIED",
      "Drive mailbox accepts only HEALTH and DISCOVER_ARTIFACTS."
    );
  }
  if (!COMMAND_ID_PATTERN.test(identity.commandId) || identity.commandId !== expectedCommandId) {
    throw new DriveCommandMailboxError(
      "MAILBOX_COMMAND_ID_MISMATCH",
      "Command identity must be lowercase SHA-256 and match the create-only filename."
    );
  }
  if (command.connectorBuildId !== sourceHead) {
    throw new DriveCommandMailboxError(
      "MAILBOX_BUILD_MISMATCH",
      "Mailbox command does not match the configured exact build."
    );
  }
  if (!COMMAND_ID_PATTERN.test(command.nonce)) {
    throw new DriveCommandMailboxError("MAILBOX_NONCE_INVALID", "Mailbox nonce must contain 32 random bytes.");
  }
  const issuedAt = parseTime(command.issuedAt, "MAILBOX_TIME_INVALID");
  const expiresAt = parseTime(command.expiresAt, "MAILBOX_TIME_INVALID");
  const now = clock().getTime();
  if (expiresAt <= issuedAt || expiresAt - issuedAt > MAX_WINDOW_MS || now < issuedAt || now > expiresAt) {
    throw new DriveCommandMailboxError(
      "MAILBOX_COMMAND_EXPIRED",
      "Mailbox command is expired, premature or outside the five-minute maximum window."
    );
  }
  assertMailboxSafety(command);
  return { ...identity, issuedAt, expiresAt };
}

function mailboxPaths(mailboxRoot) {
  if (typeof mailboxRoot !== "string" || mailboxRoot.length === 0 || !path.isAbsolute(mailboxRoot)) {
    throw new DriveCommandMailboxError(
      "MAILBOX_ROOT_INVALID",
      "Mailbox root must be an explicit absolute path inside a locally synced Drive folder."
    );
  }
  return Object.fromEntries(
    Object.entries(DRIVE_MAILBOX_LAYOUT).map(([key, folder]) => [key, path.join(mailboxRoot, folder)])
  );
}

export async function initializeDriveCommandMailbox(mailboxRoot) {
  const paths = mailboxPaths(mailboxRoot);
  for (const folder of Object.values(paths)) await mkdir(folder, { recursive: true });
  return paths;
}

async function readJsonRegularFile(filePath) {
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink()) {
    throw new DriveCommandMailboxError(
      "MAILBOX_FILE_TYPE_DENIED",
      "Mailbox commands and state must be regular files, never links or special files."
    );
  }
  if (info.size <= 0 || info.size > MAX_COMMAND_BYTES) {
    throw new DriveCommandMailboxError(
      "MAILBOX_FILE_SIZE_INVALID",
      "Mailbox command size must be between 1 byte and 1 MiB."
    );
  }
  let value;
  try {
    value = JSON.parse(await readFile(filePath, "utf8"));
  } catch {
    throw new DriveCommandMailboxError("MAILBOX_JSON_INVALID", "Mailbox file is not valid JSON.");
  }
  return value;
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function jsonBytes(value) {
  return `${JSON.stringify(canonicalize(value), null, 2)}\n`;
}

async function writeJsonCreateOnly(filePath, value) {
  assertNoSensitivePersistence(value);
  assertNoExecutablePayload(value);
  const handle = await open(filePath, "wx", 0o600);
  try {
    await handle.writeFile(jsonBytes(value), "utf8");
    await handle.sync();
  } finally {
    await handle.close();
  }
}

async function writeJsonAtomic(filePath, value) {
  assertNoSensitivePersistence(value);
  assertNoExecutablePayload(value);
  const temporary = `${filePath}.tmp-${randomUUID()}`;
  try {
    await writeFile(temporary, jsonBytes(value), { encoding: "utf8", mode: 0o600, flag: "wx" });
    await rename(temporary, filePath);
  } finally {
    await rm(temporary, { force: true });
  }
}

async function pathExists(filePath) {
  try {
    await lstat(filePath);
    return true;
  } catch (error) {
    if (error?.code === "ENOENT") return false;
    throw error;
  }
}

function safeErrorCode(error, fallback) {
  return typeof error?.code === "string" && /^[A-Z0-9_]{3,96}$/u.test(error.code) ? error.code : fallback;
}

function safetyReceipt() {
  return {
    readOnly: true,
    mysmisWrites: 0,
    controlsClicked: 0,
    routeMutations: 0,
    browserSecretsRead: false,
    arbitraryShell: false,
    publicPortOpened: false,
    childProcessesSpawned: 0
  };
}

async function archiveCommand(sourcePath, archivePath) {
  if (!await pathExists(archivePath)) {
    await rename(sourcePath, archivePath);
    return;
  }
  const [source, archived] = await Promise.all([readFile(sourcePath), readFile(archivePath)]);
  if (!source.equals(archived)) {
    throw new DriveCommandMailboxError(
      "MAILBOX_ARCHIVE_COLLISION",
      "Existing archive bytes differ for the same command identity."
    );
  }
  await rm(sourcePath);
}

async function emitRejected({ paths, commandId, operation = null, sourceHead, error, clock, executionAttempted }) {
  const rejectedAt = clock().toISOString();
  const receipt = {
    schemaVersion: 1,
    mailboxProtocolVersion: 1,
    status: "DRIVE_MAILBOX_COMMAND_REJECTED",
    commandId,
    operation,
    sourceHead,
    rejectedAt,
    errorCode: safeErrorCode(error, "MAILBOX_COMMAND_REJECTED"),
    executionAttempted,
    liveEvidenceAccepted: false,
    safety: safetyReceipt()
  };
  const receiptPath = path.join(paths.outbox, `${commandId}.failure.json`);
  if (!await pathExists(receiptPath)) await writeJsonCreateOnly(receiptPath, receipt);
  return { receipt, receiptPath };
}

async function processClaimedCommand({
  fileName,
  paths,
  sourceHead,
  dispatch,
  clock,
  claimLeaseMs
}) {
  const match = COMMAND_FILE_PATTERN.exec(fileName);
  if (!match) return { status: "IGNORED_UNRECOGNIZED_FILE", fileName };
  const commandId = match[1];
  const processingPath = path.join(paths.processing, fileName);
  const resultPath = path.join(paths.outbox, `${commandId}.result.json`);
  const failurePath = path.join(paths.outbox, `${commandId}.failure.json`);
  const claimPath = path.join(paths.state, `${commandId}.claim.json`);
  const archivePath = path.join(paths.archive, fileName);

  if (await pathExists(resultPath) || await pathExists(failurePath)) {
    await archiveCommand(processingPath, archivePath);
    return { status: "REPLAY_ALREADY_PERSISTED", commandId };
  }

  if (await pathExists(claimPath)) {
    const claim = await readJsonRegularFile(claimPath);
    if (claim.status === "COMMITTED" || claim.status === "REJECTED") {
      await archiveCommand(processingPath, archivePath);
      return { status: "REPLAY_ALREADY_CLAIMED", commandId };
    }
    const leaseUntil = Date.parse(claim.leaseUntil);
    if (claim.status === "DISPATCHING" && Number.isFinite(leaseUntil) && clock().getTime() <= leaseUntil) {
      return { status: "CLAIM_ACTIVE", commandId };
    }
    const error = new DriveCommandMailboxError(
      "MAILBOX_AMBIGUOUS_RESTART_REJECTED",
      "An interrupted dispatch cannot be replayed safely after its lease expires."
    );
    const { receipt } = await emitRejected({
      paths,
      commandId,
      sourceHead,
      error,
      clock,
      executionAttempted: true
    });
    await writeJsonAtomic(claimPath, {
      ...claim,
      status: "REJECTED",
      rejectedAt: receipt.rejectedAt,
      errorCode: receipt.errorCode
    });
    await archiveCommand(processingPath, archivePath);
    return { status: receipt.status, commandId, errorCode: receipt.errorCode };
  }

  let command;
  let identity;
  try {
    command = await readJsonRegularFile(processingPath);
    identity = validateDriveMailboxCommand({ command, sourceHead, expectedCommandId: commandId, clock });
  } catch (error) {
    const { receipt } = await emitRejected({
      paths,
      commandId,
      sourceHead,
      error,
      clock,
      executionAttempted: false
    });
    await archiveCommand(processingPath, archivePath);
    return { status: receipt.status, commandId, errorCode: receipt.errorCode };
  }

  const claimedAt = clock().toISOString();
  const claim = {
    schemaVersion: 1,
    status: "DISPATCHING",
    commandId,
    operation: identity.operation,
    sourceHead,
    claimedAt,
    leaseUntil: new Date(clock().getTime() + claimLeaseMs).toISOString()
  };
  try {
    await writeJsonCreateOnly(claimPath, claim);
  } catch (error) {
    if (error?.code === "EEXIST") return { status: "CLAIM_RACE_LOST", commandId };
    throw error;
  }

  try {
    const response = await dispatch(command);
    assertNoSensitivePersistence(response);
    assertNoExecutablePayload(response);
    const completedAt = clock().toISOString();
    const result = {
      schemaVersion: 1,
      mailboxProtocolVersion: 1,
      status: "DRIVE_MAILBOX_COMMAND_COMPLETED",
      commandId,
      operation: identity.operation,
      sourceHead,
      claimedAt,
      completedAt,
      observationClass: "LOCAL_MCLENOVO_DRIVE_MAILBOX",
      liveEvidenceAccepted: false,
      liveEvidenceGate: "REQUIRES_DRIVE_READBACK_AND_PROTOCOL_VALIDATION",
      response,
      safety: safetyReceipt()
    };
    await writeJsonCreateOnly(resultPath, result);
    await writeJsonAtomic(claimPath, { ...claim, status: "COMMITTED", completedAt, resultFile: path.basename(resultPath) });
    await archiveCommand(processingPath, archivePath);
    return { status: result.status, commandId, operation: identity.operation };
  } catch (error) {
    const { receipt } = await emitRejected({
      paths,
      commandId,
      operation: identity.operation,
      sourceHead,
      error,
      clock,
      executionAttempted: true
    });
    await writeJsonAtomic(claimPath, {
      ...claim,
      status: "REJECTED",
      rejectedAt: receipt.rejectedAt,
      errorCode: receipt.errorCode
    });
    await archiveCommand(processingPath, archivePath);
    return { status: receipt.status, commandId, operation: identity.operation, errorCode: receipt.errorCode };
  }
}

export async function runDriveCommandMailboxCycle({
  mailboxRoot,
  sourceHead,
  dispatch,
  clock = () => new Date(),
  maxCommands = 25,
  claimLeaseMs = CLAIM_LEASE_MS
}) {
  if (!BUILD_PATTERN.test(sourceHead)) {
    throw new DriveCommandMailboxError("MAILBOX_SOURCE_HEAD_INVALID", "Mailbox source head must be an exact Git SHA.");
  }
  if (typeof dispatch !== "function") {
    throw new DriveCommandMailboxError(
      "MAILBOX_EXECUTOR_NOT_BOUND",
      "An attested fixed dispatcher must be injected; arbitrary modules and commands are not supported."
    );
  }
  if (!Number.isSafeInteger(maxCommands) || maxCommands < 1 || maxCommands > 100) {
    throw new DriveCommandMailboxError("MAILBOX_BATCH_INVALID", "Mailbox cycle batch must be between 1 and 100 commands.");
  }
  if (!Number.isSafeInteger(claimLeaseMs) || claimLeaseMs < 10_000 || claimLeaseMs > MAX_WINDOW_MS) {
    throw new DriveCommandMailboxError("MAILBOX_LEASE_INVALID", "Mailbox claim lease must be between 10 and 300 seconds.");
  }
  const paths = await initializeDriveCommandMailbox(mailboxRoot);
  const inboxNames = (await readdir(paths.inbox)).filter((name) => COMMAND_FILE_PATTERN.test(name)).sort();
  for (const name of inboxNames.slice(0, maxCommands)) {
    try {
      await rename(path.join(paths.inbox, name), path.join(paths.processing, name));
    } catch (error) {
      if (error?.code !== "ENOENT") throw error;
    }
  }
  const processingNames = (await readdir(paths.processing))
    .filter((name) => COMMAND_FILE_PATTERN.test(name))
    .sort()
    .slice(0, maxCommands);
  const outcomes = [];
  for (const fileName of processingNames) {
    outcomes.push(await processClaimedCommand({
      fileName,
      paths,
      sourceHead,
      dispatch,
      clock,
      claimLeaseMs
    }));
  }
  return {
    schemaVersion: 1,
    status: "DRIVE_MAILBOX_CYCLE_COMPLETED",
    sourceHead,
    processedAt: clock().toISOString(),
    outcomes,
    safety: safetyReceipt()
  };
}

export function startDriveCommandMailboxPoller({
  mailboxRoot,
  sourceHead,
  dispatch,
  clock = () => new Date(),
  pollIntervalMs = 5_000,
  onCycle = () => {},
  onError = () => {}
}) {
  if (!Number.isSafeInteger(pollIntervalMs) || pollIntervalMs < 1_000 || pollIntervalMs > 60_000) {
    throw new DriveCommandMailboxError(
      "MAILBOX_POLL_INTERVAL_INVALID",
      "Mailbox polling interval must be between one and sixty seconds."
    );
  }
  if (typeof dispatch !== "function") {
    throw new DriveCommandMailboxError(
      "MAILBOX_EXECUTOR_NOT_BOUND",
      "Poller requires the attested fixed dispatcher before it can start."
    );
  }
  let stopped = false;
  let timer = null;
  const tick = async () => {
    if (stopped) return;
    try {
      const receipt = await runDriveCommandMailboxCycle({ mailboxRoot, sourceHead, dispatch, clock });
      await onCycle(receipt);
    } catch (error) {
      await onError(error);
    }
    if (!stopped) timer = setTimeout(tick, pollIntervalMs);
  };
  timer = setTimeout(tick, 0);
  return {
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
    }
  };
}

export function mailboxCommandFileName(command) {
  const { commandId } = identifyCommand(command);
  if (!COMMAND_ID_PATTERN.test(commandId)) {
    throw new DriveCommandMailboxError("MAILBOX_COMMAND_ID_INVALID", "Command identifier is not a SHA-256 value.");
  }
  return `${commandId}.command.json`;
}

export function hashMailboxBytes(bytes) {
  return createHash("sha256").update(bytes).digest("hex");
}
