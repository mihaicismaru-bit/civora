import assert from "node:assert/strict";
import { cp, lstat, mkdtemp, readFile, readdir, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  DRIVE_MAILBOX_LAYOUT,
  DriveCommandMailboxError,
  initializeDriveCommandMailbox,
  mailboxCommandFileName,
  runDriveCommandMailboxCycle,
  startDriveCommandMailboxPoller,
  validateDriveMailboxCommand
} from "../native/drive-command-mailbox.mjs";

const SOURCE_HEAD = "8a6506b3a9bfed0b00f716ff0e1bc2eb893f5416";
const COMMAND_ID = "a".repeat(64);
const NOW = new Date("2026-08-30T07:00:00.000Z");
const clock = () => new Date(NOW);

function healthCommand(overrides = {}) {
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    intent: "HEALTH_CHECK_ONLY",
    challengeId: COMMAND_ID,
    targetLabel: "MCLENOVO",
    connectorBuildId: SOURCE_HEAD,
    issuedAt: "2026-08-30T06:59:00.000Z",
    expiresAt: "2026-08-30T07:01:00.000Z",
    nonce: "b".repeat(64),
    requiredCapabilities: ["HEALTH"],
    restrictions: {
      readOnly: true,
      arbitraryShell: false,
      mysmisWrites: 0,
      controlsClicked: 0
    },
    ...overrides
  };
}

function healthResponse(command) {
  return {
    schemaVersion: 1,
    protocolVersion: 1,
    challengeId: command.challengeId,
    nonceEcho: command.nonce,
    targetLabel: "MCLENOVO",
    connectorBuildId: SOURCE_HEAD,
    agentBuildId: SOURCE_HEAD,
    respondedAt: NOW.toISOString(),
    capabilities: [{ name: "HEALTH", mode: "READ_ONLY" }],
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

async function mailbox() {
  const root = await mkdtemp(path.join(os.tmpdir(), "mysmis-mailbox-"));
  const paths = await initializeDriveCommandMailbox(root);
  return { root, paths };
}

async function putCommand(paths, command = healthCommand()) {
  const fileName = mailboxCommandFileName(command);
  await writeFile(path.join(paths.inbox, fileName), `${JSON.stringify(command)}\n`, "utf8");
  return fileName;
}

test("initializes the bounded Drive mailbox layout", async () => {
  const { paths } = await mailbox();
  assert.deepEqual(Object.keys(paths).sort(), Object.keys(DRIVE_MAILBOX_LAYOUT).sort());
  for (const directory of Object.values(paths)) assert.equal((await lstat(directory)).isDirectory(), true);
});

test("validates an exact-build HEALTH command", () => {
  const identity = validateDriveMailboxCommand({
    command: healthCommand(),
    sourceHead: SOURCE_HEAD,
    expectedCommandId: COMMAND_ID,
    clock
  });
  assert.equal(identity.operation, "HEALTH");
  assert.equal(identity.commandId, COMMAND_ID);
});

test("processes a create-only command and persists a non-promoted result", async () => {
  const { root, paths } = await mailbox();
  const command = healthCommand();
  const fileName = await putCommand(paths, command);
  let dispatches = 0;
  const receipt = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async (value) => {
      dispatches += 1;
      return healthResponse(value);
    }
  });
  assert.equal(dispatches, 1);
  assert.equal(receipt.outcomes[0].status, "DRIVE_MAILBOX_COMMAND_COMPLETED");
  const result = JSON.parse(await readFile(path.join(paths.outbox, `${COMMAND_ID}.result.json`), "utf8"));
  assert.equal(result.liveEvidenceAccepted, false);
  assert.equal(result.liveEvidenceGate, "REQUIRES_DRIVE_READBACK_AND_PROTOCOL_VALIDATION");
  assert.equal(result.safety.publicPortOpened, false);
  assert.equal(result.safety.childProcessesSpawned, 0);
  assert.equal((await lstat(path.join(paths.archive, fileName))).isFile(), true);
});

test("replay after restart does not dispatch or create a second result", async () => {
  const { root, paths } = await mailbox();
  const command = healthCommand();
  const fileName = await putCommand(paths, command);
  let dispatches = 0;
  const dispatch = async (value) => {
    dispatches += 1;
    return healthResponse(value);
  };
  await runDriveCommandMailboxCycle({ mailboxRoot: root, sourceHead: SOURCE_HEAD, clock, dispatch });
  await cp(path.join(paths.archive, fileName), path.join(paths.inbox, fileName));
  const replay = await runDriveCommandMailboxCycle({ mailboxRoot: root, sourceHead: SOURCE_HEAD, clock, dispatch });
  assert.equal(dispatches, 1);
  assert.equal(replay.outcomes[0].status, "REPLAY_ALREADY_PERSISTED");
  assert.deepEqual((await readdir(paths.outbox)).sort(), [`${COMMAND_ID}.result.json`]);
});

test("denies unknown operations before execution", () => {
  const command = {
    ...healthCommand({ intent: undefined, operation: "SAVE", commandId: COMMAND_ID })
  };
  assert.throws(
    () => validateDriveMailboxCommand({ command, sourceHead: SOURCE_HEAD, expectedCommandId: COMMAND_ID, clock }),
    (error) => error instanceof DriveCommandMailboxError && error.code === "MAILBOX_OPERATION_DENIED"
  );
});

