import assert from "node:assert/strict";
import test from "node:test";
import {
  BridgeHealthError,
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES,
  validateBridgeHealthResponse
} from "../core/bridge-health.mjs";

const CONNECTOR_BUILD = "820b2b21068da32447c255be3b0ffae09d3b65dd";
const AGENT_BUILD = "1111111111111111111111111111111111111111";
const issuedClock = () => new Date("2026-08-29T14:00:00.000Z");
const observedClock = () => new Date("2026-08-29T14:00:30.000Z");
const nonce = "ab".repeat(32);

function challenge(overrides = {}) {
  return createBridgeHealthChallenge({ connectorBuildId: CONNECTOR_BUILD, clock: issuedClock, nonce, ...overrides });
}

function responseFor(value, overrides = {}) {
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    challengeId: value.challengeId,
    nonceEcho: value.nonce,
    targetLabel: value.targetLabel,
    connectorBuildId: value.connectorBuildId,
    agentBuildId: AGENT_BUILD,
    respondedAt: "2026-08-29T14:00:20.000Z",
    capabilities: READ_ONLY_BRIDGE_CAPABILITIES.map((name) => ({
      name,
      mode: name === "OBSERVE_DOWNLOADS" ? "OBSERVE" : "READ_ONLY"
    })),
    runtime: {
      browserFamily: "EDGE",
      manifestVersion: 3,
      extensionReady: true,
      nativeAgentReady: true,
      authenticatedSessionPresent: true,
      mysmisOriginPresent: true
    },
    safety: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false
    },
    ...overrides
  };
}

test("validates the complete read-only health contract without claiming a live bridge", () => {
  const value = challenge();
  const receipt = validateBridgeHealthResponse({
    challenge: value,
    response: responseFor(value),
    observedVia: "OFFLINE_FIXTURE",
    clock: observedClock
  });
  assert.equal(receipt.status, "BRIDGE_HEALTH_CONTRACT_VERIFIED_ONLY");
  assert.equal(receipt.liveVerified, false);
  assert.equal(receipt.safety.arbitraryShell, false);
  assert.equal(receipt.safety.mysmisWrites, 0);
  assert.deepEqual(receipt.capabilities, [...READ_ONLY_BRIDGE_CAPABILITIES].sort());
});

test("only the trusted caller observation class can mark a response live", () => {
  const value = challenge();
  const receipt = validateBridgeHealthResponse({
    challenge: value,
    response: responseFor(value),
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: observedClock
  });
  assert.equal(receipt.status, "BRIDGE_HEALTH_LIVE_VERIFIED");
  assert.equal(receipt.liveVerified, true);
});

test("rejects expired or replayed health responses", () => {
  const value = challenge({ ttlMs: 10_000 });
  assert.throws(
    () => validateBridgeHealthResponse({
      challenge: value,
      response: responseFor(value, { respondedAt: "2026-08-29T14:00:11.000Z" }),
      observedVia: "LIVE_BRIDGE_TOOL",
      clock: () => new Date("2026-08-29T14:00:11.000Z")
    }),
    (error) => error instanceof BridgeHealthError && error.code === "BRIDGE_CHALLENGE_EXPIRED"
  );
});

test("rejects write and remote-shell capability declarations", () => {
  const value = challenge();
  for (const denied of ["SAVE", "SUBMIT", "REMOTE_SHELL"]) {
    assert.throws(
      () => validateBridgeHealthResponse({
        challenge: value,
        response: responseFor(value, {
          capabilities: [...responseFor(value).capabilities, { name: denied, mode: "READ_ONLY" }]
        }),
        observedVia: "OFFLINE_FIXTURE",
        clock: observedClock
      }),
      (error) => error instanceof BridgeHealthError && error.code === "BRIDGE_CAPABILITY_DENIED"
    );
  }
});

test("rejects sensitive fields even when the response otherwise matches", () => {
  const value = challenge();
  assert.throws(
    () => validateBridgeHealthResponse({
      challenge: value,
      response: responseFor(value, { authorization: "denied" }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error instanceof BridgeHealthError && error.code === "SENSITIVE_PERSISTENCE_DENIED"
  );
});

test("rejects missing capabilities, build mismatch and unready runtime", () => {
  const value = challenge();
  assert.throws(
    () => validateBridgeHealthResponse({
      challenge: value,
      response: responseFor(value, { capabilities: responseFor(value).capabilities.slice(1) }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "BRIDGE_CAPABILITY_MISSING"
  );
  assert.throws(
    () => validateBridgeHealthResponse({
      challenge: value,
      response: responseFor(value, { connectorBuildId: "2".repeat(40) }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "BRIDGE_CHALLENGE_MISMATCH"
  );
  assert.throws(
    () => validateBridgeHealthResponse({
      challenge: value,
      response: responseFor(value, { runtime: { ...responseFor(value).runtime, extensionReady: false } }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "BRIDGE_RUNTIME_NOT_READY"
  );
});
