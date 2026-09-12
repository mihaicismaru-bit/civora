import { createHash } from "node:crypto";
import path from "node:path";

import { assertNoSensitivePersistence } from "../core/policy.mjs";
import {
  runDriveCommandMailboxCycle,
  startDriveCommandMailboxPoller
} from "./drive-command-mailbox.mjs";
import { createLoopbackBroker } from "./loopback-broker.mjs";

const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const EXTENSION_ID_PATTERN = /^[a-p]{32}$/u;
const HEX64_PATTERN = /^[a-f0-9]{64}$/u;
const BROKER_ORIGIN = "http://127.0.0.1:43127";
const BROKER_HOST = "127.0.0.1";
const BROKER_PORT = 43127;
const MAILBOX_POLL_INTERVAL_MS = 5_000;

export class MclenovoRuntimeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "MclenovoRuntimeError";
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

function configurationCore({ sourceHead, pairId, extensionId }) {
  return {
    schemaVersion: 1,
    enabled: true,
    sourceHead,
    agentBuildId: sourceHead,
    brokerOrigin: BROKER_ORIGIN,
    extensionId,
    pairId
  };
}

export function createMclenovoRuntimeHandoffPlan({ sourceHead, pairId, extensionId }) {
  if (!BUILD_PATTERN.test(sourceHead) || !HEX64_PATTERN.test(pairId) || !EXTENSION_ID_PATTERN.test(extensionId)) {
    throw new MclenovoRuntimeError(
      "MCLENOVO_RUNTIME_IDENTITY_INVALID",
      "Runtime handoff requires one exact source head, paired build and installed extension identity."
    );
  }
  const core = configurationCore({ sourceHead, pairId, extensionId });
  const extensionConfig = { ...core, configurationId: digest(core) };
  const planCore = {
    schemaVersion: 1,
    status: "MCLENOVO_RUNTIME_HANDOFF_VERIFIED_NOT_STARTED",
    sourceHead,
    pairId,
    extensionId,
    extensionConfig,
    agent: {
      brokerHost: BROKER_HOST,
      brokerPort: BROKER_PORT,
      mailboxPollIntervalMs: MAILBOX_POLL_INTERVAL_MS,
      allowedOperations: ["HEALTH", "DISCOVER_ARTIFACTS"]
    },
    safety: {
      mysmisAccessPerformed: false,
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false,
      arbitraryShell: false,
      publicPortOpened: false,
      nativeMessaging: false,
      liveEvidenceAccepted: false
    }
  };
  const plan = { ...planCore, planId: digest(planCore) };
  assertNoSensitivePersistence(plan);
  return Object.freeze(plan);
}

export function verifyMclenovoRuntimeHandoffPlan(plan) {
  if (!plan || plan.schemaVersion !== 1 || plan.status !== "MCLENOVO_RUNTIME_HANDOFF_VERIFIED_NOT_STARTED") {
    throw new MclenovoRuntimeError("MCLENOVO_RUNTIME_PLAN_INVALID", "A bounded not-started runtime plan is required.");
  }
  const expected = createMclenovoRuntimeHandoffPlan({
    sourceHead: plan.sourceHead,
    pairId: plan.pairId,
    extensionId: plan.extensionId
  });
  if (JSON.stringify(canonicalize(plan)) !== JSON.stringify(canonicalize(expected))) {
    throw new MclenovoRuntimeError("MCLENOVO_RUNTIME_PLAN_TAMPERED", "Runtime handoff plan does not match its exact identities.");
  }
  return expected;
}

export function createMclenovoRuntime({
  plan,
  mailboxRoot,
  clock = () => new Date(),
  brokerFactory = createLoopbackBroker,
  mailboxCycle = runDriveCommandMailboxCycle,
  mailboxPoller = startDriveCommandMailboxPoller
}) {
  const verified = verifyMclenovoRuntimeHandoffPlan(plan);
  if (typeof mailboxRoot !== "string" || !path.isAbsolute(mailboxRoot)) {
    throw new MclenovoRuntimeError("MCLENOVO_MAILBOX_ROOT_INVALID", "Mailbox root must be an explicit absolute local Drive path.");
  }
  if (typeof brokerFactory !== "function" || typeof mailboxCycle !== "function" || typeof mailboxPoller !== "function") {
    throw new MclenovoRuntimeError("MCLENOVO_RUNTIME_COMPOSITION_INVALID", "Runtime components must be fixed injected functions.");
  }
  const broker = brokerFactory({
    sourceHead: verified.sourceHead,
    extensionId: verified.extensionId,
    host: BROKER_HOST,
    port: BROKER_PORT,
    clock
  });
  let started = false;
  let poller = null;

  const dispatch = (command) => broker.dispatch(command);
  const runOnce = async () => {
    if (!started) throw new MclenovoRuntimeError("MCLENOVO_RUNTIME_NOT_STARTED", "Runtime must start before mailbox processing.");
    return mailboxCycle({ mailboxRoot, sourceHead: verified.sourceHead, dispatch, clock });
  };

  return Object.freeze({
    async start({ continuous = true } = {}) {
      if (started) return this.status();
      const bound = await broker.start();
      if (bound.host !== BROKER_HOST || bound.port !== BROKER_PORT) {
        await broker.stop();
        throw new MclenovoRuntimeError("MCLENOVO_RUNTIME_BIND_INVALID", "Broker must bind the fixed local endpoint.");
      }
      started = true;
      if (continuous) {
        poller = mailboxPoller({
          mailboxRoot,
          sourceHead: verified.sourceHead,
          dispatch,
          clock,
          pollIntervalMs: MAILBOX_POLL_INTERVAL_MS
        });
      }
      return this.status();
    },
    runOnce,
    async stop() {
      poller?.stop();
      poller = null;
      await broker.stop();
      started = false;
      return this.status();
    },
    status() {
      return {
        schemaVersion: 1,
        status: started ? "MCLENOVO_RUNTIME_LISTENING_PENDING_EXTENSION" : "MCLENOVO_RUNTIME_STOPPED",
        sourceHead: verified.sourceHead,
        pairId: verified.pairId,
        extensionId: verified.extensionId,
        planId: verified.planId,
        continuousPolling: Boolean(poller),
        broker: broker.status(),
        mailboxRootPersisted: false,
        liveEvidenceAccepted: false,
        safety: {
          mysmisWrites: 0,
          controlsClicked: 0,
          browserSecretsRead: false,
          arbitraryShell: false,
          publicPortOpened: false,
          nativeMessaging: false
        }
      };
    }
  });
}

export const MCLENOVO_LOOPBACK_ORIGIN = BROKER_ORIGIN;

