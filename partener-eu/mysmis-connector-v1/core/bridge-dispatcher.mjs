import { assertNoSensitivePersistence } from "./policy.mjs";
import { READ_ONLY_BRIDGE_CAPABILITIES } from "./bridge-capabilities.mjs";

const FIXED_OPERATIONS = new Set(["HEALTH", "DISCOVER_ARTIFACTS"]);
const SAFE_METHODS = new Set(["GET", "HEAD"]);
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

export class BridgeDispatchError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "BridgeDispatchError";
    this.code = code;
    this.details = details;
  }
}

export class MemoryReplayStore {
  #claims = new Map();

  claim(id, expiresAt, now) {
    for (const [key, expiry] of this.#claims) {
      if (expiry < now) this.#claims.delete(key);
    }
    if (this.#claims.has(id)) return false;
    this.#claims.set(id, expiresAt);
    return true;
  }
}

function normalizeKey(value) {
  return String(value).toLowerCase().replace(/[^a-z]/gu, "");
}

function assertNoExecutablePayload(value, path = "root") {
  if (value == null) return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoExecutablePayload(item, `${path}[${index}]`));
    return;
  }
  if (typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = normalizeKey(key);
    if (DANGEROUS_KEYS.has(normalized)) {
      throw new BridgeDispatchError("BRIDGE_EXECUTABLE_PAYLOAD_DENIED", `Executable payload field denied at ${path}.${key}.`);
    }
    if (normalized.includes("shell") && child !== false && child != null) {
      throw new BridgeDispatchError("BRIDGE_REMOTE_SHELL_DENIED", `Shell field denied at ${path}.${key}.`);
    }
    assertNoExecutablePayload(child, `${path}.${key}`);
  }
}

function parseTime(value, code) {
  const milliseconds = Date.parse(value);
  if (!Number.isFinite(milliseconds)) throw new BridgeDispatchError(code, "Bridge command timestamp is invalid.");
  return milliseconds;
}

function assertBuildId(value, field) {
  if (typeof value !== "string" || !/^[a-f0-9]{40}$/u.test(value)) {
    throw new BridgeDispatchError("BRIDGE_DISPATCH_BUILD_INVALID", `${field} must be an exact Git commit SHA.`);
  }
}

function identify(command) {
  if (command?.intent === "HEALTH_CHECK_ONLY") {
    return { operation: "HEALTH", id: command.challengeId };
  }
  return { operation: command?.operation, id: command?.commandId };
}

function validateCommand(command, connectorBuildId, now) {
  try {
    assertNoSensitivePersistence(command);
  } catch (error) {
    throw new BridgeDispatchError("SENSITIVE_PERSISTENCE_DENIED", error.message);
  }
  assertNoExecutablePayload(command);
  const identity = identify(command);
  if (!FIXED_OPERATIONS.has(identity.operation)) {
    throw new BridgeDispatchError("BRIDGE_OPERATION_DENIED", "Only HEALTH and DISCOVER_ARTIFACTS are dispatchable.");
  }
  if (!identity.id || typeof identity.id !== "string" || identity.id.length > 128) {
    throw new BridgeDispatchError("BRIDGE_COMMAND_ID_INVALID", "Bridge command identifier is missing or invalid.");
  }
  assertBuildId(command.connectorBuildId, "command.connectorBuildId");
  if (command.connectorBuildId !== connectorBuildId) {
    throw new BridgeDispatchError("BRIDGE_DISPATCH_BUILD_MISMATCH", "Command does not match the configured connector build.");
  }
  if (!/^[a-f0-9]{64}$/u.test(command.nonce)) {
    throw new BridgeDispatchError("BRIDGE_DISPATCH_NONCE_INVALID", "Command nonce must contain 32 random bytes as lowercase hex.");
  }
  const issuedAt = parseTime(command.issuedAt, "BRIDGE_DISPATCH_TIME_INVALID");
  const expiresAt = parseTime(command.expiresAt, "BRIDGE_DISPATCH_TIME_INVALID");
  if (expiresAt <= issuedAt || expiresAt - issuedAt > 300_000 || now < issuedAt || now > expiresAt) {
    throw new BridgeDispatchError("BRIDGE_DISPATCH_EXPIRED", "Command is expired, premature, or outside the maximum five-minute window.");
  }
  if (command.restrictions?.arbitraryShell !== false
    || command.restrictions?.mysmisWrites !== 0
    || command.restrictions?.controlsClicked !== 0) {
    throw new BridgeDispatchError("BRIDGE_DISPATCH_SAFETY_INVALID", "Command must explicitly preserve zero-write, zero-click, no-shell restrictions.");
  }
  return { ...identity, expiresAt };
}

