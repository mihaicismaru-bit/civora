import { assertNoSensitivePersistence } from "../core/policy.mjs";

const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const EXTENSION_ID_PATTERN = /^[a-p]{32}$/u;
const HEX64_PATTERN = /^[a-f0-9]{64}$/u;
const BROKER_ORIGIN = "http://127.0.0.1:43127";
const MAX_RESPONSE_BYTES = 1024 * 1024;
const ALLOWED_OPERATIONS = new Set(["HEALTH", "DISCOVER_ARTIFACTS"]);
const DELIVERY_KEYS = Object.freeze([
  "command", "commandId", "connectorBuildId", "deliveredAt", "extensionId",
  "operation", "safety", "schemaVersion", "source"
]);
const DELIVERY_SAFETY_KEYS = Object.freeze([
  "arbitraryShell", "controlsClicked", "mysmisWrites", "publicPortOpened", "readOnly"
]);

export class ExtensionLoopbackError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ExtensionLoopbackError";
    this.code = code;
  }
}

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

function identity(command) {
  if (command?.intent === "HEALTH_CHECK_ONLY") {
    return { operation: "HEALTH", commandId: command.challengeId };
  }
  return { operation: command?.operation, commandId: command?.commandId };
}

function validateDelivery({ delivery, sourceHead, extensionId, clock }) {
  try {
    assertNoSensitivePersistence(delivery);
  } catch {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_SENSITIVE_FIELD_DENIED", "Sensitive delivery fields are denied.");
  }
  if (!exactKeys(delivery, DELIVERY_KEYS) || !exactKeys(delivery.safety, DELIVERY_SAFETY_KEYS)) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_DELIVERY_SHAPE_INVALID", "Loopback delivery must match the fixed envelope.");
  }
  const commandIdentity = identity(delivery.command);
  if (delivery.schemaVersion !== 1 || delivery.source !== "MCLENOVO_LOCAL_AGENT"
    || delivery.extensionId !== extensionId || delivery.connectorBuildId !== sourceHead
    || delivery.command?.connectorBuildId !== sourceHead
    || delivery.commandId !== commandIdentity.commandId || delivery.operation !== commandIdentity.operation
    || !ALLOWED_OPERATIONS.has(delivery.operation) || !HEX64_PATTERN.test(delivery.commandId)
    || !HEX64_PATTERN.test(delivery.command?.nonce)) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_DELIVERY_BINDING_INVALID", "Delivery does not bind to this extension, build and fixed operation.");
  }
  const deliveredAt = Date.parse(delivery.deliveredAt);
  const issuedAt = Date.parse(delivery.command.issuedAt);
  const expiresAt = Date.parse(delivery.command.expiresAt);
  const now = clock().getTime();
  if (!Number.isFinite(deliveredAt) || !Number.isFinite(issuedAt) || !Number.isFinite(expiresAt)
    || deliveredAt < issuedAt || deliveredAt > expiresAt || now > expiresAt) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_DELIVERY_EXPIRED", "Delivery is stale or outside the command window.");
  }
  if (delivery.safety.readOnly !== true || delivery.safety.mysmisWrites !== 0
    || delivery.safety.controlsClicked !== 0 || delivery.safety.arbitraryShell !== false
    || delivery.safety.publicPortOpened !== false) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_DELIVERY_SAFETY_INVALID", "Delivery violates the zero-write loopback boundary.");
  }
  return commandIdentity;
}

async function boundedJson(response) {
  const declared = Number(response.headers?.get?.("content-length"));
  if (Number.isFinite(declared) && declared > MAX_RESPONSE_BYTES) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_RESPONSE_TOO_LARGE", "Loopback response exceeds one MiB.");
  }
  const text = await response.text();
  if (new TextEncoder().encode(text).length > MAX_RESPONSE_BYTES) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_RESPONSE_TOO_LARGE", "Loopback response exceeds one MiB.");
  }
  try {
    return JSON.parse(text);
  } catch {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_JSON_INVALID", "Loopback response is not valid JSON.");
  }
}

function endpoint(pathname, extensionId) {
  const url = new URL(pathname, BROKER_ORIGIN);
  url.searchParams.set("extensionId", extensionId);
  return url.toString();
}

function fetchOptions(method, body) {
  return {
    method,
    body,
    headers: body == null ? undefined : { "content-type": "application/json" },
    credentials: "omit",
    cache: "no-store",
    redirect: "error",
    referrerPolicy: "no-referrer"
  };
}

