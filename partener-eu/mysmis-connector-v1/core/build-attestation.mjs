import { createHash } from "node:crypto";

const COMPONENTS = new Set(["EXTENSION", "NATIVE_AGENT"]);
const SAFE_PATH = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._/-]+$/u;

export class BuildAttestationError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "BuildAttestationError";
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

function assertSourceHead(value) {
  if (typeof value !== "string" || !/^[a-f0-9]{40}$/u.test(value) || /^0{40}$/u.test(value)) {
    throw new BuildAttestationError("BUILD_SOURCE_HEAD_INVALID", "Source head must be a non-placeholder 40-character Git commit SHA.");
  }
}

function normalizeFileEntries(files) {
  if (!Array.isArray(files) || files.length === 0) {
    throw new BuildAttestationError("BUILD_FILE_SET_EMPTY", "A build must contain an explicit non-empty runtime file set.");
  }
  const seen = new Set();
  const normalized = files.map((file) => {
    if (!file || typeof file.path !== "string" || !SAFE_PATH.test(file.path)) {
      throw new BuildAttestationError("BUILD_PATH_INVALID", "Runtime file paths must be safe relative paths.");
    }
    if (seen.has(file.path)) {
      throw new BuildAttestationError("BUILD_DUPLICATE_PATH", `Duplicate runtime file path: ${file.path}`);
    }
    seen.add(file.path);
    if (!(file.bytes instanceof Uint8Array)) {
      throw new BuildAttestationError("BUILD_BYTES_INVALID", `Runtime bytes are missing for ${file.path}.`);
    }
    return {
      path: file.path,
      size: file.bytes.byteLength,
      sha256: sha256(file.bytes)
    };
  });
  return normalized.sort((a, b) => a.path.localeCompare(b.path));
}

export function createBuildAttestation({ component, sourceHead, files }) {
  if (!COMPONENTS.has(component)) {
    throw new BuildAttestationError("BUILD_COMPONENT_INVALID", "Component must be EXTENSION or NATIVE_AGENT.");
  }
  assertSourceHead(sourceHead);
  const normalizedFiles = normalizeFileEntries(files);
  const packageCore = {
    schemaVersion: 1,
    component,
    sourceHead,
    fileCount: normalizedFiles.length,
    files: normalizedFiles
  };
  const packageDigest = sha256(JSON.stringify(canonicalize(packageCore)));
  const attestationCore = { ...packageCore, packageDigest };
  return {
    ...attestationCore,
    attestationId: sha256(JSON.stringify(canonicalize(attestationCore)))
  };
}

export function verifyBuildAttestation({ attestation, component, sourceHead, files }) {
  const expected = createBuildAttestation({ component, sourceHead, files });
  if (!attestation || attestation.schemaVersion !== 1
    || attestation.component !== component
    || attestation.sourceHead !== sourceHead) {
    throw new BuildAttestationError("BUILD_ATTESTATION_BINDING_MISMATCH", "Attestation does not bind the requested component and source head.");
  }
  if (JSON.stringify(canonicalize(attestation.files)) !== JSON.stringify(canonicalize(expected.files))) {
    throw new BuildAttestationError("BUILD_FILE_SET_MISMATCH", "Runtime file list, size, or SHA-256 does not match the attestation.");
  }
  if (attestation.fileCount !== expected.fileCount
    || attestation.packageDigest !== expected.packageDigest
    || attestation.attestationId !== expected.attestationId) {
    throw new BuildAttestationError("BUILD_DIGEST_MISMATCH", "Build digest or attestation ID does not match the runtime bytes.");
  }
  return {
    schemaVersion: 1,
    status: "BUILD_ATTESTATION_VERIFIED",
    component,
    sourceHead,
    packageDigest: expected.packageDigest,
    attestationId: expected.attestationId,
    fileCount: expected.fileCount
  };
}

export function verifyPairedBuildAttestations(extensionAttestation, agentAttestation) {
  if (extensionAttestation?.component !== "EXTENSION"
    || agentAttestation?.component !== "NATIVE_AGENT") {
    throw new BuildAttestationError("BUILD_PAIR_COMPONENT_MISMATCH", "Build pair must contain one extension and one native agent.");
  }
  assertSourceHead(extensionAttestation.sourceHead);
  assertSourceHead(agentAttestation.sourceHead);
  if (extensionAttestation.sourceHead !== agentAttestation.sourceHead) {
    throw new BuildAttestationError("BUILD_PAIR_SOURCE_MISMATCH", "Extension and native agent must originate from the same Git source head.");
  }
  if (!/^[a-f0-9]{64}$/u.test(extensionAttestation.packageDigest)
    || !/^[a-f0-9]{64}$/u.test(agentAttestation.packageDigest)
    || !/^[a-f0-9]{64}$/u.test(extensionAttestation.attestationId)
    || !/^[a-f0-9]{64}$/u.test(agentAttestation.attestationId)) {
    throw new BuildAttestationError("BUILD_PAIR_DIGEST_INVALID", "Both packages require complete SHA-256 attestations.");
  }
  const core = {
    schemaVersion: 1,
    sourceHead: extensionAttestation.sourceHead,
    extensionPackageDigest: extensionAttestation.packageDigest,
    extensionAttestationId: extensionAttestation.attestationId,
    agentPackageDigest: agentAttestation.packageDigest,
    agentAttestationId: agentAttestation.attestationId
  };
  return {
    ...core,
    pairId: sha256(JSON.stringify(canonicalize(core))),
    status: "PAIRED_BUILD_ATTESTATION_VERIFIED"
  };
}