function validateHealthPayload(payload) {
  if (!payload || typeof payload.agentBuildId !== "string" || !/^[a-f0-9]{40}$/u.test(payload.agentBuildId)) {
    throw new BridgeDispatchError("BRIDGE_AGENT_BUILD_INVALID", "Health handler must identify the exact agent build.");
  }
  if (!Array.isArray(payload.capabilities)) {
    throw new BridgeDispatchError("BRIDGE_CAPABILITIES_INVALID", "Health handler must declare capabilities.");
  }
  const seen = new Set();
  for (const capability of payload.capabilities) {
    if (!READ_ONLY_BRIDGE_CAPABILITIES.includes(capability?.name)
      || !["READ_ONLY", "OBSERVE"].includes(capability?.mode)
      || seen.has(capability.name)) {
      throw new BridgeDispatchError("BRIDGE_CAPABILITY_DENIED", "Health handler returned an unknown, mutable, or duplicate capability.");
    }
    seen.add(capability.name);
  }
  const missing = READ_ONLY_BRIDGE_CAPABILITIES.filter((name) => !seen.has(name));
  if (missing.length) {
    throw new BridgeDispatchError("BRIDGE_CAPABILITY_MISSING", "Health handler omitted required capabilities.", { missing });
  }
  if (!payload.runtime
    || !["CHROME", "EDGE"].includes(payload.runtime.browserFamily)
    || payload.runtime.manifestVersion !== 3
    || payload.runtime.extensionReady !== true
    || payload.runtime.nativeAgentReady !== true
    || typeof payload.runtime.authenticatedSessionPresent !== "boolean"
    || typeof payload.runtime.mysmisOriginPresent !== "boolean") {
    throw new BridgeDispatchError("BRIDGE_RUNTIME_NOT_READY", "Health handler returned an invalid runtime state.");
  }
}

function validateDiscoveryPayload(payload) {
  if (!payload?.snapshot || typeof payload.snapshot !== "object" || !Array.isArray(payload.snapshot.elements)) {
    throw new BridgeDispatchError("BRIDGE_DISCOVERY_SNAPSHOT_INVALID", "Discovery handler must return a current-page DOM snapshot.");
  }
  if (!Number.isSafeInteger(payload.reportedCandidateCount) || payload.reportedCandidateCount < 0) {
    throw new BridgeDispatchError("BRIDGE_DISCOVERY_COUNT_INVALID", "Discovery handler must report a non-negative candidate count.");
  }
  if (!Array.isArray(payload.methodsObserved)
    || payload.methodsObserved.some((method) => !SAFE_METHODS.has(String(method).toUpperCase()))) {
    throw new BridgeDispatchError("BRIDGE_DISCOVERY_METHOD_DENIED", "Discovery handler may report GET and HEAD observations only.");
  }
}

export function createFixedBridgeDispatcher({
  connectorBuildId,
  agentBuildId,
  replayStore = new MemoryReplayStore(),
  clock = () => new Date(),
  healthHandler,
  discoverHandler
}) {
  assertBuildId(connectorBuildId, "connectorBuildId");
  assertBuildId(agentBuildId, "agentBuildId");
  if (typeof healthHandler !== "function" || typeof discoverHandler !== "function") {
    throw new BridgeDispatchError("BRIDGE_HANDLER_MISSING", "Fixed health and discovery handlers are required.");
  }

  return async function dispatch(command) {
    const now = clock().getTime();
    const identity = validateCommand(command, connectorBuildId, now);
    if (!await replayStore.claim(identity.id, identity.expiresAt, now)) {
      throw new BridgeDispatchError("BRIDGE_REPLAY_DENIED", "Bridge command identifier has already been consumed.");
    }

    let response;
    if (identity.operation === "HEALTH") {
      const payload = await healthHandler({
        targetLabel: command.targetLabel,
        connectorBuildId,
        requiredCapabilities: [...READ_ONLY_BRIDGE_CAPABILITIES]
      });
      try {
        assertNoSensitivePersistence(payload);
      } catch (error) {
        throw new BridgeDispatchError("SENSITIVE_PERSISTENCE_DENIED", error.message);
      }
      assertNoExecutablePayload(payload);
      validateHealthPayload({ ...payload, agentBuildId: payload.agentBuildId || agentBuildId });
      response = {
        schemaVersion: 1,
        protocolVersion: command.protocolVersion,
        challengeId: command.challengeId,
        nonceEcho: command.nonce,
        targetLabel: command.targetLabel,
        connectorBuildId,
        agentBuildId,
        respondedAt: clock().toISOString(),
        capabilities: payload.capabilities,
        runtime: payload.runtime,
        safety: {
          readOnly: true,
          arbitraryShell: false,
          mysmisWrites: 0,
          controlsClicked: 0,
          browserSecretsRead: false
        }
      };
    } else {
      const payload = await discoverHandler({
        pageContext: "CURRENT_PAGE_ONLY",
        projectSelector: command.projectSelector,
        track: command.track,
        allowedMethods: ["GET", "HEAD"]
      });
      try {
        assertNoSensitivePersistence(payload);
      } catch (error) {
        throw new BridgeDispatchError("SENSITIVE_PERSISTENCE_DENIED", error.message);
      }
      assertNoExecutablePayload(payload);
      validateDiscoveryPayload(payload);
      response = {
        schemaVersion: 1,
        commandId: command.commandId,
        nonceEcho: command.nonce,
        connectorBuildId,
        healthChallengeId: command.healthChallengeId,
        capturedAt: clock().toISOString(),
        snapshot: payload.snapshot,
        reportedCandidateCount: payload.reportedCandidateCount,
        methodsObserved: payload.methodsObserved.map((method) => String(method).toUpperCase()),
        safety: {
          readOnly: true,
          controlsClicked: 0,
          routeMutations: 0,
          mysmisWrites: 0,
          cdpAttached: false,
          arbitraryShell: false
        }
      };
    }
    assertNoSensitivePersistence(response);
    assertNoExecutablePayload(response);
    return response;
  };
}
