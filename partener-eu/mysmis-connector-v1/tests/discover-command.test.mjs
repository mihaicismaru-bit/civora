import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  createDiscoverArtifactsCommand,
  DiscoverCommandError,
  validateDiscoverArtifactsResponse
} from "../core/discover-command.mjs";
import { READ_ONLY_BRIDGE_CAPABILITIES } from "../core/bridge-health.mjs";

const CONNECTOR_BUILD = "046b17970f5778db62f4a3baa1ad6b0445666e24";
const issuedClock = () => new Date("2026-08-29T15:00:00.000Z");
const observedClock = () => new Date("2026-08-29T15:00:30.000Z");
const nonce = "cd".repeat(32);

async function fixture(name) {
  return JSON.parse(await readFile(new URL(`../fixtures/${name}`, import.meta.url), "utf8"));
}

function health(liveVerified = false, overrides = {}) {
  return {
    schemaVersion: 1,
    status: liveVerified ? "BRIDGE_HEALTH_LIVE_VERIFIED" : "BRIDGE_HEALTH_CONTRACT_VERIFIED_ONLY",
    liveVerified,
    challengeId: "health-challenge-006",
    connectorBuildId: CONNECTOR_BUILD,
    capabilities: [...READ_ONLY_BRIDGE_CAPABILITIES].sort(),
    runtime: {
      authenticatedSessionPresent: liveVerified,
      mysmisOriginPresent: liveVerified
    },
    safety: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0
    },
    ...overrides
  };
}

function commandFor(projectSelector, track, overrides = {}) {
  return createDiscoverArtifactsCommand({
    connectorBuildId: CONNECTOR_BUILD,
    healthReceipt: health(false),
    executionClass: "OFFLINE_FIXTURE",
    projectSelector,
    track,
    clock: issuedClock,
    nonce,
    ...overrides
  });
}

function responseFor(command, snapshot, overrides = {}) {
  return {
    schemaVersion: 1,
    commandId: command.commandId,
    nonceEcho: command.nonce,
    connectorBuildId: command.connectorBuildId,
    healthChallengeId: command.healthChallengeId,
    capturedAt: "2026-08-29T15:00:20.000Z",
    snapshot,
    reportedCandidateCount: snapshot.elements.length,
    methodsObserved: ["GET", "HEAD"],
    safety: {
      readOnly: true,
      controlsClicked: 0,
      routeMutations: 0,
      mysmisWrites: 0,
      cdpAttached: false,
      arbitraryShell: false
    },
    ...overrides
  };
}

test("310224 creates a complete fail-closed artifact envelope from the real failed fixture", async () => {
  const snapshot = await fixture("310224-failed-direct-get.json");
  const command = commandFor("310224", "IMPLEMENTATION");
  const result = validateDiscoverArtifactsResponse({
    command,
    response: responseFor(command, snapshot),
    observedVia: "OFFLINE_FIXTURE",
    clock: observedClock
  });

  assert.equal(result.status, "DISCOVERY_CONTRACT_VERIFIED_ONLY");
  assert.equal(result.candidates.length, 10);
  assert.equal(result.counts.retrievable, 0);
  assert.equal(result.counts.nonRetrievable, 10);
  assert.ok(result.candidates.every((candidate) => candidate.nonRetrievableReason));
  assert.equal(result.candidates.find((candidate) => candidate.label === "Descarcă formular").nonRetrievableReason, "MANUAL_DOWNLOAD_REQUIRED");
  assert.equal(result.invariants.writeActionsPerformed, 0);
});

test("367944 maps every current-page schema candidate without inventing an export", async () => {
  const snapshot = await fixture("367944-schema-discovery.json");
  const command = commandFor("367944", "WRITING");
  const result = validateDiscoverArtifactsResponse({
    command,
    response: responseFor(command, snapshot),
    observedVia: "OFFLINE_FIXTURE",
    clock: observedClock
  });

  assert.equal(result.candidates.length, 10);
  assert.equal(result.counts.retrievable, 0);
  assert.equal(result.candidates.some((candidate) => candidate.strategy === "DIRECT_URL_SAFE_GET"), false);
  assert.equal(result.candidates.filter((candidate) => candidate.nonRetrievableReason === "BINARY_SOURCE_NOT_EXPOSED").length, 8);
  assert.equal(result.invariants.routeMutations, 0);
});

