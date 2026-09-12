import { createHash, randomBytes } from "node:crypto";
import { discoverArtifacts } from "./artifact-discovery.mjs";
import { assertNoSensitivePersistence } from "./policy.mjs";

const EXECUTION_CLASSES = new Set(["LIVE_BRIDGE", "OFFLINE_FIXTURE"]);
const OBSERVATION_SOURCES = new Set(["LIVE_BRIDGE_TOOL", "OFFLINE_FIXTURE"]);
const REQUIRED_CAPABILITIES = Object.freeze(["DISCOVER_ARTIFACTS", "READ_CURRENT_PAGE_DOM"]);

const NON_RETRIEVABLE_REASON = Object.freeze({
  BLOCKED_WRITE_CONTROL: "WRITE_INTENT_CONTROL",
  BLOCKED_UNSAFE_METHOD: "UNSAFE_METHOD_UNPROVEN",
  ROUTE_METADATA_ONLY: "BINARY_SOURCE_NOT_EXPOSED",
  UI_READONLY_DOWNLOAD_OBSERVE: "MANUAL_DOWNLOAD_REQUIRED",
  BROWSER_DOWNLOAD_OBSERVE: "BROWSER_OBSERVATION_REQUIRED"
});

export class DiscoverCommandError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "DiscoverCommandError";
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

function parseTime(value, code) {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) throw new DiscoverCommandError(code, "Discovery timestamp is invalid.");
  return milliseconds;
}

function assertBuildId(value, field) {
  if (typeof value !== "string" || !/^[a-f0-9]{40}$/u.test(value)) {
    throw new DiscoverCommandError("DISCOVERY_BUILD_ID_INVALID", `${field} must be an exact Git commit SHA.`);
  }
}

