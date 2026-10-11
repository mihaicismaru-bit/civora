import assert from "node:assert/strict";
import test from "node:test";
import {
  createBuildAttestation,
  verifyPairedBuildAttestations
} from "../core/build-attestation.mjs";
import {
  createInstallBundleManifest,
  InstallBundleError,
  verifyInstallBundlePreflight
} from "../native/install-bundle.mjs";

const HEAD = "9a7e59e8960c84c0145c98ab877716c63a5b3071";
const encoder = new TextEncoder();

function file(path, value = path) {
  return { path, bytes: encoder.encode(value) };
}

function envelope() {
  const extensionFiles = [file("manifest.json"), file("core/shared.mjs"), file("extension/entry.js")];
  const agentFiles = [file("core/shared.mjs"), file("native/agent.mjs")];
  const extensionAttestation = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: extensionFiles });
  const agentAttestation = createBuildAttestation({ component: "NATIVE_AGENT", sourceHead: HEAD, files: agentFiles });
  const pair = verifyPairedBuildAttestations(extensionAttestation, agentAttestation);
  const pairReceipt = {
    schemaVersion: 1,
    status: "PAIRED_BUILD_ATTESTATION_VERIFIED",
    claim: "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE",
    sourceHead: HEAD,
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
    liveMysmisEvidence: false
  };
  return {
    sourceHead: HEAD,
    extensionAttestation,
    extensionFiles,
    agentAttestation,
    agentFiles,
    pairReceipt,
    runtimeConfig: {
      schemaVersion: 1,
      EXTENSION: extensionFiles.map(({ path }) => path),
      NATIVE_AGENT: agentFiles.map(({ path }) => path)
    }
  };
}

function payload(value) {
  const all = new Map();
  for (const item of [...value.extensionFiles, ...value.agentFiles]) all.set(item.path, item);
  return [...all.values()];
}

test("deterministic manifest deduplicates shared allowlisted runtime files", () => {
  const value = envelope();
  const first = createInstallBundleManifest(value);
  const second = createInstallBundleManifest(value);
  assert.deepEqual(first, second);
  assert.equal(first.payloadFileCount, 4);
  assert.deepEqual(
    first.payloadFiles.find((item) => item.path === "core/shared.mjs").targets,
    ["EXTENSION", "NATIVE_AGENT"]
  );
  assert.match(first.manifestDigest, /^[a-f0-9]{64}$/u);
});

test("exact payload passes offline preflight without enabling installation", () => {
  const value = envelope();
  const manifest = createInstallBundleManifest(value);
  const receipt = verifyInstallBundlePreflight({ manifest, pairReceipt: value.pairReceipt, bundleFiles: payload(value) });
  assert.equal(receipt.status, "INSTALL_BUNDLE_PREFLIGHT_PASS_OFFLINE");
  assert.equal(receipt.browserInstallationPerformed, false);
  assert.equal(receipt.nativeMessagingEnabled, false);
  assert.equal(receipt.mysmisWrites, 0);
  assert.equal(receipt.liveEvidenceClaimed, false);
});

test("changed and extra payload files fail closed", () => {
  const value = envelope();
  const manifest = createInstallBundleManifest(value);
  const changed = payload(value).map((item) => item.path === "native/agent.mjs" ? file(item.path, "changed") : item);
  assert.throws(
    () => verifyInstallBundlePreflight({ manifest, pairReceipt: value.pairReceipt, bundleFiles: changed }),
    (error) => error.code === "INSTALL_PAYLOAD_MISMATCH"
  );
  assert.throws(
    () => verifyInstallBundlePreflight({
      manifest,
      pairReceipt: value.pairReceipt,
      bundleFiles: [...payload(value), file("extra/unknown.js")]
    }),
    (error) => error.code === "INSTALL_PAYLOAD_MISMATCH"
  );
});

test("duplicate and symbolic-link payload paths are denied", () => {
  const value = envelope();
  const manifest = createInstallBundleManifest(value);
  assert.throws(
    () => verifyInstallBundlePreflight({
      manifest,
      pairReceipt: value.pairReceipt,
      bundleFiles: [...payload(value), payload(value)[0]]
    }),
    (error) => error.code === "INSTALL_DUPLICATE_PATH"
  );
  const linked = payload(value).map((item, index) => index === 0 ? { ...item, isSymbolicLink: true } : item);
  assert.throws(
    () => verifyInstallBundlePreflight({ manifest, pairReceipt: value.pairReceipt, bundleFiles: linked }),
    (error) => error.code === "INSTALL_SYMLINK_DENIED"
  );
});

test("allowlist mismatch and shared-byte conflict are rejected", () => {
  const value = envelope();
  assert.throws(
    () => createInstallBundleManifest({
      ...value,
      runtimeConfig: { ...value.runtimeConfig, NATIVE_AGENT: ["native/agent.mjs"] }
    }),
    (error) => error instanceof InstallBundleError && error.code === "INSTALL_ALLOWLIST_MISMATCH"
  );
  const conflictingAgentFiles = [file("core/shared.mjs", "different"), file("native/agent.mjs")];
  const conflictingAgentAttestation = createBuildAttestation({
    component: "NATIVE_AGENT",
    sourceHead: HEAD,
    files: conflictingAgentFiles
  });
  const pair = verifyPairedBuildAttestations(value.extensionAttestation, conflictingAgentAttestation);
  const receipt = {
    ...value.pairReceipt,
    pairId: pair.pairId,
    nativeAgent: {
      fileCount: conflictingAgentAttestation.fileCount,
      packageDigest: conflictingAgentAttestation.packageDigest,
      attestationId: conflictingAgentAttestation.attestationId
    }
  };
  assert.throws(
    () => createInstallBundleManifest({
      ...value,
      agentFiles: conflictingAgentFiles,
      agentAttestation: conflictingAgentAttestation,
      pairReceipt: receipt
    }),
    (error) => error.code === "INSTALL_SHARED_FILE_CONFLICT"
  );
});

test("forged manifest and mismatched pair receipt fail preflight", () => {
  const value = envelope();
  const manifest = createInstallBundleManifest(value);
  assert.throws(
    () => verifyInstallBundlePreflight({
      manifest: { ...manifest, payloadFileCount: 999 },
      pairReceipt: value.pairReceipt,
      bundleFiles: payload(value)
    }),
    (error) => error.code === "INSTALL_MANIFEST_DIGEST_MISMATCH"
  );
  assert.throws(
    () => verifyInstallBundlePreflight({
      manifest,
      pairReceipt: { ...value.pairReceipt, pairId: "0".repeat(64) },
      bundleFiles: payload(value)
    }),
    (error) => error.code === "INSTALL_PAIR_RECEIPT_INVALID"
  );
});
