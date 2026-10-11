import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  BridgeDispatchError,
  createFixedBridgeDispatcher,
  MemoryReplayStore
} from "../core/bridge-dispatcher.mjs";
import {
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES,
  validateBridgeHealthResponse
} from "../core/bridge-health.mjs";
import {
  createDiscoverArtifactsCommand,
  validateDiscoverArtifactsResponse
} from "../core/discover-command.mjs";

const CONNECTOR_BUILD = "6d33f69ba67a03791777f4c6951e64691500e64c";
const AGENT_BUILD = "3".repeat(40);
const nonce = "ef".repeat(32);
const issuedClock = () => new Date("2026-08-29T16:30:00.000Z");
const dispatchClock = () => new Date("2026-08-29T16:30:30.000Z");

async function fixture(name) {
  return JSON.parse(await readFile(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
}

function healthPayload(overrides = {}) {
  return {
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
    ...overrides
  };
}

function dispatcher({ health = healthPayload(), discover, clock = dispatchClock, replayStore } = {}) {
  return createFixedBridgeDispatcher({
    connectorBuildId: CONNECTOR_BUILD,
    agentBuildId: AGENT_BUILD,
    replayStore,
    clock,
    healthHandler: async () => health,
    discoverHandler: async () => discover || {
      snapshot: { project: { code: "none", track: "WRITING" }, page: {}, elements: [] },
      reportedCandidateCount: 0,
      methodsObserved: []
    }
  });
}

function challenge(overrides = {}) {
  return createBridgeHealthChallenge({
    connectorBuildId: CONNECTOR_BUILD,
    clock: issuedClock,
    nonce,
    ...overrides
  });
}

test("fixed dispatcher returns a health response accepted as live evidence", async () => {
  const value = challenge();
  const response = await dispatcher()(value);
  const receipt = validateBridgeHealthResponse({
    challenge: value,
    response,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: dispatchClock
  });
  assert.equal(receipt.status, "BRIDGE_HEALTH_LIVE_VERIFIED");
  assert.equal(receipt.safety.arbitraryShell, false);
  assert.equal(receipt.safety.mysmisWrites, 0);
});

test("same dispatcher shape completes the 310224 live discovery envelope without clicks", async () => {
  const healthChallenge = challenge();
  const healthResponse = await dispatcher()(healthChallenge);
  const healthReceipt = validateBridgeHealthResponse({
    challenge: healthChallenge,
    response: healthResponse,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: dispatchClock
  });
  const snapshot = await fixture("310224-failed-direct-get.json");
  const command = createDiscoverArtifactsCommand({
    connectorBuildId: CONNECTOR_BUILD,
    healthReceipt,
    executionClass: "LIVE_BRIDGE",
    projectSelector: "310224",
    track: "IMPLEMENTATION",
    clock: issuedClock,
    nonce: "12".repeat(32)
  });
  const response = await dispatcher({
    discover: {
      snapshot,
      reportedCandidateCount: 10,
      methodsObserved: ["GET", "HEAD"]
    }
  })(command);
  const result = validateDiscoverArtifactsResponse({
    command,
    response,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: dispatchClock
  });
  assert.equal(result.status, "DISCOVERY_LIVE_VERIFIED");
  assert.equal(result.counts.total, 10);
  assert.equal(response.safety.controlsClicked, 0);
  assert.equal(response.safety.routeMutations, 0);
});

test("unknown, write and shell operations are never dispatched", async () => {
  for (const operation of ["SAVE", "SUBMIT", "REMOTE_SHELL"]) {
    await assert.rejects(
      () => dispatcher()({
        schemaVersion: 1,
        operation,
        commandId: `cmd-${operation}`,
        connectorBuildId: CONNECTOR_BUILD,
        issuedAt: "2026-08-29T16:30:00.000Z",
        expiresAt: "2026-08-29T16:32:00.000Z",
        nonce,
        restrictions: { arbitraryShell: false, mysmisWrites: 0, controlsClicked: 0 }
      }),
      (error) => error instanceof BridgeDispatchError && error.code === "BRIDGE_OPERATION_DENIED"
    );
  }
});

test("replayed command identifiers are consumed once", async () => {
  const value = challenge();
  const dispatch = dispatcher({ replayStore: new MemoryReplayStore() });
  await dispatch(value);
  await assert.rejects(
    () => dispatch(value),
    (error) => error.code === "BRIDGE_REPLAY_DENIED"
  );
});

test("expired, premature and build-mismatched commands fail before handlers", async () => {
  await assert.rejects(
    () => dispatcher({ clock: () => new Date("2026-08-29T16:35:01.000Z") })(challenge()),
    (error) => error.code === "BRIDGE_DISPATCH_EXPIRED"
  );
  await assert.rejects(
    () => dispatcher({ clock: () => new Date("2026-08-29T16:29:59.000Z") })(challenge()),
    (error) => error.code === "BRIDGE_DISPATCH_EXPIRED"
  );
  await assert.rejects(
    () => dispatcher()({ ...challenge(), connectorBuildId: "4".repeat(40) }),
    (error) => error.code === "BRIDGE_DISPATCH_BUILD_MISMATCH"
  );
});

test("executable and sensitive payload fields fail closed", async () => {
  await assert.rejects(
    () => dispatcher()({ ...challenge(), script: "denied" }),
    (error) => error.code === "BRIDGE_EXECUTABLE_PAYLOAD_DENIED"
  );
  await assert.rejects(
    () => dispatcher({ health: healthPayload({ token: "denied" }) })(challenge()),
    (error) => error.code === "SENSITIVE_PERSISTENCE_DENIED"
  );
});

test("discovery handler cannot report POST or unsafe browser behavior", async () => {
  const healthChallenge = challenge();
  const healthResponse = await dispatcher()(healthChallenge);
  const healthReceipt = validateBridgeHealthResponse({
    challenge: healthChallenge,
    response: healthResponse,
    observedVia: "LIVE_BRIDGE_TOOL",
    clock: dispatchClock
  });
  const snapshot = await fixture("367944-schema-discovery.json");
  const command = createDiscoverArtifactsCommand({
    connectorBuildId: CONNECTOR_BUILD,
    healthReceipt,
    executionClass: "LIVE_BRIDGE",
    projectSelector: "367944",
    track: "WRITING",
    clock: issuedClock,
    nonce: "34".repeat(32)
  });
  await assert.rejects(
    () => dispatcher({
      discover: { snapshot, reportedCandidateCount: 10, methodsObserved: ["GET", "POST"] }
    })(command),
    (error) => error.code === "BRIDGE_DISCOVERY_METHOD_DENIED"
  );
});
