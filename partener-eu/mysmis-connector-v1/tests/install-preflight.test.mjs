import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { mkdtemp, mkdir, readFile, symlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { promisify } from "node:util";
import test from "node:test";
import { createBuildAttestation, verifyPairedBuildAttestations } from "../core/build-attestation.mjs";
import { createInstallBundleManifest } from "../native/install-bundle.mjs";
import {
  createInstallAttemptFailureReceipt,
  runInstallPreflight
} from "../native/install-preflight.mjs";

const execFileAsync = promisify(execFile);
const HEAD = "605b37a08dc913f9ca186127d39c4c7587b3b990";
const NOW = () => new Date("2026-08-29T21:51:00.000Z");
const encoder = new TextEncoder();

function runtimeFile(path, value = path) {
  return { path, bytes: encoder.encode(value) };
}

function buildEnvelope() {
  const extensionFiles = [runtimeFile("manifest.json"), runtimeFile("core/shared.mjs"), runtimeFile("extension/entry.js")];
  const agentFiles = [runtimeFile("core/shared.mjs"), runtimeFile("native/install-preflight-cli.mjs")];
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
  const manifest = createInstallBundleManifest({
    sourceHead: HEAD,
    extensionAttestation,
    extensionFiles,
    agentAttestation,
    agentFiles,
    pairReceipt,
    runtimeConfig: {
      schemaVersion: 1,
      EXTENSION: extensionFiles.map((file) => file.path),
      NATIVE_AGENT: agentFiles.map((file) => file.path)
    }
  });
  return { extensionFiles, agentFiles, extensionAttestation, agentAttestation, pairReceipt, manifest };
}

async function writeJson(path, value) {
  await mkdir(dirname(path), { recursive: true });
  await writeFile(path, `${JSON.stringify(value, null, 2)}\n`);
}

async function extractedBundle() {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-preflight-"));
  const envelope = buildEnvelope();
  const unique = new Map();
  for (const file of [...envelope.extensionFiles, ...envelope.agentFiles]) unique.set(file.path, file);
  for (const file of unique.values()) {
    const path = resolve(root, "PAYLOAD", file.path);
    await mkdir(dirname(path), { recursive: true });
    await writeFile(path, file.bytes);
  }
  const control = resolve(root, "CONTROL");
  await mkdir(control, { recursive: true });
  await writeJson(resolve(control, "EXTENSION_BUILD_ATTESTATION.json"), envelope.extensionAttestation);
  await writeJson(resolve(control, "INSTALL_BUNDLE_MANIFEST.json"), envelope.manifest);
  await writeJson(resolve(control, "NATIVE_AGENT_BUILD_ATTESTATION.json"), envelope.agentAttestation);
  await writeFile(resolve(control, "OPERATOR_README.md"), "Offline verification only.\n");
  await writeJson(resolve(control, "PAIRED_BUILD_RECEIPT.json"), envelope.pairReceipt);
  await writeFile(resolve(control, "VERIFY_OFFLINE.cmd"), "@echo off\nexit /b 0\n");
  return { root, envelope };
}

test("portable extracted-bundle preflight emits bounded no-install receipt", async () => {
  const { root } = await extractedBundle();
  const receipt = await runInstallPreflight({ bundleRoot: root, attemptId: "ATTEMPT-013", clock: NOW });
  assert.equal(receipt.status, "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED");
  assert.equal(receipt.installState, "NOT_STARTED");
  assert.equal(receipt.rollbackState, "NOT_REQUIRED");
  assert.equal(receipt.browserInstallationPerformed, false);
  assert.equal(receipt.nativeMessagingEnabled, false);
  assert.equal(receipt.mysmisAccessPerformed, false);
  assert.equal(receipt.mysmisWrites, 0);
  assert.equal(receipt.liveEvidenceClaimed, false);
  assert.doesNotMatch(JSON.stringify(receipt), new RegExp(root.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&"), "u"));
});

test("missing or extra control files are denied before installation", async () => {
  const missing = await extractedBundle();
  await writeFile(resolve(missing.root, "CONTROL", "EXTRA.txt"), "extra");
  await assert.rejects(
    runInstallPreflight({ bundleRoot: missing.root, attemptId: "ATTEMPT-EXTRA", clock: NOW }),
    (error) => error.code === "PREFLIGHT_CONTROL_SET_MISMATCH"
  );
});

test("changed payload bytes fail closed", async () => {
  const { root } = await extractedBundle();
  await writeFile(resolve(root, "PAYLOAD", "manifest.json"), "changed");
  await assert.rejects(
    runInstallPreflight({ bundleRoot: root, attemptId: "ATTEMPT-CHANGED", clock: NOW }),
    (error) => error.code === "INSTALL_PAYLOAD_MISMATCH"
  );
});

test("symbolic links in extracted payload are denied", async () => {
  const { root } = await extractedBundle();
  await symlink(resolve(root, "PAYLOAD", "manifest.json"), resolve(root, "PAYLOAD", "linked-file"));
  await assert.rejects(
    runInstallPreflight({ bundleRoot: root, attemptId: "ATTEMPT-SYMLINK", clock: NOW }),
    (error) => error.code === "PREFLIGHT_SYMLINK_DENIED"
  );
});

test("mismatched component attestation cannot pass the full envelope check", async () => {
  const { root, envelope } = await extractedBundle();
  await writeJson(resolve(root, "CONTROL", "NATIVE_AGENT_BUILD_ATTESTATION.json"), {
    ...envelope.agentAttestation,
    sourceHead: "1".repeat(40)
  });
  await assert.rejects(
    runInstallPreflight({ bundleRoot: root, attemptId: "ATTEMPT-MISMATCH", clock: NOW }),
    (error) => error.code === "BUILD_ATTESTATION_BINDING_MISMATCH"
  );
});

test("failure receipts expose only bounded error codes, not paths or messages", () => {
  const receipt = createInstallAttemptFailureReceipt({
    attemptId: "../../secret",
    error: Object.assign(new Error("C:\\Users\\operator\\secret-token"), { code: "unsafe/path" }),
    clock: NOW
  });
  assert.equal(receipt.attemptId, "INVALID_ATTEMPT_ID");
  assert.equal(receipt.errorCode, "PREFLIGHT_UNEXPECTED_FAILURE");
  assert.equal(receipt.installState, "NOT_STARTED");
  assert.doesNotMatch(JSON.stringify(receipt), /Users|secret-token|unsafe\/path/u);
});

test("CLI returns a machine-readable success receipt without writing files", async () => {
  const { root } = await extractedBundle();
  const before = await readdirTree(root);
  const { stdout, stderr } = await execFileAsync(process.execPath, [
    resolve("native/install-preflight-cli.mjs"),
    "--bundle", root,
    "--attempt-id", "ATTEMPT-CLI"
  ]);
  assert.equal(stderr, "");
  assert.equal(JSON.parse(stdout).status, "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED");
  assert.deepEqual(await readdirTree(root), before);
});

test("Windows wrapper invokes only the bounded Node preflight command", async () => {
  const script = await readFile(resolve("install/VERIFY_OFFLINE.cmd"), "utf8");
  assert.match(script, /install-preflight-cli\.mjs/u);
  assert.doesNotMatch(script, /powershell|reg(?:\.exe)?\s|nativeMessaging|chrome\.exe|msedge\.exe|start\s/iu);
});

async function readdirTree(root) {
  const result = [];
  async function walk(directory) {
    for (const entry of await (await import("node:fs/promises")).readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      result.push(path.slice(root.length).split("\\").join("/"));
      if (entry.isDirectory()) await walk(path);
    }
  }
  await walk(root);
  return result.sort();
}
