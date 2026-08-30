import assert from "node:assert/strict";
import test from "node:test";

import { createExtensionLoopbackClient, ExtensionLoopbackError } from "../extension/loopback-client.mjs";

const SOURCE_HEAD = "a".repeat(40);
const EXTENSION_ID = "a".repeat(32);
const COMMAND_ID = "b".repeat(64);
const NONCE = "c".repeat(64);
const NOW = new Date("2026-08-30T08:00:00.000Z");
const clock = () => new Date(NOW);

function command(overrides = {}) {
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    intent: "HEALTH_CHECK_ONLY",
    challengeId: COMMAND_ID,
    targetLabel: "MCLENOVO",
    connectorBuildId: SOURCE_HEAD,
    issuedAt: "2026-08-30T07:59:00.000Z",
    expiresAt: "2026-08-30T08:01:00.000Z",
    nonce: NONCE,
    restrictions: { readOnly: true, arbitraryShell: false, mysmisWrites: 0, controlsClicked: 0 },
    ...overrides
  };
}

function delivery(overrides = {}) {
  const value = command();
  return {
    schemaVersion: 1,
    source: "MCLENOVO_LOCAL_AGENT",
    extensionId: EXTENSION_ID,
    commandId: COMMAND_ID,
    operation: "HEALTH",
    connectorBuildId: SOURCE_HEAD,
    deliveredAt: NOW.toISOString(),
    command: value,
    safety: {
      readOnly: true,
      mysmisWrites: 0,
      controlsClicked: 0,
      arbitraryShell: false,
      publicPortOpened: false
    },
    ...overrides
  };
}

function jsonResponse(value, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" }
  });
}

test("requires fixed loopback origin, exact build and installed extension ID", () => {
  const valid = { sourceHead: SOURCE_HEAD, extensionId: EXTENSION_ID, dispatch: async () => ({}) };
  assert.throws(
    () => createExtensionLoopbackClient({ ...valid, brokerOrigin: "http://localhost:43127" }),
    (error) => error instanceof ExtensionLoopbackError && error.code === "MV3_LOOPBACK_ORIGIN_DENIED"
  );
  assert.throws(
    () => createExtensionLoopbackClient({ ...valid, extensionId: "invalid" }),
    (error) => error.code === "MV3_LOOPBACK_EXTENSION_ID_INVALID"
  );
});

test("polls with credentials omitted and posts one bound dispatcher response", async () => {
  const calls = [];
  const expectedResponse = { bounded: "READ_ONLY" };
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    if (calls.length === 1) return jsonResponse(delivery());
    const envelope = JSON.parse(options.body);
    assert.equal(envelope.source, "MV3_EXTENSION_LOOPBACK");
    assert.equal(envelope.extensionId, EXTENSION_ID);
    assert.equal(envelope.commandId, COMMAND_ID);
    assert.deepEqual(envelope.response, expectedResponse);
    assert.equal(envelope.safety.browserSecretsRead, false);
    return jsonResponse({ ok: true, commandId: COMMAND_ID });
  };
  const client = createExtensionLoopbackClient({
    sourceHead: SOURCE_HEAD,
    extensionId: EXTENSION_ID,
    dispatch: async () => expectedResponse,
    fetchImpl,
    clock
  });
  const result = await client.pollOnce();
  assert.equal(result.status, "MV3_LOOPBACK_RESULT_ACKNOWLEDGED_PENDING_DRIVE_READBACK");
  assert.equal(result.liveEvidenceAccepted, false);
  assert.equal(calls.length, 2);
  assert.match(calls[0].url, /^http:\/\/127\.0\.0\.1:43127\/v1\/next\?extensionId=/u);
  assert.match(calls[1].url, /^http:\/\/127\.0\.0\.1:43127\/v1\/result\?extensionId=/u);
  assert.equal(calls[0].options.credentials, "omit");
  assert.equal(calls[1].options.credentials, "omit");
  assert.equal(calls[0].options.redirect, "error");
});

test("204 response performs no dispatch and no POST", async () => {
  let calls = 0;
  const client = createExtensionLoopbackClient({
    sourceHead: SOURCE_HEAD,
    extensionId: EXTENSION_ID,
    dispatch: async () => assert.fail("no command must not dispatch"),
    fetchImpl: async () => { calls += 1; return new Response(null, { status: 204 }); },
    clock
  });
  assert.equal((await client.pollOnce()).status, "MV3_LOOPBACK_NO_COMMAND");
  assert.equal(calls, 1);
});

test("wrong extension, build and unknown delivery fields fail before dispatch", async () => {
  for (const invalid of [
    delivery({ extensionId: "b".repeat(32) }),
    delivery({ connectorBuildId: "d".repeat(40) }),
    delivery({ extra: "denied" })
  ]) {
    let dispatches = 0;
    const client = createExtensionLoopbackClient({
      sourceHead: SOURCE_HEAD,
      extensionId: EXTENSION_ID,
      dispatch: async () => { dispatches += 1; },
      fetchImpl: async () => jsonResponse(invalid),
      clock
    });
    assert.equal((await client.pollOnce()).status, "MV3_LOOPBACK_DELIVERY_REJECTED");
    assert.equal(dispatches, 0);
  }
});

test("sensitive or stale deliveries fail closed", async () => {
  const sensitive = delivery();
  sensitive.token = "denied";
  const stale = delivery({ deliveredAt: "2026-08-30T08:02:00.000Z" });
  for (const invalid of [sensitive, stale]) {
    const client = createExtensionLoopbackClient({
      sourceHead: SOURCE_HEAD,
      extensionId: EXTENSION_ID,
      dispatch: async () => assert.fail("invalid delivery must not dispatch"),
      fetchImpl: async () => jsonResponse(invalid),
      clock
    });
    const result = await client.pollOnce();
    assert.equal(result.status, "MV3_LOOPBACK_DELIVERY_REJECTED");
    assert.equal(result.liveEvidenceAccepted, false);
  }
});

test("dispatcher rejection is not POSTed or promoted", async () => {
  let calls = 0;
  const client = createExtensionLoopbackClient({
    sourceHead: SOURCE_HEAD,
    extensionId: EXTENSION_ID,
    dispatch: async () => { const error = new Error("private"); error.code = "BRIDGE_REPLAY_DENIED"; throw error; },
    fetchImpl: async () => { calls += 1; return jsonResponse(delivery()); },
    clock
  });
  const result = await client.pollOnce();
  assert.equal(result.status, "MV3_LOOPBACK_DISPATCH_REJECTED");
  assert.equal(result.errorCode, "BRIDGE_REPLAY_DENIED");
  assert.equal(result.liveEvidenceAccepted, false);
  assert.equal(calls, 1);
});

test("broker network failure is sanitized", async () => {
  const client = createExtensionLoopbackClient({
    sourceHead: SOURCE_HEAD,
    extensionId: EXTENSION_ID,
    dispatch: async () => ({}),
    fetchImpl: async () => { throw new Error("private network path"); },
    clock
  });
  assert.deepEqual(await client.pollOnce(), {
    status: "MV3_LOOPBACK_BROKER_UNAVAILABLE",
    liveEvidenceAccepted: false
  });
});