test("denies exact-build mismatch and sensitive fields", () => {
  assert.throws(
    () => validateDriveMailboxCommand({
      command: healthCommand({ connectorBuildId: "c".repeat(40) }),
      sourceHead: SOURCE_HEAD,
      expectedCommandId: COMMAND_ID,
      clock
    }),
    (error) => error.code === "MAILBOX_BUILD_MISMATCH"
  );
  assert.throws(
    () => validateDriveMailboxCommand({
      command: healthCommand({ token: "denied" }),
      sourceHead: SOURCE_HEAD,
      expectedCommandId: COMMAND_ID,
      clock
    }),
    (error) => error.code === "SENSITIVE_PERSISTENCE_DENIED"
  );
});

test("malformed JSON is rejected with zero execution", async () => {
  const { root, paths } = await mailbox();
  await writeFile(path.join(paths.inbox, `${COMMAND_ID}.command.json`), "{", "utf8");
  let dispatches = 0;
  const cycle = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async () => { dispatches += 1; }
  });
  assert.equal(dispatches, 0);
  assert.equal(cycle.outcomes[0].errorCode, "MAILBOX_JSON_INVALID");
  const failure = JSON.parse(await readFile(path.join(paths.outbox, `${COMMAND_ID}.failure.json`), "utf8"));
  assert.equal(failure.executionAttempted, false);
});

test("an expired in-flight claim fails closed instead of replaying", async () => {
  const { root, paths } = await mailbox();
  const fileName = mailboxCommandFileName(healthCommand());
  await writeFile(path.join(paths.processing, fileName), JSON.stringify(healthCommand()), "utf8");
  await writeFile(path.join(paths.state, `${COMMAND_ID}.claim.json`), JSON.stringify({
    schemaVersion: 1,
    status: "DISPATCHING",
    commandId: COMMAND_ID,
    operation: "HEALTH",
    sourceHead: SOURCE_HEAD,
    claimedAt: "2026-08-30T06:55:00.000Z",
    leaseUntil: "2026-08-30T06:57:00.000Z"
  }), "utf8");
  let dispatches = 0;
  const cycle = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async () => { dispatches += 1; }
  });
  assert.equal(dispatches, 0);
  assert.equal(cycle.outcomes[0].errorCode, "MAILBOX_AMBIGUOUS_RESTART_REJECTED");
});

test("an active in-flight claim is left untouched", async () => {
  const { root, paths } = await mailbox();
  const fileName = mailboxCommandFileName(healthCommand());
  await writeFile(path.join(paths.processing, fileName), JSON.stringify(healthCommand()), "utf8");
  await writeFile(path.join(paths.state, `${COMMAND_ID}.claim.json`), JSON.stringify({
    schemaVersion: 1,
    status: "DISPATCHING",
    commandId: COMMAND_ID,
    operation: "HEALTH",
    sourceHead: SOURCE_HEAD,
    claimedAt: "2026-08-30T06:59:30.000Z",
    leaseUntil: "2026-08-30T07:00:30.000Z"
  }), "utf8");
  const cycle = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async () => assert.fail("active claims must not dispatch")
  });
  assert.equal(cycle.outcomes[0].status, "CLAIM_ACTIVE");
  assert.equal((await lstat(path.join(paths.processing, fileName))).isFile(), true);
});

test("concurrent cycles have one dispatch winner", async () => {
  const { root, paths } = await mailbox();
  await putCommand(paths);
  let dispatches = 0;
  const dispatch = async (command) => {
    dispatches += 1;
    await new Promise((resolve) => setTimeout(resolve, 20));
    return healthResponse(command);
  };
  await Promise.all([
    runDriveCommandMailboxCycle({ mailboxRoot: root, sourceHead: SOURCE_HEAD, clock, dispatch }),
    runDriveCommandMailboxCycle({ mailboxRoot: root, sourceHead: SOURCE_HEAD, clock, dispatch })
  ]);
  assert.equal(dispatches, 1);
});

test("sensitive executor responses are rejected and never promoted", async () => {
  const { root, paths } = await mailbox();
  await putCommand(paths);
  const cycle = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async () => ({ token: "denied" })
  });
  assert.equal(cycle.outcomes[0].errorCode, "MAILBOX_COMMAND_REJECTED");
  assert.equal(await readFile(path.join(paths.outbox, `${COMMAND_ID}.failure.json`), "utf8").then(Boolean), true);
});

test("poller refuses to start without an attested fixed dispatcher", async () => {
  const { root } = await mailbox();
  assert.throws(
    () => startDriveCommandMailboxPoller({ mailboxRoot: root, sourceHead: SOURCE_HEAD }),
    (error) => error.code === "MAILBOX_EXECUTOR_NOT_BOUND"
  );
});

test("unrecognized files are ignored instead of interpreted as commands", async () => {
  const { root, paths } = await mailbox();
  await writeFile(path.join(paths.inbox, "README.txt"), "not a command", "utf8");
  let dispatches = 0;
  const cycle = await runDriveCommandMailboxCycle({
    mailboxRoot: root,
    sourceHead: SOURCE_HEAD,
    clock,
    dispatch: async () => { dispatches += 1; }
  });
  assert.equal(dispatches, 0);
  assert.deepEqual(cycle.outcomes, []);
  assert.equal((await lstat(path.join(paths.inbox, "README.txt"))).isFile(), true);
});
