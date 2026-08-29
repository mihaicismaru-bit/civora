import { createHash, randomBytes } from "node:crypto";
import { assertNoSensitivePersistence } from "./policy.mjs";

export const BRIDGE_PROTOCOL_VERSION = 1;

export const READ_ONLY_BRIDGE_CAPABILITIES = Object.freeze([
  "HEALTH",
  "LIST_PROJECTS",
  "DISCOVER_ARTIFACTS",
  "READ_CURRENT_PAGE_DOM",
  "READ_ROUTE_SCHEMA",
  "OBSERVE_DOWNLOADS",
  "READ_COMPLETED_LOCAL_DOWNLOAD"
]);

const OBSERVATION_SOURCES = new Set(["OFFLINE_FIXTURE", "LIVE_BRIDGE_TOOL"]);
const BROWSER_FAMILIES = new Set(["CHROME", "EDGE"]);

export class BridgeHealthError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "BridgeHealthError";
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
  if (!Number.isFinite(milliseconds)) throw new BridgeHealthError(code, "Bridge health timestamp is invalid.");
  return milliseconds;
}

function assertBuildId(value, field) {
  if (typeof value !== "string" || !/^[a-f0-9]{40}$/u.test(value)) {
    throw new BridgeHealthError("BRIDGE_BUILD_ID_INVALID", `${field} must be an exact 40-character Git commit SHA.`);
  }
}

export function createBridgeHealthChallenge({
  connectorBuildId,
  targetLabel = "MCLENOVO",
  clock = () => new Date(),
  ttlMs = 120_000,
  nonce = randomBytes(32).toString("hex")
}) {
  assertBuildId(connectorBuildId, "connectorBuildId");
  if (!Number.isSafeInteger(ttlMs) || ttlMs < 10_000 || ttlMs > 300_000) {
    throw new BridgeHealthError("BRIDGE_CHALLENGE_TTL_INVALID", "Health challenge TTL must be between 10 and 300 seconds.");
  }
  if (!/^[a-f0-9]{64}$/u.test(nonce)) {
    throw new BridgeHealthError("BRIDGE_NONCE_INVALID", "Health challenge nonce must contain 32 random bytes as lowercase hex.");
  }
  const issuedAt = clock().toISOString();
  const expiresAt = new Date(parseTime(issuedAt, "BRIDGE_CHALLENGE_TIME_INVALID") + ttlMs).toISOString();
  const core = {
    schemaVersion: 1,
    protocolVersion: BRIDGE_PROTOCOL_VERSION,
    intent: "HEALTH_CHECK_ONLY",
    targetLabel: String(targetLabel).slice(0, 64),
    connectorBuildId,
    issuedAt,
    expiresAt,
    nonce,
    requiredCapabilities: [...READ_ONLY_BRIDGE_CAPABILITIES],
    restrictions: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0
    }
  };
  const challenge = { ...core, challengeId: digest(core) };
  assertNoSensitivePersistence(challenge);
  return challenge;
}

function validateCapabilities(challenge, response) {
  if (!Array.isArray(response.capabilities)) {
    throw new BridgeHealthError("BRIDGE_CAPABILITIES_INVALID", "Bridge response must declare its capabilities.");
  }
  const seen = new Set();
  for (const capability of response.capabilities) {
    if (!capability || typeof capability.name !== "string" || !["READ_ONLY", "OBSERVE"].includes(capability.mode)) {
      throw new BridgeHealthError("BRIDGE_CAPABILITIES_INVALID", "Every capability must use READ_ONLY or OBSERVE mode.");
    }
    if (!READ_ONLY_BRIDGE_CAPABILITIES.includes(capability.name)) {
      throw new BridgeHealthError("BRIDGE_CAPABILITY_DENIED", `Bridge capability ${capability.name} is not allowed.`);
    }
    if (seen.has(capability.name)) {
      throw new BridgeHealthError("BRIDGE_CAPABILITIES_INVALID", `Duplicate capability ${capability.name}.`);
    }
    seen.add(capability.name);
  }
  const missing = challenge.requiredCapabilities.filter((name) => !seen.has(name));
  if (missing.length) {
    throw new BridgeHealthError("BRIDGE_CAPABILITY_MISSING", "Bridge is missing required read-only capabilities.", { missing });
  }
  return [...seen].sort();
}