function validateHealthReceipt(healthReceipt, executionClass, connectorBuildId) {
  try {
    assertNoSensitivePersistence(healthReceipt);
  } catch (error) {
    throw new DiscoverCommandError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  if (healthReceipt?.connectorBuildId !== connectorBuildId) {
    throw new DiscoverCommandError("DISCOVERY_HEALTH_BUILD_MISMATCH", "Health receipt does not match this connector build.");
  }
  const missing = REQUIRED_CAPABILITIES.filter((value) => !healthReceipt?.capabilities?.includes(value));
  if (missing.length) {
    throw new DiscoverCommandError("DISCOVERY_CAPABILITY_MISSING", "Health receipt lacks required discovery capabilities.", { missing });
  }
  if (healthReceipt?.safety?.readOnly !== true
    || healthReceipt?.safety?.mysmisWrites !== 0
    || healthReceipt?.safety?.controlsClicked !== 0
    || healthReceipt?.safety?.arbitraryShell !== false) {
    throw new DiscoverCommandError("DISCOVERY_HEALTH_SAFETY_INVALID", "Health receipt does not preserve the read-only boundary.");
  }
  if (executionClass === "LIVE_BRIDGE"
    && (healthReceipt.status !== "BRIDGE_HEALTH_LIVE_VERIFIED"
      || healthReceipt.liveVerified !== true
      || healthReceipt.runtime?.authenticatedSessionPresent !== true
      || healthReceipt.runtime?.mysmisOriginPresent !== true)) {
    throw new DiscoverCommandError("DISCOVERY_LIVE_HEALTH_REQUIRED", "Live discovery requires a live health receipt for an authenticated MySMIS page.");
  }
}

export function createDiscoverArtifactsCommand({
  connectorBuildId,
  healthReceipt,
  executionClass,
  projectSelector,
  track,
  clock = () => new Date(),
  ttlMs = 120_000,
  nonce = randomBytes(32).toString("hex")
}) {
  assertBuildId(connectorBuildId, "connectorBuildId");
  if (!EXECUTION_CLASSES.has(executionClass)) {
    throw new DiscoverCommandError("DISCOVERY_EXECUTION_CLASS_INVALID", "Discovery execution class must be explicit.");
  }
  if (!/^[a-f0-9]{64}$/u.test(nonce)) {
    throw new DiscoverCommandError("DISCOVERY_NONCE_INVALID", "Discovery nonce must contain 32 random bytes as lowercase hex.");
  }
  if (!Number.isSafeInteger(ttlMs) || ttlMs < 10_000 || ttlMs > 300_000) {
    throw new DiscoverCommandError("DISCOVERY_TTL_INVALID", "Discovery TTL must be between 10 and 300 seconds.");
  }
  if (!projectSelector || typeof projectSelector !== "string" || projectSelector.length > 64) {
    throw new DiscoverCommandError("DISCOVERY_PROJECT_SELECTOR_INVALID", "Project selector must be an opaque string of at most 64 characters.");
  }
  if (!["WRITING", "IMPLEMENTATION"].includes(track)) {
    throw new DiscoverCommandError("DISCOVERY_TRACK_INVALID", "Discovery track must remain explicitly separated.");
  }
  validateHealthReceipt(healthReceipt, executionClass, connectorBuildId);

  const issuedAt = clock().toISOString();
  const expiresAt = new Date(parseTime(issuedAt, "DISCOVERY_TIME_INVALID") + ttlMs).toISOString();
  const core = {
    schemaVersion: 1,
    operation: "DISCOVER_ARTIFACTS",
    executionClass,
    connectorBuildId,
    healthChallengeId: healthReceipt.challengeId,
    projectSelector,
    track,
    issuedAt,
    expiresAt,
    nonce,
    scope: {
      pageContext: "CURRENT_PAGE_ONLY",
      allowedSources: ["CURRENT_PAGE_DOM", "OBSERVED_DOWNLOAD_METADATA", "OBSERVED_RESPONSE_METADATA"],
      allowedMethods: ["GET", "HEAD"]
    },
    restrictions: {
      readOnly: true,
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      cdpAttached: false,
      arbitraryShell: false
    }
  };
  const command = { ...core, commandId: digest(core) };
  assertNoSensitivePersistence(command);
  return command;
}

function validateSafety(response) {
  const expected = {
    readOnly: true,
    controlsClicked: 0,
    routeMutations: 0,
    mysmisWrites: 0,
    cdpAttached: false,
    arbitraryShell: false
  };
  for (const [key, value] of Object.entries(expected)) {
    if (response.safety?.[key] !== value) {
      throw new DiscoverCommandError("DISCOVERY_SAFETY_GATE_FAILED", `Discovery safety assertion ${key} is invalid.`);
    }
  }
  if (!Array.isArray(response.methodsObserved)
    || response.methodsObserved.some((method) => !["GET", "HEAD"].includes(String(method).toUpperCase()))) {
    throw new DiscoverCommandError("DISCOVERY_UNSAFE_METHOD_OBSERVED", "Discovery may only observe GET and HEAD requests.");
  }
}

function normalizeCandidate(candidate) {
  const retrievable = candidate.strategy === "DIRECT_URL_SAFE_GET";
  const nonRetrievableReason = retrievable ? null : NON_RETRIEVABLE_REASON[candidate.strategy];
  if (!retrievable && !nonRetrievableReason) {
    throw new DiscoverCommandError("DISCOVERY_REASON_MISSING", "Every non-retrievable artifact must have an explicit reason.");
  }
  return {
    candidateId: candidate.candidateId,
    artifactKind: candidate.artifactKind,
    label: candidate.label,
    method: candidate.method,
    url: candidate.url,
    strategy: candidate.strategy,
    retrievable,
    nonRetrievableReason,
    automatedActionAllowed: false,
    provenance: candidate.provenance
  };
}

export function validateDiscoverArtifactsResponse({
  command,
  response,
  observedVia,
  clock = () => new Date()
}) {
  try {
    assertNoSensitivePersistence(command);
    assertNoSensitivePersistence(response);
  } catch (error) {
    throw new DiscoverCommandError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  if (!OBSERVATION_SOURCES.has(observedVia)) {
    throw new DiscoverCommandError("DISCOVERY_OBSERVATION_SOURCE_INVALID", "Discovery observation source must be explicit.");
  }
  const expectedSource = command.executionClass === "LIVE_BRIDGE" ? "LIVE_BRIDGE_TOOL" : "OFFLINE_FIXTURE";
  if (observedVia !== expectedSource) {
    throw new DiscoverCommandError("DISCOVERY_OBSERVATION_CLASS_MISMATCH", "Observation source cannot promote an offline fixture to live evidence.");
  }
  if (command?.operation !== "DISCOVER_ARTIFACTS"
    || response?.schemaVersion !== 1
    || response.commandId !== command.commandId
    || response.nonceEcho !== command.nonce
    || response.connectorBuildId !== command.connectorBuildId
    || response.healthChallengeId !== command.healthChallengeId) {
    throw new DiscoverCommandError("DISCOVERY_COMMAND_MISMATCH", "Discovery response is not bound to this command, health receipt, and build.");
  }
  const issued = parseTime(command.issuedAt, "DISCOVERY_TIME_INVALID");
  const expires = parseTime(command.expiresAt, "DISCOVERY_TIME_INVALID");
  const captured = parseTime(response.capturedAt, "DISCOVERY_RESPONSE_TIME_INVALID");
  if (captured < issued || captured > expires || clock().getTime() > expires) {
    throw new DiscoverCommandError("DISCOVERY_COMMAND_EXPIRED", "Discovery response is stale or outside the command window.");
  }
  if (response.snapshot?.project?.code !== command.projectSelector
    || response.snapshot?.project?.track !== command.track) {
    throw new DiscoverCommandError("DISCOVERY_PROJECT_MISMATCH", "Snapshot does not match the requested benchmark track.");
  }
  validateSafety(response);

  const inventory = discoverArtifacts(response.snapshot);
  if (response.reportedCandidateCount !== inventory.candidates.length) {
    throw new DiscoverCommandError("DISCOVERY_INVENTORY_INCOMPLETE", "Bridge must report the complete current-page candidate count.", {
      reported: response.reportedCandidateCount,
      computed: inventory.candidates.length
    });
  }
  const candidates = inventory.candidates.map(normalizeCandidate);
  if (new Set(candidates.map((candidate) => candidate.candidateId)).size !== candidates.length) {
    throw new DiscoverCommandError("DISCOVERY_DUPLICATE_CANDIDATE", "Discovery candidate identifiers must be unique.");
  }
  const liveVerified = observedVia === "LIVE_BRIDGE_TOOL";
  const result = {
    schemaVersion: 1,
    status: liveVerified ? "DISCOVERY_LIVE_VERIFIED" : "DISCOVERY_CONTRACT_VERIFIED_ONLY",
    liveVerified,
    observedVia,
    commandId: command.commandId,
    connectorBuildId: command.connectorBuildId,
    healthChallengeId: command.healthChallengeId,
    project: inventory.project,
    page: inventory.page,
    capturedAt: response.capturedAt,
    candidates,
    counts: {
      total: candidates.length,
      retrievable: candidates.filter((candidate) => candidate.retrievable).length,
      nonRetrievable: candidates.filter((candidate) => !candidate.retrievable).length
    },
    invariants: {
      writeActionsPerformed: 0,
      controlsClicked: 0,
      routeMutations: 0,
      credentialsCaptured: 0,
      requestSecretMaterialPersisted: 0
    }
  };
  assertNoSensitivePersistence(result);
  return result;
}
