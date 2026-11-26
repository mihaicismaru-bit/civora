import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { createBridgeHealthChallenge, READ_ONLY_BRIDGE_CAPABILITIES } from "../core/bridge-health.mjs";
import { createExtensionLoopbackClient } from "../extension/loopback-client.mjs";
import {
  createMclenovoRuntime,
  createMclenovoRuntimeHandoffPlan,
  MclenovoRuntimeError,
  verifyMclenovoRuntimeHandoffPlan
} from "../native/mclenovo-runtime.mjs";
import { initializeDriveCommandMailbox, mailboxCommandFileName } from "../native/drive-command-mailbox.mjs";

const BUILD = "3".repeat(40);
const PAIR_ID = "4".repeat(64);
const EXTENSION_ID = "b".repeat(32);
const NOW = new Date("2026-08-30T09:20:20.000Z");
const clock = () => new Date(NOW);

function plan() {
  return createMclenovoRuntimeHandoffPlan({ sourceHead: BUILD, pairId: PAIR_ID, extensionId: EXTENSION_ID });
}

function challenge() {
  return createBridgeHealthChallenge({
    connectorBuildId: BUILD,
    clock: () => new Date("2026-08-30T09:20:00.000Z"),
    nonce: "5".repeat(64)
  });
}

function healthResponse(command) {
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    challengeId: command.challengeId,
    nonceEcho: command.nonce,
    targetLabel: command.targetLabel,
    connectorBuildId: BUILD,
    agentBuildId: BUILD,
    respondedAt: NOW.toISOString(),
    capabilities: READ_ONLY_BRIDGE_CAPABILITIES.map((name) => ({
      name,
      mode: name.startsWith("OBSERVE_") ? "OBSERVE" : "READ_ONLY"
    })),
    runtime: {
      browserFamily: "EDGE",
      manifestVersion: 3,
      extensionReady: true,
      nativeAgentReady: true,
      authenticatedSessionPresent: false,
      mysmisOriginPresent: false
    },
    safety: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false
    }
  };
}

async function waitForOutstanding(runtime, commandId) {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (runtime.status().broker.outstandingCommandId === commandId) return;
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
  assert.fail("mailbox command was not delivered to the bounded broker");
}

test("handoff plan is deterministic, path-free and not live acceptance", () => {
  const first = plan();
  const second = plan();
  assert.deepEqual(first, second);
  assert.match(first.planId, /^[a-f0-9]{64}$/u);
  assert.match(first.extensionConfig.configurationId, /^[a-f0-9]{64}$/u);
  assert.equal(first.extensionConfig.brokerOrigin, "http://127.0.0.1:43127");
  assert.equal(first.safety.liveEvidenceAccepted, false);
  assert.equal(JSON.stringify(first).includes("mailboxRoot"), false);
});

test("tampered, mixed-build and widened plans fail before runtime start", () => {
  assert.throws(
    () => verifyMclenovoRuntimeHandoffPlan({ ...plan(), sourceHead: "6".repeat(40) }),
    (error) => error instanceof MclenovoRuntimeError && error.code === "MCLENOVO_RUNTIME_PLAN_TAMPERED"
  );
  assert.throws(
    () => verifyMclenovoRuntimeHandoffPlan({ ...plan(), command: "shell" }),
    (error) => error.code === "MCLENOVO_RUNTIME_PLAN_TAMPERED"
  );
  assert.throws(
    () => createMclenovoRuntime({ plan: plan(), mailboxRoot: "relative/path" }),
    (error) => error.code === "MCLENOVO_MAILBOX_ROOT_INVALID"
  );
});

test("full offline bridge composes Drive mailbox to broker to extension and back", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "mclenovo-runtime-"));
  const paths = await initializeDriveCommandMailbox(root);
  const command = challenge();
  await writeFile(path.join(paths.inbox, mailboxCommandFileName(command)), `${JSON.stringify(command)}\n`, "utf8");

  const runtime = createMclenovoRuntime({ plan: plan(), mailboxRoot: root, clock });
  await runtime.start({ continuous: false });
  const mailboxPromise = runtime.runOnce();
  await waitForOutstanding(runtime, command.challengeId);

  const client = createExtensionLoopbackClient({
    sourceHead: BUILD,
    extensionId: EXTENSION_ID,
    dispatch: async (value) => healthResponse(value),
    clock
  });
  const clientReceipt = await client.pollOnce();
  const cycle = await mailboxPromise;
  assert.equal(clientReceipt.status, "MV3_LOOPBACK_RESULT_ACKNOWLEDGED_PENDING_DRIVE_READBACK");
  assert.equal(clientReceipt.liveEvidenceAccepted, false);
  assert.equal(cycle.outcomes[0].status, "DRIVE_MAILBOX_COMMAND_COMPLETED");

  const names = await readdir(paths.outbox);
  assert.deepEqual(names, [`${command.challengeId}.result.json`]);
  const result = JSON.parse(await readFile(path.join(paths.outbox, names[0]), "utf8"));
  assert.equal(result.response.challengeId, command.challengeId);
  assert.equal(result.liveEvidenceAccepted, false);
  assert.equal(result.safety.mysmisWrites, 0);
  assert.equal(runtime.status().mailboxRootPersisted, false);
  await runtime.stop();
  assert.equal(runtime.status().status, "MCLENOVO_RUNTIME_STOPPED");
});

test("runtime refuses mailbox processing before bounded broker start", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "mclenovo-runtime-stopped-"));
  const runtime = createMclenovoRuntime({ plan: plan(), mailboxRoot: root, clock });
  await assert.rejects(() => runtime.runOnce(), (error) => error.code === "MCLENOVO_RUNTIME_NOT_STARTED");
});

test("runtime CLI rejects incomplete arguments without echoing paths or starting", () => {
  const cli = path.resolve("native/mclenovo-runtime-cli.mjs");
  const result = spawnSync(process.execPath, [cli, "--plan", "C:\\private\\plan.json"], { encoding: "utf8" });
  assert.equal(result.status, 1);
  const receipt = JSON.parse(result.stdout);
  assert.equal(receipt.status, "MCLENOVO_RUNTIME_START_REJECTED");
  assert.equal(receipt.runtimeStarted, false);
  assert.doesNotMatch(result.stdout, /private|plan\.json/iu);
});

test("options page has one bounded user action and no network or browser-control primitive", async () => {
  const html = await readFile(new URL("../extension/options.html", import.meta.url), "utf8");
  const script = await readFile(new URL("../extension/options.js", import.meta.url), "utf8");
  const manifest = JSON.parse(await readFile(new URL("../manifest.json", import.meta.url), "utf8"));
  assert.equal(manifest.options_page, "extension/options.html");
  assert.match(html, /type="button"/u);
  assert.doesNotMatch(html, /type="submit"|<form/iu);
  assert.doesNotMatch(script, /fetch\s*\(|XMLHttpRequest|WebSocket|\.click\s*\(|location\.|tabs\.|scripting\.|debugger/iu);
  assert.match(script, /chrome\.storage\.local\.set/u);
});