function validateSafety(response) {
  const expected = {
    readOnly: true,
    arbitraryShell: false,
    mysmisWrites: 0,
    controlsClicked: 0,
    browserSecretsRead: false
  };
  for (const [key, value] of Object.entries(expected)) {
    if (response.safety?.[key] !== value) {
      throw new BridgeHealthError("BRIDGE_SAFETY_GATE_FAILED", `Bridge safety assertion ${key} is invalid.`);
    }
  }
}

export function validateBridgeHealthResponse({
  challenge,
  response,
  observedVia,
  clock = () => new Date()
}) {
  assertNoSensitivePersistence(challenge);
  try {
    assertNoSensitivePersistence(response);
  } catch (error) {
    throw new BridgeHealthError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  if (!OBSERVATION_SOURCES.has(observedVia)) {
    throw new BridgeHealthError("BRIDGE_OBSERVATION_SOURCE_INVALID", "Bridge observation source must be explicit.");
  }
  if (!challenge || !response
    || challenge.schemaVersion !== 1
    || response.schemaVersion !== 1
    || challenge.protocolVersion !== BRIDGE_PROTOCOL_VERSION
    || response.protocolVersion !== BRIDGE_PROTOCOL_VERSION) {
    throw new BridgeHealthError("BRIDGE_PROTOCOL_MISMATCH", "Bridge health protocol version does not match.");
  }
  assertBuildId(challenge.connectorBuildId, "challenge.connectorBuildId");
  assertBuildId(response.connectorBuildId, "response.connectorBuildId");
  assertBuildId(response.agentBuildId, "response.agentBuildId");
  if (response.challengeId !== challenge.challengeId
    || response.nonceEcho !== challenge.nonce
    || response.targetLabel !== challenge.targetLabel
    || response.connectorBuildId !== challenge.connectorBuildId) {
    throw new BridgeHealthError("BRIDGE_CHALLENGE_MISMATCH", "Bridge response does not bind to the current challenge and build.");
  }

  const issued = parseTime(challenge.issuedAt, "BRIDGE_CHALLENGE_TIME_INVALID");
  const expires = parseTime(challenge.expiresAt, "BRIDGE_CHALLENGE_TIME_INVALID");
  const responded = parseTime(response.respondedAt, "BRIDGE_RESPONSE_TIME_INVALID");
  const observed = clock().getTime();
  if (responded < issued || responded > expires || observed > expires) {
    throw new BridgeHealthError("BRIDGE_CHALLENGE_EXPIRED", "Bridge health response is stale or outside the challenge window.");
  }

  if (!BROWSER_FAMILIES.has(response.runtime?.browserFamily)
    || response.runtime?.manifestVersion !== 3
    || response.runtime?.extensionReady !== true
    || response.runtime?.nativeAgentReady !== true
    || typeof response.runtime?.authenticatedSessionPresent !== "boolean"
    || typeof response.runtime?.mysmisOriginPresent !== "boolean") {
    throw new BridgeHealthError("BRIDGE_RUNTIME_NOT_READY", "Bridge runtime does not prove the required MV3/native-agent health state.");
  }
  validateSafety(response);
  const capabilities = validateCapabilities(challenge, response);
  const liveVerified = observedVia === "LIVE_BRIDGE_TOOL";
  const receipt = {
    schemaVersion: 1,
    status: liveVerified ? "BRIDGE_HEALTH_LIVE_VERIFIED" : "BRIDGE_HEALTH_CONTRACT_VERIFIED_ONLY",
    liveVerified,
    observedVia,
    challengeId: challenge.challengeId,
    targetLabel: challenge.targetLabel,
    connectorBuildId: challenge.connectorBuildId,
    agentBuildId: response.agentBuildId,
    protocolVersion: BRIDGE_PROTOCOL_VERSION,
    respondedAt: response.respondedAt,
    observedAt: clock().toISOString(),
    capabilities,
    runtime: {
      browserFamily: response.runtime.browserFamily,
      manifestVersion: 3,
      extensionReady: true,
      nativeAgentReady: true,
      authenticatedSessionPresent: response.runtime.authenticatedSessionPresent,
      mysmisOriginPresent: response.runtime.mysmisOriginPresent
    },
    safety: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false
    }
  };
  assertNoSensitivePersistence(receipt);
  return receipt;
}