test("live execution requires current authenticated bridge health", () => {
  assert.throws(
    () => createDiscoverArtifactsCommand({
      connectorBuildId: CONNECTOR_BUILD,
      healthReceipt: health(false),
      executionClass: "LIVE_BRIDGE",
      projectSelector: "310224",
      track: "IMPLEMENTATION",
      clock: issuedClock,
      nonce
    }),
    (error) => error instanceof DiscoverCommandError && error.code === "DISCOVERY_LIVE_HEALTH_REQUIRED"
  );
  const value = createDiscoverArtifactsCommand({
    connectorBuildId: CONNECTOR_BUILD,
    healthReceipt: health(true),
    executionClass: "LIVE_BRIDGE",
    projectSelector: "310224",
    track: "IMPLEMENTATION",
    clock: issuedClock,
    nonce
  });
  assert.equal(value.scope.pageContext, "CURRENT_PAGE_ONLY");
  assert.equal(value.restrictions.controlsClicked, 0);
});

test("offline fixtures cannot be promoted to live evidence", async () => {
  const snapshot = await fixture("310224-failed-direct-get.json");
  const command = commandFor("310224", "IMPLEMENTATION");
  assert.throws(
    () => validateDiscoverArtifactsResponse({
      command,
      response: responseFor(command, snapshot),
      observedVia: "LIVE_BRIDGE_TOOL",
      clock: observedClock
    }),
    (error) => error.code === "DISCOVERY_OBSERVATION_CLASS_MISMATCH"
  );
});

test("rejects clicks, route mutations, MySMIS writes and unsafe methods", async () => {
  const snapshot = await fixture("310224-failed-direct-get.json");
  const command = commandFor("310224", "IMPLEMENTATION");
  for (const overrides of [
    { safety: { ...responseFor(command, snapshot).safety, controlsClicked: 1 } },
    { safety: { ...responseFor(command, snapshot).safety, routeMutations: 1 } },
    { safety: { ...responseFor(command, snapshot).safety, mysmisWrites: 1 } },
    { methodsObserved: ["GET", "POST"] }
  ]) {
    assert.throws(
      () => validateDiscoverArtifactsResponse({
        command,
        response: responseFor(command, snapshot, overrides),
        observedVia: "OFFLINE_FIXTURE",
        clock: observedClock
      }),
      (error) => ["DISCOVERY_SAFETY_GATE_FAILED", "DISCOVERY_UNSAFE_METHOD_OBSERVED"].includes(error.code)
    );
  }
});

test("rejects incomplete inventories and mismatched benchmark separation", async () => {
  const snapshot = await fixture("367944-schema-discovery.json");
  const command = commandFor("367944", "WRITING");
  assert.throws(
    () => validateDiscoverArtifactsResponse({
      command,
      response: responseFor(command, snapshot, { reportedCandidateCount: 9 }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "DISCOVERY_INVENTORY_INCOMPLETE"
  );
  assert.throws(
    () => validateDiscoverArtifactsResponse({
      command,
      response: responseFor(command, { ...snapshot, project: { code: "310224", track: "IMPLEMENTATION" } }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "DISCOVERY_PROJECT_MISMATCH"
  );
});

test("rejects sensitive response fields before evidence can be persisted", async () => {
  const snapshot = await fixture("310224-failed-direct-get.json");
  const command = commandFor("310224", "IMPLEMENTATION");
  assert.throws(
    () => validateDiscoverArtifactsResponse({
      command,
      response: responseFor(command, snapshot, { authorization: "denied" }),
      observedVia: "OFFLINE_FIXTURE",
      clock: observedClock
    }),
    (error) => error.code === "SENSITIVE_PERSISTENCE_DENIED"
  );
});
