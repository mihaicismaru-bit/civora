import http from "node:http";

import { assertNoSensitivePersistence } from "../core/policy.mjs";

const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const HEX64_PATTERN = /^[a-f0-9]{64}$/u;
const MAX_BODY_BYTES = 1024 * 1024;
const ALLOWED_OPERATIONS = new Set(["HEALTH", "DISCOVER_ARTIFACTS"]);

export class LoopbackBrokerError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "LoopbackBrokerError";
    this.code = code;
    this.details = details;
  }
}

function identifyCommand(command) {
  if (command?.intent === "HEALTH_CHECK_ONLY") {
    return { operation: "HEALTH", commandId: command.challengeId };
  }
  return { operation: command?.operation, commandId: command?.commandId };
}

function assertCommandShape(command, sourceHead) {
  assertNoSensitivePersistence(command);
  const identity = identifyCommand(command);
  if (!ALLOWED_OPERATIONS.has(identity.operation)) {
    throw new LoopbackBrokerError("LOOPBACK_OPERATION_DENIED", "Loopback broker accepts only HEALTH and DISCOVER_ARTIFACTS.");
  }
  if (!HEX64_PATTERN.test(identity.commandId) || !HEX64_PATTERN.test(command?.nonce)) {
    throw new LoopbackBrokerError("LOOPBACK_COMMAND_ID_INVALID", "Loopback command identity and nonce must be lowercase 32-byte hex values.");
  }
  if (command?.connectorBuildId !== sourceHead) {
    throw new LoopbackBrokerError("LOOPBACK_BUILD_MISMATCH", "Loopback command does not match the attested source head.");
  }
  if (command?.restrictions?.readOnly !== true
    || command?.restrictions?.arbitraryShell !== false
    || command?.restrictions?.mysmisWrites !== 0
    || command?.restrictions?.controlsClicked !== 0) {
    throw new LoopbackBrokerError("LOOPBACK_SAFETY_INVALID", "Loopback command must remain read-only, zero-write, zero-click and no-shell.");
  }
  return identity;
}

function jsonResponse(response, statusCode, value) {
  const body = `${JSON.stringify(value)}\n`;
  response.writeHead(statusCode, {
    "content-type": "application/json; charset=utf-8",
    "cache-control": "no-store",
    "content-length": Buffer.byteLength(body),
    "x-content-type-options": "nosniff"
  });
  response.end(body);
}

function emptyResponse(response, statusCode = 204) {
  response.writeHead(statusCode, { "cache-control": "no-store" });
  response.end();
}

async function readJsonBody(request) {
  let total = 0;
  const chunks = [];
  for await (const chunk of request) {
    total += chunk.length;
    if (total > MAX_BODY_BYTES) {
      throw new LoopbackBrokerError("LOOPBACK_BODY_TOO_LARGE", "Loopback response body exceeds one MiB.");
    }
    chunks.push(chunk);
  }
  if (total === 0) {
    throw new LoopbackBrokerError("LOOPBACK_BODY_MISSING", "Loopback response body is required.");
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    throw new LoopbackBrokerError("LOOPBACK_JSON_INVALID", "Loopback response must be valid JSON.");
  }
}

function assertResultEnvelope({ envelope, pending, sourceHead }) {
  assertNoSensitivePersistence(envelope);
  if (!envelope || envelope.schemaVersion !== 1 || envelope.source !== "MV3_EXTENSION_LOOPBACK") {
    throw new LoopbackBrokerError("LOOPBACK_RESULT_INVALID", "Loopback result envelope is invalid.");
  }
  if (envelope.commandId !== pending.commandId || envelope.nonceEcho !== pending.command.nonce) {
    throw new LoopbackBrokerError("LOOPBACK_RESULT_BINDING_MISMATCH", "Loopback result does not bind to the outstanding command and nonce.");
  }
  if (envelope.connectorBuildId !== sourceHead || envelope.operation !== pending.operation) {
    throw new LoopbackBrokerError("LOOPBACK_RESULT_BUILD_MISMATCH", "Loopback result does not match the attested build and operation.");
  }
  if (envelope.safety?.readOnly !== true
    || envelope.safety?.mysmisWrites !== 0
    || envelope.safety?.controlsClicked !== 0
    || envelope.safety?.arbitraryShell !== false
    || envelope.safety?.browserSecretsRead !== false) {
    throw new LoopbackBrokerError("LOOPBACK_RESULT_SAFETY_INVALID", "Loopback result must prove zero-write, zero-click, no-shell and no browser-secret access.");
  }
  if (!envelope.response || typeof envelope.response !== "object") {
    throw new LoopbackBrokerError("LOOPBACK_RESULT_RESPONSE_MISSING", "Loopback result must contain the bounded dispatcher response.");
  }
}

function safeError(error) {
  return {
    ok: false,
    error: {
      code: typeof error?.code === "string" ? error.code : "LOOPBACK_REJECTED",
      message: "Loopback request rejected fail-closed."
    }
  };
}

