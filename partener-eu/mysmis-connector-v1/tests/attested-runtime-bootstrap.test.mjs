import assert from "node:assert/strict";
import test from "node:test";
import {
  createBuildAttestation,
  verifyPairedBuildAttestations
} from "../core/build-attestation.mjs";
import {
  bootstrapAttestedRuntime,
  RuntimeBootstrapError,
  verifyAttestedRuntimeEnvelope
} from "../native/attested-runtime-bootstrap.mjs";
import {
  createBridgeHealthChallenge,
  READ_ONLY_BRIDGE_CAPABILITIES
} from "../core/bridge-health.mjs";

const HEAD = "411e1120be806dd2902298b8e4baac7dcc01e302";
const OTHER_HEAD = "7".repeat(40);
const encoder = new TextEncoder();
const issuedClock = () => new Date("2026-08-29T19:20:00.000Z");
const dispatchClock = () => new Date("2026-08-29T19:20:20.000Z");

function runtimeFiles(label) {
  return [
    { path: `${label}/entry.mjs`, bytes: encoder.encode(`${label}-entry`) },
    { path: `${label}/policy.mjs`, bytes: encoder.encode("read-only") }
  ];
}

function buildEnvelope({ sourceHead = HEAD, receiptOverrides = {} } = {}) {
  const extensionFiles = runtimeFiles("extension");
  const agentFiles = runtimeFiles("native");
  const extensionAttestation = createBuildAttestation({
    component: "EXTENSION",
    sourceHead,
    files: extensionFiles
  });
  const agentAttestation = createBuildAttestation({
    component: "NATIVE_AGENT",
    sourceHead,
    files: agentFiles
  });
  const pair = verifyPairedBuildAttestations(extensionAttestation, agentAttestation);
  const pairReceipt = {
    schemaVersion: 1,
    status: "PAIRED_BUILD_ATTESTATION_VERIFIED",
    claim: "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE",
    sourceHead,
    pairId: pair.pairId,
    extension: {
      fileCount: extensionAttestation.fileCount,
      packageDigest: extensionAttestation.packageDigest,
      attestationId: extensionAttestation.attestationId
    },
    nativeAgent: {
      fileCount: agentAttestation.fileCount,
      packageDigest: agentAttestation.packageDigest,
      attestationId: agentAttestation.attestationId
    },
    verification: {
      extensionRuntimeBytes: "PASS",
      nativeAgentRuntimeBytes: "PASS",
      sameSourceHead: "PASS",
      mixedBuild: "DENIED",
      placeholderHead: "DENIED",
      tamper: "DENIED"
    },
    installationPerformed: false,
    liveMysmisEvidence: false,
    ...receiptOverrides
  };
  return {
    sourceHead,
    extensionFiles,
    agentFiles,
    extensionAttestation,
    agentAttestation,
    pairReceipt
  };
}

function chromeApi(storageState = {}) {
  let listener;
  const storage = {
    state: structuredClone(storageState),
    async get(key) { return { [key]: structuredClone(this.state[key]) }; },
    async set(values) { Object.assign(this.state, structuredClone(values)); }
  };
  return {
    api: {
      runtime: {
        id: "attested-extension",
        onMessage: {
          addListener(value) { listener = value; },
          removeListener(value) { if (listener === value) listener = undefined; }
        }
      },
      storage: { session: storage }
    },
    storage,
    get listener() { return listener; }
  };
}

function healthHandler() {
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
      authenticatedSessionPresent: false,
      mysmisOriginPresent: false
    }
  };
}

function bootstrap(chrome, envelope = buildEnvelope()) {
  return bootstrapAttestedRuntime({
    ...envelope,
    chromeApi: chrome.api,
    clock: dispatchClock,
    healthHandler: async () => healthHandler(),
    discoverHandler: async () => ({
      snapshot: { project: null, page: {}, elements: [] },
      reportedCandidateCount: 0,
      methodsObserved: []
    })
  });
}

test("verified same-head bytes and pair receipt bootstrap only the fixed internal transport", async () => {
  const chrome = chromeApi();
  const runtime = bootstrap(chrome);
  assert.equal(runtime.status, "ATTESTED_RUNTIME_BOOTSTRAPPED_READ_ONLY");
  assert.deepEqual(runtime.operations, ["HEALTH", "DISCOVER_ARTIFACTS"]);
  assert.equal(runtime.nativeMessagingEnabled, false);
  assert.equal(typeof chrome.listener, "function");

  const challenge = createBridgeHealthChallenge({
    connectorBuildId: HEAD,
    clock: issuedClock,
    nonce: "89".repeat(32)
  });
  const response = await new Promise((resolve) => {
    chrome.listener(
      { type: "MYSMIS_BRIDGE_COMMAND", command: challenge },
      { id: "attested-extension" },
      resolve
    );
  });
  assert.equal(response.ok, true);
  assert.equal(response.response.connectorBuildId, HEAD);
  assert.equal(response.response.safety.mysmisWrites, 0);
});

test("missing paired receipt fails before a listener is registered", () => {
  const chrome = chromeApi();
  assert.throws(
    () => bootstrap(chrome, { ...buildEnvelope(), pairReceipt: undefined }),
    (error) => error instanceof RuntimeBootstrapError && error.code === "RUNTIME_PAIR_RECEIPT_REQUIRED"
  );
  assert.equal(chrome.listener, undefined);
});

test("changed runtime bytes fail before bootstrap side effects", () => {
  const chrome = chromeApi();
  const envelope = buildEnvelope();
  envelope.extensionFiles[0] = {
    ...envelope.extensionFiles[0],
    bytes: encoder.encode("one-byte-different")
  };
  assert.throws(
    () => bootstrap(chrome, envelope),
    (error) => error.code === "BUILD_FILE_SET_MISMATCH"
  );
  assert.equal(chrome.listener, undefined);
});

test("mixed component source heads cannot be bootstrapped", () => {
  const chrome = chromeApi();
  const envelope = buildEnvelope();
  envelope.agentAttestation = createBuildAttestation({
    component: "NATIVE_AGENT",
    sourceHead: OTHER_HEAD,
    files: envelope.agentFiles
  });
  assert.throws(
    () => bootstrap(chrome, envelope),
    (error) => error.code === "BUILD_ATTESTATION_BINDING_MISMATCH"
  );
  assert.equal(chrome.listener, undefined);
});

test("forged pair ID and unsafe acceptance claims fail closed", () => {
  const chrome = chromeApi();
  const forged = buildEnvelope({ receiptOverrides: { pairId: "0".repeat(64) } });
  assert.throws(
    () => bootstrap(chrome, forged),
    (error) => error.code === "RUNTIME_PAIR_RECEIPT_BINDING_MISMATCH"
  );
  const unsafe = buildEnvelope({ receiptOverrides: { installationPerformed: true } });
  assert.throws(
    () => bootstrap(chrome, unsafe),
    (error) => error.code === "RUNTIME_PAIR_RECEIPT_SAFETY_INVALID"
  );
  assert.equal(chrome.listener, undefined);
});

test("verified envelope contains no runtime bytes, paths or credential material", () => {
  const verified = verifyAttestedRuntimeEnvelope(buildEnvelope());
  assert.equal(verified.status, "ATTESTED_RUNTIME_ENVELOPE_VERIFIED");
  assert.equal("files" in verified, false);
  assert.equal(JSON.stringify(verified).includes("entry.mjs"), false);
  assert.equal(Object.isFrozen(verified), true);
});
