import assert from "node:assert/strict";
import test from "node:test";
import { createBridgeHealthChallenge, READ_ONLY_BRIDGE_CAPABILITIES } from "../core/bridge-health.mjs";
import { createDiscoverArtifactsCommand } from "../core/discover-command.mjs";
import { createLiveExtensionDispatcher } from "../extension/live-runtime.mjs";

const BUILD = "4".repeat(40);
const NOW = new Date("2026-08-30T08:00:20.000Z");
const issuedClock = () => new Date("2026-08-30T08:00:00.000Z");
const dispatchClock = () => new Date(NOW);

function storageSession(initial = {}) {
  const state = structuredClone(initial);
  return {
    state,
    async get(key) { return { [key]: structuredClone(state[key]) }; },
    async set(values) { Object.assign(state, structuredClone(values)); }
  };
}

function snapshot(project = "310224", url = `https://mysmis2021.gov.ro/proiect/${project}`) {
  return {
    capture: { id: "live-current-page", kind: "LIVE_DOM_READ_ONLY" },
    project: null,
    page: { url: `${url}?token=secret&view=documents`, title: `Proiect ${project}` },
    elements: [{
      tag: "a",
      text: `Descarcă raport proiect ${project}`,
      href: `https://mysmis2021.gov.ro/files/${project}/raport.pdf?access_token=secret`,
      method: "GET",
      download: true
    }],
    invariants: { controlsClicked: 0, routeMutations: 0, formSubmissions: 0 }
  };
}

function chromeRuntime({ currentSnapshot = snapshot(), session = storageSession(), tabUrl } = {}) {
  return {
    storage: { session },
    tabs: {
      async query() {
        return tabUrl === null ? [] : [{ id: 17, url: tabUrl || currentSnapshot.page.url }];
      },
      async sendMessage(id, message) {
        assert.equal(id, 17);
        assert.deepEqual(message, { type: "MYSMIS_CAPTURE_CURRENT_PAGE" });
        return { ok: true, snapshot: structuredClone(currentSnapshot) };
      }
    }
  };
}

function challenge(nonce = "11".repeat(32)) {
  return createBridgeHealthChallenge({ connectorBuildId: BUILD, clock: issuedClock, nonce });
}

function liveHealthReceipt(value) {
  return {
    schemaVersion: 1,
    status: "BRIDGE_HEALTH_LIVE_VERIFIED",
    liveVerified: true,
    challengeId: value.challengeId,
    connectorBuildId: BUILD,
    capabilities: [...READ_ONLY_BRIDGE_CAPABILITIES],
    runtime: { authenticatedSessionPresent: true, mysmisOriginPresent: true },
    safety: { readOnly: true, mysmisWrites: 0, controlsClicked: 0, arbitraryShell: false }
  };
}

test("live HEALTH reads only the active MySMIS page and reports an authenticated project context", async () => {
  const dispatch = createLiveExtensionDispatcher({
    chromeApi: chromeRuntime(), sourceHead: BUILD, clock: dispatchClock, userAgent: "Edg/140"
  });
  const response = await dispatch(challenge());
  assert.equal(response.runtime.browserFamily, "EDGE");
  assert.equal(response.runtime.authenticatedSessionPresent, true);
  assert.equal(response.runtime.mysmisOriginPresent, true);
  assert.equal(response.capabilities.length, READ_ONLY_BRIDGE_CAPABILITIES.length);
  assert.equal(response.safety.mysmisWrites, 0);
});

test("DISCOVER_ARTIFACTS binds the visible project and removes sensitive query values", async () => {
  const health = challenge();
  const command = createDiscoverArtifactsCommand({
    connectorBuildId: BUILD,
    healthReceipt: liveHealthReceipt(health),
    executionClass: "LIVE_BRIDGE",
    projectSelector: "310224",
    track: "IMPLEMENTATION",
    clock: issuedClock,
    nonce: "22".repeat(32)
  });
  const dispatch = createLiveExtensionDispatcher({ chromeApi: chromeRuntime(), sourceHead: BUILD, clock: dispatchClock });
  const response = await dispatch(command);
  assert.equal(response.snapshot.project.code, "310224");
  assert.equal(response.snapshot.project.track, "IMPLEMENTATION");
  assert.equal(response.reportedCandidateCount, 1);
  assert.doesNotMatch(JSON.stringify(response), /secret|access_token|token=/u);
  assert.deepEqual(response.methodsObserved, ["GET"]);
  assert.equal(response.safety.controlsClicked, 0);
  assert.equal(response.safety.routeMutations, 0);
});

test("project mismatch and absence of an active MySMIS page fail closed", async () => {
  const health = challenge("33".repeat(32));
  const command = createDiscoverArtifactsCommand({
    connectorBuildId: BUILD,
    healthReceipt: liveHealthReceipt(health),
    executionClass: "LIVE_BRIDGE",
    projectSelector: "367944",
    track: "WRITING",
    clock: issuedClock,
    nonce: "44".repeat(32)
  });
  const mismatch = createLiveExtensionDispatcher({ chromeApi: chromeRuntime(), sourceHead: BUILD, clock: dispatchClock });
  await assert.rejects(() => mismatch(command), (error) => error.code === "MV3_PROJECT_CONTEXT_UNPROVEN");

  const absent = createLiveExtensionDispatcher({
    chromeApi: chromeRuntime({ tabUrl: null }), sourceHead: BUILD, clock: dispatchClock
  });
  await assert.rejects(() => absent({ ...command, commandId: "a".repeat(64), nonce: "55".repeat(32) }),
    (error) => error.code === "MV3_MYSMIS_PAGE_UNAVAILABLE");
});

test("login-like route never claims an authenticated project session", async () => {
  const loginSnapshot = snapshot("310224", "https://mysmis2021.gov.ro/login");
  const dispatch = createLiveExtensionDispatcher({
    chromeApi: chromeRuntime({ currentSnapshot: loginSnapshot }), sourceHead: BUILD, clock: dispatchClock
  });
  const response = await dispatch(challenge("66".repeat(32)));
  assert.equal(response.runtime.mysmisOriginPresent, true);
  assert.equal(response.runtime.authenticatedSessionPresent, false);
});

test("replay claims survive recreation of the MV3 service worker", async () => {
  const session = storageSession();
  const chromeApi = chromeRuntime({ session });
  await createLiveExtensionDispatcher({ chromeApi, sourceHead: BUILD, clock: dispatchClock })(challenge("77".repeat(32)));
  const restarted = createLiveExtensionDispatcher({ chromeApi, sourceHead: BUILD, clock: dispatchClock });
  await assert.rejects(() => restarted(challenge("77".repeat(32))), (error) => error.code === "BRIDGE_REPLAY_DENIED");
});

