import { createHash } from "node:crypto";
import { validateBridgeHealthResponse } from "../core/bridge-health.mjs";
import {
  createAuthorizedInstallationPlan,
  transitionInstallationState
} from "./install-authorization.mjs";

const GIT_SHA = /^[a-f0-9]{40}$/u;
const SHA256 = /^[a-f0-9]{64}$/u;
const ORDER = Object.freeze([
  "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
  "BOUNDED_INSTALLATION_AUTHORIZED_EXTERNAL",
  "INSTALLATION_AUTHORIZED_PENDING_EXTERNAL_EXECUTION",
  "INSTALLATION_OBSERVED",
  "EXTERNAL_INSTALLATION_RECORDED_AWAITING_LIVE_HEALTH",
  "HEALTH_CHECK_ONLY",
  "HEALTH_RESPONSE",
  "BRIDGE_HEALTH_LIVE_VERIFIED"
]);

export class HandoffChainError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "HandoffChainError";
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

function same(left, right) {
  return JSON.stringify(canonicalize(left)) === JSON.stringify(canonicalize(right));
}

function time(value, code) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) throw new HandoffChainError(code, "Chain timestamps must be valid ISO dates.");
  return parsed;
}

function recordKind(record, index) {
  if (index === 3) return record?.event;
  if (index === 5) return record?.intent;
  if (index === 6) return "HEALTH_RESPONSE";
  return record?.status;
}

function assertNoUnboundedSensitiveFields(value, path = "root") {
  if (value == null) return;
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoUnboundedSensitiveFields(item, `${path}[${index}]`));
    return;
  }
  if (typeof value !== "object") return;
  for (const [key, child] of Object.entries(value)) {
    const normalized = key.toLowerCase().replace(/[^a-z]/gu, "");
    const allowedAuthorizationMetadata = new Set(["authorizationid", "authorizationdigest"]);
    if ((!allowedAuthorizationMetadata.has(normalized) && normalized.includes("authorization"))
      || ["cookie", "setcookie", "password", "mfa", "localstorage", "sessionstorage", "token"]
        .some((field) => normalized.includes(field))) {
      throw new HandoffChainError("HANDOFF_CHAIN_SENSITIVE_FIELD_DENIED", `Sensitive field denied at ${path}.`);
    }
    assertNoUnboundedSensitiveFields(child, `${path}.${key}`);
  }
}

function assertEnvelope(chain) {
  if (!chain || typeof chain !== "object" || Array.isArray(chain)
    || Object.keys(chain).sort().join(",") !== "mode,records,schemaVersion"
    || chain.schemaVersion !== 1
    || chain.mode !== "APPEND_ONLY_ORDERED"
    || !Array.isArray(chain.records)
    || chain.records.length !== ORDER.length) {
    throw new HandoffChainError("HANDOFF_CHAIN_SHAPE_INVALID", "A complete ordered eight-record handoff chain is required.");
  }
  const observedOrder = chain.records.map(recordKind);
  if (!same(observedOrder, ORDER)) {
    throw new HandoffChainError("HANDOFF_CHAIN_ORDER_INVALID", "Handoff records are missing, reordered or use an invalid class.");
  }
  assertNoUnboundedSensitiveFields(chain);
}

export function verifyHandoffChain({ chain }) {
  assertEnvelope(chain);
  const [preflight, authorization, plan, observation, installed, challenge, response, health] = chain.records;
  const sourceHead = preflight.sourceHead;
  if (!GIT_SHA.test(sourceHead)
    || !SHA256.test(preflight.pairId)
    || !SHA256.test(preflight.manifestDigest)) {
    throw new HandoffChainError("HANDOFF_CHAIN_PREFLIGHT_INVALID", "Preflight build bindings are invalid.");
  }

  const expectedPlan = createAuthorizedInstallationPlan({
    preflightReceipt: preflight,
    authorization,
    clock: () => new Date(plan.recordedAt)
  });
  if (!same(expectedPlan, plan)) {
    throw new HandoffChainError("HANDOFF_CHAIN_PLAN_MISMATCH", "Authorization plan does not match preflight and external authorization.");
  }
  const expectedInstalled = transitionInstallationState({
    current: plan,
    event: observation,
    clock: () => new Date(installed.recordedAt)
  });
  if (!same(expectedInstalled, installed)) {
    throw new HandoffChainError("HANDOFF_CHAIN_INSTALLATION_MISMATCH", "Installed state does not match the bounded external observation.");
  }

  if (challenge.connectorBuildId !== sourceHead
    || response.connectorBuildId !== sourceHead
    || response.agentBuildId !== sourceHead) {
    throw new HandoffChainError("HANDOFF_CHAIN_BUILD_MISMATCH", "Health challenge and both runtime components must use the exact preflight head.");
  }
  const expectedHealth = validateBridgeHealthResponse({
    challenge,
    response,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: () => new Date(health.observedAt)
  });
  if (!same(expectedHealth, health)
    || health.liveVerified !== true
    || health.runtime?.authenticatedSessionPresent !== true
    || health.runtime?.mysmisOriginPresent !== true) {
    throw new HandoffChainError("HANDOFF_CHAIN_LIVE_HEALTH_INVALID", "A recomputed authenticated live HEALTH receipt is required.");
  }

  const moments = [
    time(preflight.recordedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(authorization.issuedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(plan.recordedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(installed.recordedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(challenge.issuedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(response.respondedAt, "HANDOFF_CHAIN_TIME_INVALID"),
    time(health.observedAt, "HANDOFF_CHAIN_TIME_INVALID")
  ];
  if (moments.some((value, index) => index > 0 && value < moments[index - 1])
    || moments[3] > time(plan.expiresAt, "HANDOFF_CHAIN_TIME_INVALID")) {
    throw new HandoffChainError("HANDOFF_CHAIN_TIME_ORDER_INVALID", "Handoff records are not monotonic or installation occurred after authorization expiry.");
  }

  const chainId = digest(chain.records);
  return Object.freeze({
    schemaVersion: 1,
    status: "HANDOFF_CHAIN_LIVE_HEALTH_VERIFIED_PENDING_BENCHMARKS",
    chainId,
    recordCount: ORDER.length,
    sourceHead,
    pairId: preflight.pairId,
    manifestDigest: preflight.manifestDigest,
    attemptId: preflight.attemptId,
    authorizationId: authorization.authorizationId,
    planId: plan.planId,
    observationId: observation.observationId,
    challengeId: challenge.challengeId,
    healthObservedAt: health.observedAt,
    liveHealthVerified: true,
    authenticatedSessionPresent: true,
    mysmisOriginPresent: true,
    benchmarkTraversalPerformed: false,
    mysmisWrites: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}

export function createHandoffChainFailureReceipt({ error, clock = () => new Date() }) {
  const errorCode = error instanceof HandoffChainError && /^[A-Z0-9_]{1,80}$/u.test(error.code)
    ? error.code
    : typeof error?.code === "string" && /^[A-Z0-9_]{1,80}$/u.test(error.code)
      ? error.code
      : "HANDOFF_CHAIN_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: "HANDOFF_CHAIN_REJECTED_NO_EXECUTION",
    errorCode,
    installationPerformed: false,
    liveHealthVerified: false,
    benchmarkTraversalPerformed: false,
    mysmisWrites: 0,
    functionalAcceptance: "NOT_CLAIMED"
  });
}

export const HANDOFF_CHAIN_ORDER = ORDER;