export function createLoopbackBroker({
  sourceHead,
  host = "127.0.0.1",
  port = 43127,
  clock = () => new Date(),
  maxWaitMs = 60_000
}) {
  if (!BUILD_PATTERN.test(sourceHead)) {
    throw new LoopbackBrokerError("LOOPBACK_SOURCE_HEAD_INVALID", "Loopback source head must be an exact Git SHA.");
  }
  if (host !== "127.0.0.1") {
    throw new LoopbackBrokerError("LOOPBACK_PUBLIC_BIND_DENIED", "Loopback broker may bind only to 127.0.0.1.");
  }
  if (!Number.isSafeInteger(port) || port < 0 || port > 65535) {
    throw new LoopbackBrokerError("LOOPBACK_PORT_INVALID", "Loopback port must be between 0 and 65535.");
  }
  if (!Number.isSafeInteger(maxWaitMs) || maxWaitMs < 1_000 || maxWaitMs > 120_000) {
    throw new LoopbackBrokerError("LOOPBACK_WAIT_INVALID", "Loopback wait must be between one and 120 seconds.");
  }

  let outstanding = null;
  let server = null;
  let boundPort = null;

  const handler = async (request, response) => {
    try {
      const remoteAddress = request.socket?.remoteAddress;
      if (!["127.0.0.1", "::ffff:127.0.0.1", "::1"].includes(remoteAddress)) {
        throw new LoopbackBrokerError("LOOPBACK_REMOTE_DENIED", "Only loopback clients are accepted.");
      }
      const url = new URL(request.url || "/", `http://${host}`);
      if (request.method === "GET" && url.pathname === "/v1/next") {
        if (!outstanding || outstanding.delivered) return emptyResponse(response);
        outstanding.delivered = true;
        return jsonResponse(response, 200, {
          schemaVersion: 1,
          source: "MCLENOVO_LOCAL_AGENT",
          commandId: outstanding.commandId,
          operation: outstanding.operation,
          connectorBuildId: sourceHead,
          deliveredAt: clock().toISOString(),
          command: outstanding.command,
          safety: {
            readOnly: true,
            mysmisWrites: 0,
            controlsClicked: 0,
            arbitraryShell: false,
            publicPortOpened: false
          }
        });
      }
      if (request.method === "POST" && url.pathname === "/v1/result") {
        if (!outstanding) {
          throw new LoopbackBrokerError("LOOPBACK_NO_OUTSTANDING_COMMAND", "No outstanding command exists.");
        }
        const envelope = await readJsonBody(request);
        assertResultEnvelope({ envelope, pending: outstanding, sourceHead });
        const pending = outstanding;
        outstanding = null;
        clearTimeout(pending.timer);
        pending.resolve(envelope.response);
        return jsonResponse(response, 200, { ok: true, commandId: pending.commandId });
      }
      return emptyResponse(response, 404);
    } catch (error) {
      return jsonResponse(response, 400, safeError(error));
    }
  };

  return {
    async start() {
      if (server) return { host, port: boundPort };
      server = http.createServer((request, response) => {
        handler(request, response).catch(() => {
          if (!response.headersSent) jsonResponse(response, 500, safeError(new LoopbackBrokerError("LOOPBACK_INTERNAL_REJECTED", "Internal failure.")));
          else response.destroy();
        });
      });
      await new Promise((resolve, reject) => {
        server.once("error", reject);
        server.listen(port, host, () => {
          server.off("error", reject);
          resolve();
        });
      });
      const address = server.address();
      if (!address || typeof address === "string" || address.address !== host) {
        await new Promise((resolve) => server.close(resolve));
        server = null;
        throw new LoopbackBrokerError("LOOPBACK_BIND_INVALID", "Loopback broker did not bind to the required local interface.");
      }
      boundPort = address.port;
      return { host, port: boundPort };
    },

    async stop() {
      if (!server) return;
      const current = server;
      server = null;
      if (outstanding) {
        const pending = outstanding;
        outstanding = null;
        clearTimeout(pending.timer);
        pending.reject(new LoopbackBrokerError("LOOPBACK_STOPPED", "Loopback broker stopped before a result arrived."));
      }
      await new Promise((resolve, reject) => current.close((error) => error ? reject(error) : resolve()));
      boundPort = null;
    },

    async dispatch(command) {
      if (!server) {
        throw new LoopbackBrokerError("LOOPBACK_NOT_STARTED", "Loopback broker must be started before dispatch.");
      }
      if (outstanding) {
        throw new LoopbackBrokerError("LOOPBACK_BUSY", "Only one bounded command may be outstanding at a time.");
      }
      const identity = assertCommandShape(command, sourceHead);
      const expiresAt = Date.parse(command.expiresAt);
      const remaining = Number.isFinite(expiresAt) ? expiresAt - clock().getTime() : maxWaitMs;
      const waitMs = Math.max(1, Math.min(maxWaitMs, remaining));
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          if (outstanding?.commandId === identity.commandId) outstanding = null;
          reject(new LoopbackBrokerError("LOOPBACK_RESULT_TIMEOUT", "No bounded extension result arrived before timeout."));
        }, waitMs);
        timer.unref?.();
        outstanding = {
          command,
          commandId: identity.commandId,
          operation: identity.operation,
          delivered: false,
          resolve,
          reject,
          timer
        };
      });
    },

    status() {
      return {
        schemaVersion: 1,
        state: server ? "LISTENING_LOOPBACK_ONLY" : "STOPPED",
        host,
        port: boundPort,
        sourceHead,
        outstandingCommandId: outstanding?.commandId || null,
        safety: {
          readOnly: true,
          mysmisWrites: 0,
          arbitraryShell: false,
          publicPortOpened: false,
          childProcessesSpawned: 0
        }
      };
    }
  };
}
