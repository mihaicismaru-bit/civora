import { readFile, readdir, lstat } from "node:fs/promises";
import { relative, resolve, sep } from "node:path";
import { verifyAttestedRuntimeEnvelope } from "./attested-runtime-bootstrap.mjs";
import { InstallBundleError, verifyInstallBundlePreflight } from "./install-bundle.mjs";

const ATTEMPT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$/u;
const CONTROL_FILES = Object.freeze([
  "EXTENSION_BUILD_ATTESTATION.json",
  "INSTALL_BUNDLE_MANIFEST.json",
  "NATIVE_AGENT_BUILD_ATTESTATION.json",
  "OPERATOR_README.md",
  "PAIRED_BUILD_RECEIPT.json",
  "VERIFY_OFFLINE.cmd"
]);

export class InstallPreflightError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "InstallPreflightError";
    this.code = code;
  }
}

function assertAttemptId(value) {
  if (typeof value !== "string" || !ATTEMPT_ID.test(value)) {
    throw new InstallPreflightError("PREFLIGHT_ATTEMPT_ID_INVALID", "Attempt ID must be a bounded non-sensitive identifier.");
  }
}

function toPortablePath(root, path) {
  return relative(root, path).split(sep).join("/");
}

async function listRegularFiles(root) {
  const entries = [];
  async function visit(directory) {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const path = resolve(directory, entry.name);
      const stat = await lstat(path);
      if (stat.isSymbolicLink()) {
        throw new InstallPreflightError("PREFLIGHT_SYMLINK_DENIED", "Symbolic links are denied in the extracted bundle.");
      }
      if (stat.isDirectory()) {
        await visit(path);
      } else if (stat.isFile()) {
        entries.push({ path: toPortablePath(root, path), bytes: await readFile(path) });
      } else {
        throw new InstallPreflightError("PREFLIGHT_SPECIAL_FILE_DENIED", "Only regular files are allowed in the extracted bundle.");
      }
    }
  }
  await visit(root);
  return entries.sort((a, b) => a.path.localeCompare(b.path));
}

async function readControls(controlRoot) {
  const entries = await readdir(controlRoot, { withFileTypes: true });
  const names = entries.map((entry) => entry.name).sort();
  if (entries.some((entry) => !entry.isFile()) || JSON.stringify(names) !== JSON.stringify([...CONTROL_FILES].sort())) {
    throw new InstallPreflightError("PREFLIGHT_CONTROL_SET_MISMATCH", "The CONTROL directory must contain the exact bounded control set.");
  }
  const json = async (name) => JSON.parse(await readFile(resolve(controlRoot, name), "utf8"));
  return {
    extensionAttestation: await json("EXTENSION_BUILD_ATTESTATION.json"),
    manifest: await json("INSTALL_BUNDLE_MANIFEST.json"),
    agentAttestation: await json("NATIVE_AGENT_BUILD_ATTESTATION.json"),
    pairReceipt: await json("PAIRED_BUILD_RECEIPT.json")
  };
}

function componentFiles(manifest, payloadFiles, target) {
  const expected = new Set(
    manifest.payloadFiles
      .filter((file) => file.targets.includes(target))
      .map((file) => file.path)
  );
  return payloadFiles.filter((file) => expected.has(file.path));
}

export function createInstallAttemptFailureReceipt({ attemptId, error, clock = () => new Date() }) {
  const safeAttemptId = typeof attemptId === "string" && ATTEMPT_ID.test(attemptId) ? attemptId : "INVALID_ATTEMPT_ID";
  const errorCode = typeof error?.code === "string" && /^[A-Z0-9_]{1,80}$/u.test(error.code)
    ? error.code
    : "PREFLIGHT_UNEXPECTED_FAILURE";
  return Object.freeze({
    schemaVersion: 1,
    attemptId: safeAttemptId,
    recordedAt: clock().toISOString(),
    status: "INSTALL_ATTEMPT_BLOCKED",
    errorCode,
    installState: "NOT_STARTED",
    rollbackState: "NOT_REQUIRED",
    browserInstallationPerformed: false,
    nativeMessagingEnabled: false,
    mysmisAccessPerformed: false,
    mysmisWrites: 0,
    liveEvidenceClaimed: false
  });
}

export async function runInstallPreflight({ bundleRoot, attemptId, clock = () => new Date() }) {
  assertAttemptId(attemptId);
  if (typeof bundleRoot !== "string" || bundleRoot.length === 0) {
    throw new InstallPreflightError("PREFLIGHT_BUNDLE_ROOT_REQUIRED", "Extracted bundle root is required.");
  }
  const root = resolve(bundleRoot);
  const payloadRoot = resolve(root, "PAYLOAD");
  const controlRoot = resolve(root, "CONTROL");
  try {
    const [payloadFiles, controls] = await Promise.all([
      listRegularFiles(payloadRoot),
      readControls(controlRoot)
    ]);
    const bundle = verifyInstallBundlePreflight({
      manifest: controls.manifest,
      pairReceipt: controls.pairReceipt,
      bundleFiles: payloadFiles
    });
    const runtime = verifyAttestedRuntimeEnvelope({
      sourceHead: controls.manifest.sourceHead,
      extensionAttestation: controls.extensionAttestation,
      extensionFiles: componentFiles(controls.manifest, payloadFiles, "EXTENSION"),
      agentAttestation: controls.agentAttestation,
      agentFiles: componentFiles(controls.manifest, payloadFiles, "NATIVE_AGENT"),
      pairReceipt: controls.pairReceipt
    });
    return Object.freeze({
      schemaVersion: 1,
      attemptId,
      recordedAt: clock().toISOString(),
      status: "INSTALL_ATTEMPT_PREFLIGHT_PASS_INSTALL_NOT_STARTED",
      sourceHead: bundle.sourceHead,
      pairId: runtime.pairId,
      manifestDigest: bundle.manifestDigest,
      payloadFileCount: bundle.payloadFileCount,
      extensionFileCount: runtime.extensionFileCount,
      agentFileCount: runtime.agentFileCount,
      installState: "NOT_STARTED",
      rollbackState: "NOT_REQUIRED",
      browserInstallationPerformed: false,
      nativeMessagingEnabled: false,
      mysmisAccessPerformed: false,
      mysmisWrites: 0,
      liveEvidenceClaimed: false
    });
  } catch (error) {
    if (error instanceof InstallPreflightError || error instanceof InstallBundleError || typeof error?.code === "string") {
      throw new InstallPreflightError(error.code, "Extracted bundle preflight failed closed.");
    }
    throw new InstallPreflightError("PREFLIGHT_UNEXPECTED_FAILURE", "Extracted bundle preflight failed closed.");
  }
}

export const INSTALL_PREFLIGHT_CONTROL_FILES = CONTROL_FILES;
