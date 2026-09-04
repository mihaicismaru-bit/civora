#!/usr/bin/env node
import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createBuildAttestation, verifyPairedBuildAttestations } from "../core/build-attestation.mjs";
import { createInstallBundleManifest, verifyInstallBundlePreflight } from "../native/install-bundle.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const sourceHead = process.env.GITHUB_SHA;
if (!/^[a-f0-9]{40}$/u.test(sourceHead ?? "")) {
  throw new Error("Exact GITHUB_SHA is required.");
}

const runtimeConfig = JSON.parse(await readFile(path.join(root, "build/runtime-files.json"), "utf8"));
if (runtimeConfig?.schemaVersion !== 1) throw new Error("Runtime config invalid.");

async function loadFiles(paths) {
  return Promise.all(paths.map(async (relative) => ({
    path: relative,
    bytes: new Uint8Array(await readFile(path.join(root, relative)))
  })));
}

const extensionFiles = await loadFiles(runtimeConfig.EXTENSION);
const agentFiles = await loadFiles(runtimeConfig.NATIVE_AGENT);
const extensionAttestation = createBuildAttestation({ component: "EXTENSION", sourceHead, files: extensionFiles });
const agentAttestation = createBuildAttestation({ component: "NATIVE_AGENT", sourceHead, files: agentFiles });
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
  liveMysmisEvidence: false
};

const manifest = createInstallBundleManifest({
  sourceHead,
  extensionAttestation,
  extensionFiles,
  agentAttestation,
  agentFiles,
  pairReceipt,
  runtimeConfig
});

const outputRoot = path.join(root, "dist", `MYSMIS_CONNECTOR_INSTALL_BUNDLE_${sourceHead.slice(0, 12)}`);
await rm(outputRoot, { recursive: true, force: true });
await mkdir(path.join(outputRoot, "CONTROL"), { recursive: true });
await mkdir(path.join(outputRoot, "PAYLOAD"), { recursive: true });

const union = [...new Set([...runtimeConfig.EXTENSION, ...runtimeConfig.NATIVE_AGENT])].sort();
for (const relative of union) {
  const target = path.join(outputRoot, "PAYLOAD", relative);
  await mkdir(path.dirname(target), { recursive: true });
  await cp(path.join(root, relative), target);
}

await writeFile(path.join(outputRoot, "CONTROL", "EXTENSION_BUILD_ATTESTATION.json"), `${JSON.stringify(extensionAttestation, null, 2)}\n`);
await writeFile(path.join(outputRoot, "CONTROL", "NATIVE_AGENT_BUILD_ATTESTATION.json"), `${JSON.stringify(agentAttestation, null, 2)}\n`);
await writeFile(path.join(outputRoot, "CONTROL", "PAIRED_BUILD_RECEIPT.json"), `${JSON.stringify(pairReceipt, null, 2)}\n`);
await writeFile(path.join(outputRoot, "CONTROL", "INSTALL_BUNDLE_MANIFEST.json"), `${JSON.stringify(manifest, null, 2)}\n`);
await cp(path.join(root, "install", "OPERATOR_README.md"), path.join(outputRoot, "CONTROL", "OPERATOR_README.md"));
await cp(path.join(root, "install", "VERIFY_OFFLINE.cmd"), path.join(outputRoot, "CONTROL", "VERIFY_OFFLINE.cmd"));

const payloadForPreflight = await Promise.all(union.map(async (relative) => ({
  path: relative,
  bytes: new Uint8Array(await readFile(path.join(outputRoot, "PAYLOAD", relative))),
  isSymbolicLink: false
})));
const preflight = verifyInstallBundlePreflight({ manifest, pairReceipt, bundleFiles: payloadForPreflight });
await writeFile(path.join(outputRoot, "CONTROL", "CI_PREFLIGHT_RECEIPT.json"), `${JSON.stringify(preflight, null, 2)}\n`);
await writeFile(path.join(outputRoot, "CONTROL", "BUILD_INFO.json"), `${JSON.stringify({ schemaVersion: 1, sourceHead, pairId: pair.pairId, generatedBy: "GitHub Actions", browserCompatibilityGateRequired: true }, null, 2)}\n`);

process.stdout.write(`${outputRoot}\n`);
