import { createHash } from "node:crypto";
import { verifyAttestedRuntimeEnvelope } from "./attested-runtime-bootstrap.mjs";

const SAFE_PATH = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._/-]+$/u;

export class InstallBundleError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "InstallBundleError";
    this.code = code;
    this.details = details;
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalize(value[key])]));
  }
  return value;
}

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

function assertExactConfig(component, configured, attested) {
  if (!Array.isArray(configured) || configured.length === 0 || new Set(configured).size !== configured.length) {
    throw new InstallBundleError("INSTALL_CONFIG_INVALID", `${component} requires a unique, non-empty runtime allowlist.`);
  }
  if (configured.some((path) => typeof path !== "string" || !SAFE_PATH.test(path))) {
    throw new InstallBundleError("INSTALL_PATH_INVALID", `${component} contains an unsafe runtime path.`);
  }
  const expected = [...attested].sort();
  const actual = [...configured].sort();
  if (JSON.stringify(expected) !== JSON.stringify(actual)) {
    throw new InstallBundleError("INSTALL_ALLOWLIST_MISMATCH", `${component} runtime config does not exactly match its attestation.`);
  }
}

function assertPairReceipt(receipt, manifest) {
  if (!receipt
    || receipt.schemaVersion !== 1
    || receipt.status !== "PAIRED_BUILD_ATTESTATION_VERIFIED"
    || receipt.claim !== "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE"
    || receipt.sourceHead !== manifest.sourceHead
    || receipt.pairId !== manifest.pairId
    || receipt.installationPerformed !== false
    || receipt.liveMysmisEvidence !== false) {
    throw new InstallBundleError("INSTALL_PAIR_RECEIPT_INVALID", "Bundle preflight requires the matching fail-closed pair receipt.");
  }
}

function manifestCore(manifest) {
  const { manifestDigest: _ignored, ...core } = manifest;
  return core;
}

export function createInstallBundleManifest({
  sourceHead,
  extensionAttestation,
  extensionFiles,
  agentAttestation,
  agentFiles,
  pairReceipt,
  runtimeConfig
}) {
  const verified = verifyAttestedRuntimeEnvelope({
    sourceHead,
    extensionAttestation,
    extensionFiles,
    agentAttestation,
    agentFiles,
    pairReceipt
  });
  if (!runtimeConfig || runtimeConfig.schemaVersion !== 1) {
    throw new InstallBundleError("INSTALL_CONFIG_INVALID", "Runtime allowlist config schema is missing or invalid.");
  }
  assertExactConfig("EXTENSION", runtimeConfig.EXTENSION, extensionAttestation.files.map((file) => file.path));
  assertExactConfig("NATIVE_AGENT", runtimeConfig.NATIVE_AGENT, agentAttestation.files.map((file) => file.path));

  const payload = new Map();
  for (const [target, attestation] of [
    ["EXTENSION", extensionAttestation],
    ["NATIVE_AGENT", agentAttestation]
  ]) {
    for (const file of attestation.files) {
      const existing = payload.get(file.path);
      if (existing && (existing.size !== file.size || existing.sha256 !== file.sha256)) {
        throw new InstallBundleError("INSTALL_SHARED_FILE_CONFLICT", `Shared runtime file differs between components: ${file.path}`);
      }
      if (existing) {
        existing.targets.push(target);
      } else {
        payload.set(file.path, { path: file.path, size: file.size, sha256: file.sha256, targets: [target] });
      }
    }
  }
  const payloadFiles = [...payload.values()]
    .map((file) => ({ ...file, targets: file.targets.sort() }))
    .sort((a, b) => a.path.localeCompare(b.path));
  const core = {
    schemaVersion: 1,
    status: "INSTALL_BUNDLE_MANIFEST_VERIFIED_OFFLINE",
    sourceHead,
    pairId: verified.pairId,
    payloadFileCount: payloadFiles.length,
    payloadFiles,
    controls: {
      controlDirectory: "CONTROL",
      payloadDirectory: "PAYLOAD",
      browserInstallationPerformed: false,
      nativeMessagingEnabled: false,
      mysmisAccessPerformed: false,
      arbitraryShellAllowed: false,
      mysmisWritesAllowed: 0
    },
    operatorPlan: {
      preflight: "Verify this manifest, the paired-build receipt, and every PAYLOAD byte before installation.",
      installGate: "STOP until the bounded MCLENOVO installation is explicitly authorized and observable.",
      rollback: "Remove the unpacked extension, stop the local agent, delete only the newly created connector folder, and preserve receipts.",
      liveAcceptance: "A successful offline preflight is not live MySMIS acceptance."
    }
  };
  return Object.freeze({ ...core, manifestDigest: sha256(JSON.stringify(canonicalize(core))) });
}

