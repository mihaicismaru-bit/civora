import { createHash } from "node:crypto";

const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$/u;
const SHA256 = /^[a-f0-9]{64}$/u;
const GIT_SHA = /^[a-f0-9]{40}$/u;
const ALLOWED_OPERATIONS = Object.freeze([
  "LOAD_UNPACKED_EXTENSION",
  "RUN_LIVE_HEALTH",
  "START_LOCAL_AGENT"
]);
const AUTHORIZATION_KEYS = new Set([
  "schemaVersion", "status", "authorizationId", "approvalEvidenceRef", "machineAlias",
  "sourceHead", "pairId", "manifestDigest", "attemptId", "operations", "controls",
  "issuedAt", "expiresAt", "authorizationDigest"
]);
const CONTROL_KEYS = new Set([
  "operatorPresenceRequired", "browserInstallation", "localAgentStart",
  "nativeMessagingEnabled", "mysmisAccessAllowed", "mysmisWritesAllowed",
  "remoteShellAllowed", "credentialAccessAllowed"
]);
const OBSERVATION_COMMON_KEYS = [
  "schemaVersion", "event", "observationClass", "observationId", "sourceHead", "pairId",
  "manifestDigest", "attemptId", "nativeMessagingEnabled", "mysmisAccessPerformed",
  "mysmisWrites", "remoteShellUsed", "credentialAccessPerformed"
];

export class InstallAuthorizationError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "InstallAuthorizationError";
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

function assertExactKeys(value, allowed, code) {
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).some((key) => !allowed.has(key))
    || [...allowed].some((key) => !Object.hasOwn(value, key))) {
    throw new InstallAuthorizationError(code, "Record shape does not match the bounded contract.");
  }
}

function parseTime(value, code) {
  const time = Date.parse(value);
  if (!Number.isFinite(time)) throw new InstallAuthorizationError(code, "Authorization timestamps must be valid ISO dates.");
  return time;
}

function assertPreflight(receipt) {
  if (!receipt
    || receipt.schemaVersion !== 1
    || receipt.status !== "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED"
    || !GIT_SHA.test(receipt.sourceHead)
    || !SHA256.test(receipt.pairId)
    || !SHA256.test(receipt.manifestDigest)
    || !SAFE_ID.test(receipt.attemptId)
    || receipt.installState !== "NOT_STARTED"
    || receipt.rollbackState !== "NOT_REQUIRED"
    || receipt.browserInstallationPerformed !== false
    || receipt.nativeMessagingEnabled !== false
    || receipt.mysmisAccessPerformed !== false
    || receipt.mysmisWrites !== 0
    || receipt.liveEvidenceClaimed !== false) {
    throw new InstallAuthorizationError("INSTALL_AUTH_PREFLIGHT_INVALID", "A complete no-install preflight receipt is required.");
  }
}

function authorizationCore(authorization) {
  const { authorizationDigest: _ignored, ...core } = authorization;
  return core;
}

export function computeInstallationAuthorizationDigest(authorization) {
  return digest(authorizationCore(authorization));
}

