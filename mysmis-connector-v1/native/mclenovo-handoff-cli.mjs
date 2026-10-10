#!/usr/bin/env node
import { lstat, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createMclenovoRuntimeHandoffPlan } from "./mclenovo-runtime.mjs";

const MAX_CONTROL_BYTES = 1024 * 1024;
const EXTENSION_ID_PATTERN = /^[a-p]{32}$/u;

export class MclenovoHandoffCliError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "MclenovoHandoffCliError";
    this.code = code;
  }
}

export function parseMclenovoHandoffArguments(argv) {
  if (argv.length !== 4) {
    throw new MclenovoHandoffCliError("MCLENOVO_HANDOFF_ARGUMENTS_INVALID", "Expected --bundle and --extension-id.");
  }
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    if (!["--bundle", "--extension-id"].includes(key) || values[key] || argv[index + 1] == null) {
      throw new MclenovoHandoffCliError("MCLENOVO_HANDOFF_ARGUMENTS_INVALID", "Expected unique bounded arguments.");
    }
    values[key] = argv[index + 1];
  }
  if (!values["--bundle"] || !EXTENSION_ID_PATTERN.test(values["--extension-id"])) {
    throw new MclenovoHandoffCliError("MCLENOVO_HANDOFF_IDENTITY_INVALID", "A bundle root and installed extension ID are required.");
  }
  return Object.freeze({
    bundleRoot: path.resolve(values["--bundle"]),
    extensionId: values["--extension-id"]
  });
}

async function readRegularJson(filePath) {
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.size <= 0 || info.size > MAX_CONTROL_BYTES) {
    throw new MclenovoHandoffCliError("MCLENOVO_HANDOFF_CONTROL_INVALID", "A bounded regular control file is required.");
  }
  return JSON.parse(await readFile(filePath, "utf8"));
}

export function createHandoffPlanFromBundleControls({ manifest, pairReceipt, extensionId }) {
  if (!manifest
    || manifest.schemaVersion !== 1
    || manifest.status !== "INSTALL_BUNDLE_MANIFEST_VERIFIED_OFFLINE"
    || !pairReceipt
    || pairReceipt.schemaVersion !== 1
    || pairReceipt.status !== "PAIRED_BUILD_ATTESTATION_VERIFIED"
    || pairReceipt.claim !== "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE"
    || pairReceipt.sourceHead !== manifest.sourceHead
    || pairReceipt.pairId !== manifest.pairId
    || pairReceipt.installationPerformed !== false
    || pairReceipt.liveMysmisEvidence !== false) {
    throw new MclenovoHandoffCliError(
      "MCLENOVO_HANDOFF_CONTROL_MISMATCH",
      "Manifest and paired-build receipt must be exact, offline and not-started."
    );
  }
  return createMclenovoRuntimeHandoffPlan({
    sourceHead: manifest.sourceHead,
    pairId: pairReceipt.pairId,
    extensionId
  });
}

export async function createHandoffPlanFromBundle({ bundleRoot, extensionId }) {
  const controlRoot = path.resolve(bundleRoot, "CONTROL");
  const [manifest, pairReceipt] = await Promise.all([
    readRegularJson(path.resolve(controlRoot, "INSTALL_BUNDLE_MANIFEST.json")),
    readRegularJson(path.resolve(controlRoot, "PAIRED_BUILD_RECEIPT.json"))
  ]);
  return createHandoffPlanFromBundleControls({ manifest, pairReceipt, extensionId });
}

function safeFailure(error) {
  return {
    schemaVersion: 1,
    status: "MCLENOVO_HANDOFF_REJECTED_NO_RUNTIME_STARTED",
    errorCode: typeof error?.code === "string" ? error.code : "MCLENOVO_HANDOFF_REJECTED",
    runtimeStarted: false,
    mysmisAccessed: false,
    mysmisWrites: 0,
    liveEvidenceAccepted: false
  };
}

export async function main(argv = process.argv.slice(2), write = (value) => process.stdout.write(value)) {
  try {
    const args = parseMclenovoHandoffArguments(argv);
    const plan = await createHandoffPlanFromBundle(args);
    write(`${JSON.stringify(plan, null, 2)}\n`);
    return 0;
  } catch (error) {
    write(`${JSON.stringify(safeFailure(error))}\n`);
    return 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await main();
}