export function verifyInstallBundlePreflight({ manifest, pairReceipt, bundleFiles }) {
  if (!manifest || manifest.schemaVersion !== 1 || manifest.status !== "INSTALL_BUNDLE_MANIFEST_VERIFIED_OFFLINE") {
    throw new InstallBundleError("INSTALL_MANIFEST_INVALID", "A verified offline installation manifest is required.");
  }
  const expectedDigest = sha256(JSON.stringify(canonicalize(manifestCore(manifest))));
  if (manifest.manifestDigest !== expectedDigest) {
    throw new InstallBundleError("INSTALL_MANIFEST_DIGEST_MISMATCH", "Installation manifest digest is invalid.");
  }
  assertPairReceipt(pairReceipt, manifest);
  if (!Array.isArray(bundleFiles)) {
    throw new InstallBundleError("INSTALL_PAYLOAD_REQUIRED", "Bundle payload files are required for preflight.");
  }
  const seen = new Set();
  const observed = bundleFiles.map((file) => {
    if (!file || typeof file.path !== "string" || !SAFE_PATH.test(file.path)) {
      throw new InstallBundleError("INSTALL_PATH_INVALID", "Bundle payload contains an unsafe path.");
    }
    if (seen.has(file.path)) {
      throw new InstallBundleError("INSTALL_DUPLICATE_PATH", `Duplicate bundle payload path: ${file.path}`);
    }
    seen.add(file.path);
    if (file.isSymbolicLink === true) {
      throw new InstallBundleError("INSTALL_SYMLINK_DENIED", `Symbolic link denied in bundle payload: ${file.path}`);
    }
    if (!(file.bytes instanceof Uint8Array)) {
      throw new InstallBundleError("INSTALL_BYTES_INVALID", `Bundle bytes are missing for ${file.path}.`);
    }
    return { path: file.path, size: file.bytes.byteLength, sha256: sha256(file.bytes) };
  }).sort((a, b) => a.path.localeCompare(b.path));
  const expected = manifest.payloadFiles.map(({ path, size, sha256: digest }) => ({ path, size, sha256: digest }));
  if (manifest.payloadFileCount !== expected.length || JSON.stringify(observed) !== JSON.stringify(expected)) {
    throw new InstallBundleError("INSTALL_PAYLOAD_MISMATCH", "Bundle payload is missing, changed, duplicated, or contains extra files.");
  }
  if (manifest.controls?.browserInstallationPerformed !== false
    || manifest.controls?.nativeMessagingEnabled !== false
    || manifest.controls?.mysmisAccessPerformed !== false
    || manifest.controls?.arbitraryShellAllowed !== false
    || manifest.controls?.mysmisWritesAllowed !== 0) {
    throw new InstallBundleError("INSTALL_CONTROL_INVALID", "Bundle controls must preserve no-install, no-shell and zero-write state.");
  }
  return Object.freeze({
    schemaVersion: 1,
    status: "INSTALL_BUNDLE_PREFLIGHT_PASS_OFFLINE",
    sourceHead: manifest.sourceHead,
    pairId: manifest.pairId,
    manifestDigest: manifest.manifestDigest,
    payloadFileCount: observed.length,
    browserInstallationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  });
}