export function validateInstallationAuthorization({ preflightReceipt, authorization, clock = () => new Date() }) {
  assertPreflight(preflightReceipt);
  assertExactKeys(authorization, AUTHORIZATION_KEYS, "INSTALL_AUTH_RECORD_INVALID");
  if (!authorization
    || authorization.schemaVersion !== 1
    || authorization.status !== "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL"
    || !SAFE_ID.test(authorization.authorizationId)
    || !SAFE_ID.test(authorization.approvalEvidenceRef)
    || authorization.machineAlias !== "MCLENOVO") {
    throw new InstallAuthorizationError("INSTALL_AUTH_RECORD_INVALID", "A bounded external authorization record is required.");
  }
  if (authorization.sourceHead !== preflightReceipt.sourceHead
    || authorization.pairId !== preflightReceipt.pairId
    || authorization.manifestDigest !== preflightReceipt.manifestDigest
    || authorization.attemptId !== preflightReceipt.attemptId) {
    throw new InstallAuthorizationError("INSTALL_AUTH_BINDING_MISMATCH", "Authorization must bind the exact preflight build and attempt.");
  }
  const operations = [...(authorization.operations || [])].sort();
  if (JSON.stringify(operations) !== JSON.stringify([...ALLOWED_OPERATIONS].sort())) {
    throw new InstallAuthorizationError("INSTALL_AUTH_SCOPE_INVALID", "Authorization operations must match the bounded allowlist exactly.");
  }
  const controls = authorization.controls;
  assertExactKeys(controls, CONTROL_KEYS, "INSTALL_AUTH_CONTROLS_INVALID");
  if (!controls
    || controls.operatorPresenceRequired !== true
    || controls.browserInstallation !== "MANUAL_BOUNDED"
    || controls.localAgentStart !== "MANUAL_BOUNDED"
    || controls.nativeMessagingEnabled !== false
    || controls.mysmisAccessAllowed !== false
    || controls.mysmisWritesAllowed !== 0
    || controls.remoteShellAllowed !== false
    || controls.credentialAccessAllowed !== false) {
    throw new InstallAuthorizationError("INSTALL_AUTH_CONTROLS_INVALID", "Authorization must preserve bounded manual, no-access and zero-write controls.");
  }
  const issuedAt = parseTime(authorization.issuedAt, "INSTALL_AUTH_TIME_INVALID");
  const expiresAt = parseTime(authorization.expiresAt, "INSTALL_AUTH_TIME_INVALID");
  const now = clock().getTime();
  if (issuedAt > now + 30_000 || expiresAt <= now || expiresAt <= issuedAt || expiresAt - issuedAt > 30 * 60_000) {
    throw new InstallAuthorizationError("INSTALL_AUTH_EXPIRED_OR_INVALID_WINDOW", "Authorization must be current and valid for at most 30 minutes.");
  }
  if (!SHA256.test(authorization.authorizationDigest)
    || authorization.authorizationDigest !== computeInstallationAuthorizationDigest(authorization)) {
    throw new InstallAuthorizationError("INSTALL_AUTH_DIGEST_MISMATCH", "Authorization record digest does not match its bounded content.");
  }
  return Object.freeze({
    schemaVersion: 1,
    status: "INSTALL_AUTHORIZATION_VERIFIED_PENDING_EXTERNAL_EXECUTION",
    authorizationId: authorization.authorizationId,
    approvalEvidenceRef: authorization.approvalEvidenceRef,
    authorizationDigest: authorization.authorizationDigest,
    sourceHead: authorization.sourceHead,
    pairId: authorization.pairId,
    manifestDigest: authorization.manifestDigest,
    attemptId: authorization.attemptId,
    machineAlias: authorization.machineAlias,
    operations: ALLOWED_OPERATIONS,
    expiresAt: authorization.expiresAt,
    installationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  });
}

export function createAuthorizedInstallationPlan({ preflightReceipt, authorization, clock = () => new Date() }) {
  const verified = validateInstallationAuthorization({ preflightReceipt, authorization, clock });
  return Object.freeze({
    ...verified,
    schemaVersion: 1,
    planId: digest({
      authorizationDigest: verified.authorizationDigest,
      sourceHead: verified.sourceHead,
      attemptId: verified.attemptId
    }),
    recordedAt: clock().toISOString(),
    status: "INSTALLATION_AUTHORIZED_PENDING_EXTERNAL_EXECUTION",
    installState: "AUTHORIZED_NOT_STARTED",
    rollbackState: "READY_NOT_REQUIRED",
    externalExecutionRequired: true
  });
}

