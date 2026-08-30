import assert from "node:assert/strict";
import test from "node:test";

import { createLoopbackBroker, LoopbackBrokerError } from "../native/loopback-broker.mjs";

const SOURCE_HEAD = "a".repeat(40);
const COMMAND_ID = "b".repeat(64);
const NONCE = "c".repeat(64);

function healthCommand(overrides = {}) {
  const now = Date.now();
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    intent: "HEALTH_CHECK_ONLY",
    challengeId: COMMAND_ID,
    targetLabel: "MCLENOVO",
    connectorBuildId: SOURCE_HEAD,
    issuedAt: new Date(now - 1_000).toISOString(),
    expiresAt: new Date(now + 30_000).toISOString(),
    nonce: NONCE,
    restrictions: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0
    },
    ...overrides
  };
}

function safeEnvelope(command, response = { ok: true }) {
  return {
    schemaVersion: 1,
    source: "MV3_EXTENSION_LOOPBACK",
    commandId: command.challengeId,
    operation: "HEALTH",
    connectorBuildId: SOURCE_HEAD,
    nonceEcho: command.nonce,
    response,
    safety: {
      readOnly: true,
      mysmisWrites: 0,
      controlsClicked: 0,
      arbitraryShell: false,
      browserSecretsRead: false
    }
  };
}

async function withBroker(fn) {
  const broker = createLoopbackBroker({ sourceHead: SOURCE_HEAD, port: 0, maxWaitMs: 5_000 });
  const bound = await broker.start();
  try {
    await fn(broker, `http://${bound.host}:${bound.port}`);
  } finally {
    await broker.stop();
  }
}

test("refuses non-loopback bind addresses", () => {
  assert.throws(
    () => createLoopbackBroker({ sourceHead: SOURCE_HEAD, host: "0.0.0.0" }),
    (error) => error instanceof LoopbackBrokerError && error.code === "LOOPBACK_PUBLIC_BIND_DENIED"
  );
});

test("starts on loopback only with zero-shell safety state", async () => {
  await withBroker(async (broker, baseUrl) => {
    assert.match(baseUrl, /^http:\/\/127\.0\.0\.1:\d+$/u);
    const status = broker.status();
    assert.equal(status.state, "LISTENING_LOOPBACK_ONLY");
    assert.equal(status.host, "127.0.0.1");
    assert.equal(status.safety.publicPortOpened, false);
    assert.equal(status.safety.arbitraryShell, false);
    assert.equal(status.safety.childProcessesSpawned, 0);
  });
});

test("relays one exact HEALTH command and accepts only its bound result", async () => {
  await withBroker(async (broker, baseUrl) => {
    const command = healthCommand();
    const pending = broker.dispatch(command);

    const next = await fetch(`${baseUrl}/v1/next`);
    assert.equal(next.status, 200);
    const delivery = await next.json();
    assert.equal(delivery.source, "MCLENOVO_LOCAL_AGENT");
    assert.equal(delivery.commandId, COMMAND_ID);
    assert.equal(delivery.operation, "HEALTH");
    assert.deepEqual(delivery.command, command);
    assert.equal(delivery.safety.publicPortOpened, false);

    const noSecondDelivery = await fetch(`${baseUrl}/v1/next`);
    assert.equal(noSecondDelivery.status, 204);

    const expectedResponse = { health: "OBSERVED_READ_ONLY" };
    const result = await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(safeEnvelope(command, expectedResponse))
    });
    assert.equal(result.status, 200);
    assert.deepEqual(await pending, expectedResponse);
    assert.equal(broker.status().outstandingCommandId, null);
  });
});

test("rejects result nonce/build binding mismatch without resolving the command", async () => {
  await withBroker(async (broker, baseUrl) => {
    const command = healthCommand();
    const pending = broker.dispatch(command);
    await fetch(`${baseUrl}/v1/next`);

    const bad = safeEnvelope(command);
    bad.nonceEcho = "d".repeat(64);
    const rejected = await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(bad)
    });
    assert.equal(rejected.status, 400);
    assert.equal((await rejected.json()).error.code, "LOOPBACK_RESULT_BINDING_MISMATCH");
    assert.equal(broker.status().outstandingCommandId, COMMAND_ID);

    await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(safeEnvelope(command, { recovered: true }))
    });
    assert.deepEqual(await pending, { recovered: true });
  });
});

test("denies a second outstanding command and unsafe command restrictions", async () => {
  await withBroker(async (broker, baseUrl) => {
    const first = healthCommand();
    const pending = broker.dispatch(first);
    await assert.rejects(
      broker.dispatch(healthCommand({ challengeId: "e".repeat(64), nonce: "f".repeat(64) })),
      (error) => error.code === "LOOPBACK_BUSY"
    );
    await fetch(`${baseUrl}/v1/next`);
    await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(safeEnvelope(first))
    });
    await pending;

    await assert.rejects(
      broker.dispatch(healthCommand({ restrictions: {
        readOnly: true,
        arbitraryShell: true,
        mysmisWrites: 0,
        controlsClicked: 0
      } })),
      (error) => error.code === "LOOPBACK_SAFETY_INVALID"
    );
  });
});

test("rejects sensitive result fields and exposes no arbitrary endpoint", async () => {
  await withBroker(async (broker, baseUrl) => {
    const command = healthCommand();
    const pending = broker.dispatch(command);
    await fetch(`${baseUrl}/v1/next`);
    const sensitive = safeEnvelope(command);
    sensitive.token = "must-not-be-accepted";
    const response = await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(sensitive)
    });
    assert.equal(response.status, 400);
    assert.equal((await response.json()).error.code, "LOOPBACK_REJECTED");

    const arbitrary = await fetch(`${baseUrl}/v1/shell`, { method: "POST", body: "{}" });
    assert.equal(arbitrary.status, 404);

    await fetch(`${baseUrl}/v1/result`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(safeEnvelope(command))
    });
    await pending;
  });
});