export function createExtensionLoopbackClient({
  sourceHead,
  extensionId,
  brokerOrigin = BROKER_ORIGIN,
  dispatch,
  fetchImpl = globalThis.fetch,
  clock = () => new Date()
}) {
  if (!BUILD_PATTERN.test(sourceHead)) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_SOURCE_HEAD_INVALID", "Loopback client requires the exact source head.");
  }
  if (!EXTENSION_ID_PATTERN.test(extensionId)) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_EXTENSION_ID_INVALID", "Loopback client requires the installed extension ID.");
  }
  if (brokerOrigin !== BROKER_ORIGIN) {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_ORIGIN_DENIED", "Only the fixed 127.0.0.1 broker origin is allowed.");
  }
  if (typeof dispatch !== "function" || typeof fetchImpl !== "function") {
    throw new ExtensionLoopbackError("MV3_LOOPBACK_RUNTIME_INVALID", "A fixed dispatcher and fetch implementation are required.");
  }

  return Object.freeze({
    async pollOnce() {
      let next;
      try {
        next = await fetchImpl(endpoint("/v1/next", extensionId), fetchOptions("GET"));
      } catch {
        return { status: "MV3_LOOPBACK_BROKER_UNAVAILABLE", liveEvidenceAccepted: false };
      }
      if (next.status === 204) {
        return { status: "MV3_LOOPBACK_NO_COMMAND", liveEvidenceAccepted: false };
      }
      if (next.status !== 200) {
        return { status: "MV3_LOOPBACK_DELIVERY_REJECTED", liveEvidenceAccepted: false };
      }
      let delivery;
      let commandIdentity;
      try {
        delivery = await boundedJson(next);
        commandIdentity = validateDelivery({ delivery, sourceHead, extensionId, clock });
      } catch (error) {
        return {
          status: "MV3_LOOPBACK_DELIVERY_REJECTED",
          errorCode: error instanceof ExtensionLoopbackError ? error.code : "MV3_LOOPBACK_DELIVERY_REJECTED",
          liveEvidenceAccepted: false
        };
      }

      let response;
      try {
        response = await dispatch(delivery.command);
        assertNoSensitivePersistence(response);
      } catch (error) {
        return {
          status: "MV3_LOOPBACK_DISPATCH_REJECTED",
          commandId: commandIdentity.commandId,
          errorCode: typeof error?.code === "string" && /^[A-Z0-9_]{3,96}$/u.test(error.code)
            ? error.code : "MV3_LOOPBACK_DISPATCH_REJECTED",
          liveEvidenceAccepted: false
        };
      }

      const envelope = {
        schemaVersion: 1,
        source: "MV3_EXTENSION_LOOPBACK",
        extensionId,
        commandId: commandIdentity.commandId,
        operation: commandIdentity.operation,
        connectorBuildId: sourceHead,
        nonceEcho: delivery.command.nonce,
        response,
        safety: {
          readOnly: true,
          mysmisWrites: 0,
          controlsClicked: 0,
          arbitraryShell: false,
          browserSecretsRead: false
        }
      };
      assertNoSensitivePersistence(envelope);
      let posted;
      try {
        posted = await fetchImpl(
          endpoint("/v1/result", extensionId),
          fetchOptions("POST", JSON.stringify(envelope))
        );
      } catch {
        return { status: "MV3_LOOPBACK_RESULT_NOT_ACKNOWLEDGED", commandId: commandIdentity.commandId, liveEvidenceAccepted: false };
      }
      if (posted.status !== 200) {
        return { status: "MV3_LOOPBACK_RESULT_NOT_ACKNOWLEDGED", commandId: commandIdentity.commandId, liveEvidenceAccepted: false };
      }
      let acknowledgement;
      try {
        acknowledgement = await boundedJson(posted);
      } catch {
        return { status: "MV3_LOOPBACK_RESULT_NOT_ACKNOWLEDGED", commandId: commandIdentity.commandId, liveEvidenceAccepted: false };
      }
      if (acknowledgement?.ok !== true || acknowledgement.commandId !== commandIdentity.commandId) {
        return { status: "MV3_LOOPBACK_RESULT_NOT_ACKNOWLEDGED", commandId: commandIdentity.commandId, liveEvidenceAccepted: false };
      }
      return {
        status: "MV3_LOOPBACK_RESULT_ACKNOWLEDGED_PENDING_DRIVE_READBACK",
        commandId: commandIdentity.commandId,
        operation: commandIdentity.operation,
        liveEvidenceAccepted: false
      };
    }
  });
}

export const FIXED_LOOPBACK_ORIGIN = BROKER_ORIGIN;
