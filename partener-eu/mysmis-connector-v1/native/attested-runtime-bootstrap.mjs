import {
  verifyBuildAttestation,
  verifyPairedBuildAttestations
} from "../core/build-attestation.mjs";
import { createFixedBridgeDispatcher } from "../core/bridge-dispatcher.mjs";
import {
  ChromeSessionReplayStore,
  installInternalCommandTransport
} from "../extension/internal-transport.mjs";

export class RuntimeBootstrapError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "RuntimeBootstrapError";
    this.code = code;
    this.details = details;
  }
}

function assertReceiptField(condition, code, message) {
  if (!condition) throw new RuntimeBootstrapError(code, message);
}

function validatePairReceipt(receipt, pair, extension, agent) {
  assertReceiptField(
    receipt && typeof receipt === "object",
    "RUNTIME_PAIR_RECEIPT_REQUIRED",
    "A durable paired-build receipt is required before runtime bootstrap."
  );
  assertReceiptField(
    receipt.schemaVersion === 1
      && receipt.status === "PAIRED_BUILD_ATTESTATION_VERIFIED"
      && receipt.claim === "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE",
    "RUNTIME_PAIR_RECEIPT_STATUS_INVALID",
    "The paired-build receipt must be a verified, non-functional-acceptance receipt."
  );
  assertReceiptField(
    receipt.sourceHead === pair.sourceHead && receipt.pairId === pair.pairId,
    "RUNTIME_PAIR_RECEIPT_BINDING_MISMATCH",
    "The paired-build receipt does not bind the verified source head and pair ID."
  );
  assertReceiptField(
    receipt.extension?.fileCount === extension.fileCount
      && receipt.extension?.packageDigest === extension.packageDigest
      && receipt.extension?.attestationId === extension.attestationId
      && receipt.nativeAgent?.fileCount === agent.fileCount
      && receipt.nativeAgent?.packageDigest === agent.packageDigest
      && receipt.nativeAgent?.attestationId === agent.attestationId,
    "RUNTIME_PAIR_RECEIPT_COMPONENT_MISMATCH",
    "The paired-build receipt does not match both verified component attestations."
  );
  assertReceiptField(
    receipt.verification?.extensionRuntimeBytes === "PASS"
      && receipt.verification?.nativeAgentRuntimeBytes === "PASS"
      && receipt.verification?.sameSourceHead === "PASS"
      && receipt.verification?.mixedBuild === "DENIED"
      && receipt.verification?.placeholderHead === "DENIED"
      && receipt.verification?.tamper === "DENIED"
      && receipt.installationPerformed === false
      && receipt.liveMysmisEvidence === false,
    "RUNTIME_PAIR_RECEIPT_SAFETY_INVALID",
    "The paired-build receipt is missing required fail-closed safety assertions."
  );
}

export function verifyAttestedRuntimeEnvelope({
  sourceHead,
  extensionAttestation,
  extensionFiles,
  agentAttestation,
  agentFiles,
  pairReceipt
}) {
  const extension = verifyBuildAttestation({
    attestation: extensionAttestation,
    component: "EXTENSION",
    sourceHead,
    files: extensionFiles
  });
  const agent = verifyBuildAttestation({
    attestation: agentAttestation,
    component: "NATIVE_AGENT",
    sourceHead,
    files: agentFiles
  });
  const pair = verifyPairedBuildAttestations(
    { component: "EXTENSION", ...extension },
    { component: "NATIVE_AGENT", ...agent }
  );
  validatePairReceipt(pairReceipt, pair, extension, agent);
  return Object.freeze({
    schemaVersion: 1,
    status: "ATTESTED_RUNTIME_ENVELOPE_VERIFIED",
    sourceHead,
    pairId: pair.pairId,
    extensionPackageDigest: extension.packageDigest,
    agentPackageDigest: agent.packageDigest,
    extensionFileCount: extension.fileCount,
    agentFileCount: agent.fileCount
  });
}

export function bootstrapAttestedRuntime({
  sourceHead,
  extensionAttestation,
  extensionFiles,
  agentAttestation,
  agentFiles,
  pairReceipt,
  chromeApi,
  clock = () => new Date(),
  healthHandler,
  discoverHandler
}) {
  const verification = verifyAttestedRuntimeEnvelope({
    sourceHead,
    extensionAttestation,
    extensionFiles,
    agentAttestation,
    agentFiles,
    pairReceipt
  });

  // No listener or dispatcher exists before every byte and receipt binding above passes.
  const replayStore = new ChromeSessionReplayStore({
    storageSession: chromeApi?.storage?.session
  });
  const dispatch = createFixedBridgeDispatcher({
    connectorBuildId: sourceHead,
    agentBuildId: sourceHead,
    replayStore,
    clock,
    healthHandler,
    discoverHandler
  });
  const uninstall = installInternalCommandTransport({ chromeApi, dispatch });

  return Object.freeze({
    schemaVersion: 1,
    status: "ATTESTED_RUNTIME_BOOTSTRAPPED_READ_ONLY",
    sourceHead,
    pairId: verification.pairId,
    transport: "MV3_INTERNAL_ONLY",
    operations: Object.freeze(["HEALTH", "DISCOVER_ARTIFACTS"]),
    nativeMessagingEnabled: false,
    mysmisWrites: 0,
    uninstall
  });
}
