import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  ChromeSessionReplayStore,
  createInternalCommandHandler,
  installInternalCommandTransport
} from "../extension/internal-transport.mjs";
import { captureCurrentPageSnapshot } from "../extension/page-snapshot.mjs";
import { createFixedBridgeDispatcher } from "../core/bridge-dispatcher.mjs";
import {
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES
} from "../core/bridge-health.mjs";

const BUILD = "9293e34cb0310d55b08a907774419f1bc259cbdb";
const AGENT = "5".repeat(40);
const RUNTIME_ID = "internal-extension-id";
const issuedClock = () => new Date("2026-08-29T17:20:00.000Z");
const dispatchClock = () => new Date("2026-08-29T17:20:20.000Z");

function createStorageSession(initial = {}) {
  const state = structuredClone(initial);
  return {
    state,
    async get(key) {
      return { [key]: structuredClone(state[key]) };
    },
    async set(values) {
      Object.assign(state, structuredClone(values));
    }
  };
}

function healthPayload() {
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
    }
  };
}

function challenge() {
  return createBridgeHealthChallenge({
    connectorBuildId: BUILD,
    clock: issuedClock,
    nonce: "56".repeat(32)
  });
}

function fixedDispatcher(replayStore) {
  return createFixedBridgeDispatcher({
    connectorBuildId: BUILD,
    agentBuildId: AGENT,
    replayStore,
    clock: dispatchClock,
    healthHandler: async () => healthPayload(),
    discoverHandler: async () => ({
      snapshot: { project: null, page: {}, elements: [] },
      reportedCandidateCount: 0,
      methodsObserved: []
    })
  });
}

test("same-extension sender reaches only the injected fixed dispatcher", async () => {
  const storage = createStorageSession();
  const dispatch = fixedDispatcher(new ChromeSessionReplayStore({ storageSession: storage }));
  const handle = createInternalCommandHandler({ runtimeId: RUNTIME_ID, dispatch });
  const result = await handle(
    { type: "MYSMIS_BRIDGE_COMMAND", command: challenge() },
    { id: RUNTIME_ID }
  );
  assert.equal(result.ok, true);
  assert.equal(result.response.challengeId, challenge().challengeId);
  assert.equal(result.response.safety.mysmisWrites, 0);
});

test("external and malformed senders fail before dispatch", async () => {
  let calls = 0;
  const handle = createInternalCommandHandler({
    runtimeId: RUNTIME_ID,
    dispatch: async () => { calls += 1; }
  });
  const external = await handle(
    { type: "MYSMIS_BRIDGE_COMMAND", command: challenge() },
    { id: "another-extension" }
  );
  const malformed = await handle({ type: "ANYTHING" }, { id: RUNTIME_ID });
  assert.equal(external.ok, false);
  assert.equal(external.error.code, "MV3_EXTERNAL_SENDER_DENIED");
  assert.equal(malformed.error.code, "MV3_MESSAGE_TYPE_DENIED");
  assert.equal(calls, 0);
});

test("chrome.storage.session replay claim survives a service-worker restart", async () => {
  const storage = createStorageSession();
  const first = fixedDispatcher(new ChromeSessionReplayStore({ storageSession: storage }));
  const second = fixedDispatcher(new ChromeSessionReplayStore({ storageSession: storage }));
  await first(challenge());
  await assert.rejects(
    () => second(challenge()),
    (error) => error.code === "BRIDGE_REPLAY_DENIED"
  );
});

test("concurrent duplicate claims serialize to one winner", async () => {
  const storage = createStorageSession();
  const replay = new ChromeSessionReplayStore({ storageSession: storage });
  const results = await Promise.all([
    replay.claim("same-id", Date.parse("2026-08-29T17:22:00.000Z"), Date.parse("2026-08-29T17:20:00.000Z")),
    replay.claim("same-id", Date.parse("2026-08-29T17:22:00.000Z"), Date.parse("2026-08-29T17:20:00.000Z"))
  ]);
  assert.deepEqual(results.sort(), [false, true]);
});

test("current-page snapshot only reads bounded artifact fields and never invokes controls", () => {
  let clickCalls = 0;
  let submitCalls = 0;
  const element = {
    tagName: "BUTTON",
    innerText: "Descarcă formular",
    method: "GET",
    click() { clickCalls += 1; },
    submit() { submitCalls += 1; },
    getAttribute(name) { return name === "aria-label" ? "Download" : null; },
    hasAttribute() { return false; }
  };
  const documentLike = {
    title: "MySMIS page",
    querySelectorAll() { return [element]; }
  };
  const snapshot = captureCurrentPageSnapshot({
    documentLike,
    locationLike: { href: "https://mysmis2021.gov.ro/project/example" },
    captureId: "capture-test"
  });
  assert.equal(snapshot.elements.length, 1);
  assert.equal(snapshot.elements[0].text, "Descarcă formular");
  assert.equal(snapshot.invariants.controlsClicked, 0);
  assert.equal(snapshot.invariants.routeMutations, 0);
  assert.equal(clickCalls, 0);
  assert.equal(submitCalls, 0);
});

test("installed transport ignores unrelated messages and returns bounded errors", async () => {
  let listener;
  const chromeApi = {
    runtime: {
      id: RUNTIME_ID,
      onMessage: {
        addListener(value) { listener = value; },
        removeListener() {}
      }
    }
  };
  installInternalCommandTransport({
    chromeApi,
    dispatch: async () => { throw Object.assign(new Error("denied"), { code: "EXPECTED_DENIAL" }); }
  });
  assert.equal(listener({ type: "UNRELATED" }, { id: RUNTIME_ID }, () => {}), false);
  const response = await new Promise((resolve) => {
    assert.equal(listener(
      { type: "MYSMIS_BRIDGE_COMMAND", command: challenge() },
      { id: RUNTIME_ID },
      resolve
    ), true);
  });
  assert.deepEqual(response, { ok: false, error: { code: "EXPECTED_DENIAL", message: "denied" } });
  assert.equal("stack" in response.error, false);
});

test("manifest and content script add no native, external, debugger or click capability", async () => {
  const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));
  const contentScript = await readFile(new URL("../extension/content-script.js", import.meta.url), "utf8");
  assert.equal(manifest.permissions.includes("nativeMessaging"), false);
  assert.equal(manifest.permissions.includes("debugger"), false);
  assert.equal(Object.hasOwn(manifest, "externally_connectable"), false);
  assert.doesNotMatch(contentScript, /\.click\s*\(/u);
  assert.doesNotMatch(contentScript, /\.submit\s*\(/u);
  assert.doesNotMatch(contentScript, /location\.(?:assign|replace)\s*\(/u);
});