function assertSafeObservation(current, event) {
  if (!new Set(["INSTALLATION_OBSERVED", "INSTALLATION_FAILED", "ROLLBACK_OBSERVED"]).has(event?.event)) {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_INVALID", "Unknown installation observation event.");
  }
  const eventKeys = event?.event === "INSTALLATION_OBSERVED"
    ? new Set([...OBSERVATION_COMMON_KEYS, "extensionLoaded", "localAgentStarted"])
    : event?.event === "INSTALLATION_FAILED"
      ? new Set([...OBSERVATION_COMMON_KEYS, "errorCode"])
      : event?.event === "ROLLBACK_OBSERVED"
        ? new Set([...OBSERVATION_COMMON_KEYS, "extensionRemoved", "localAgentStopped", "connectorFolderRemoved", "receiptsPreserved"])
        : new Set(OBSERVATION_COMMON_KEYS);
  assertExactKeys(event, eventKeys, "INSTALL_OBSERVATION_INVALID");
  if (!event
    || event.schemaVersion !== 1
    || event.observationClass !== "MCLENOVO_BOUNDED_LOCAL_OPERATOR"
    || !SAFE_ID.test(event.observationId)
    || event.sourceHead !== current.sourceHead
    || event.pairId !== current.pairId
    || event.manifestDigest !== current.manifestDigest
    || event.attemptId !== current.attemptId
    || event.nativeMessagingEnabled !== false
    || event.mysmisAccessPerformed !== false
    || event.mysmisWrites !== 0
    || event.remoteShellUsed !== false
    || event.credentialAccessPerformed !== false) {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_INVALID", "External installation observation violates the bounded contract.");
  }
}

export function transitionInstallationState({ current, event, clock = () => new Date() }) {
  if (!current || current.schemaVersion !== 1 || !SAFE_ID.test(current.attemptId)) {
    throw new InstallAuthorizationError("INSTALL_STATE_INVALID", "A valid current installation state is required.");
  }
  if (current.status === "INSTALLATION_AUTHORIZED_PENDING_EXTERNAL_EXECUTION") {
    assertSafeObservation(current, event);
    if (event.event === "INSTALLATION_OBSERVED"
      && event.extensionLoaded === true
      && event.localAgentStarted === true) {
      return Object.freeze({
        ...current,
        recordedAt: clock().toISOString(),
        status: "EXTERNAL_INSTALLATION_RECORDED_AWAITING_LIVE_HEALTH",
        observationId: event.observationId,
        installState: "EXTERNAL_EXECUTION_RECORDED",
        rollbackState: "READY_NOT_REQUIRED",
        installationPerformed: true,
        liveEvidenceClaimed: false
      });
    }
    if (event.event === "INSTALLATION_FAILED" && /^[A-Z0-9_]{1,80}$/u.test(event.errorCode)) {
      return Object.freeze({
        ...current,
        recordedAt: clock().toISOString(),
        status: "INSTALLATION_FAILED_ROLLBACK_REQUIRED",
        observationId: event.observationId,
        errorCode: event.errorCode,
        installState: "FAILED",
        rollbackState: "REQUIRED",
        installationPerformed: false,
        liveEvidenceClaimed: false
      });
    }
    throw new InstallAuthorizationError("INSTALL_TRANSITION_INVALID", "Only bounded observed success or failure can advance an authorized plan.");
  }
  if (current.status === "INSTALLATION_FAILED_ROLLBACK_REQUIRED") {
    assertSafeObservation(current, event);
    if (event.event !== "ROLLBACK_OBSERVED"
      || event.extensionRemoved !== true
      || event.localAgentStopped !== true
      || event.connectorFolderRemoved !== true
      || event.receiptsPreserved !== true) {
      throw new InstallAuthorizationError("INSTALL_ROLLBACK_INCOMPLETE", "Rollback must remove only installed components and preserve receipts.");
    }
    return Object.freeze({
      ...current,
      recordedAt: clock().toISOString(),
      status: "INSTALLATION_ROLLED_BACK_AWAITING_NEW_AUTHORIZATION",
      observationId: event.observationId,
      installState: "ROLLED_BACK",
      rollbackState: "COMPLETE",
      installationPerformed: false,
      liveEvidenceClaimed: false
    });
  }
  throw new InstallAuthorizationError("INSTALL_TRANSITION_NOT_ALLOWED", "Current state cannot be advanced by this contract.");
}

export const INSTALLATION_ALLOWED_OPERATIONS = ALLOWED_OPERATIONS;
