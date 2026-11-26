import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  BuildAttestationError,
  createBuildAttestation,
  verifyBuildAttestation,
  verifyPairedBuildAttestations
} from "../core/build-attestation.mjs";

const HEAD = "e9b0500894443a26bf41ff5683bdfebad17c20d9";
const OTHER_HEAD = "6".repeat(40);
const encoder = new TextEncoder();

function files(overrides = {}) {
  return [
    { path: "manifest.json", bytes: encoder.encode(overrides.manifest || "manifest") },
    { path: "extension/background.js", bytes: encoder.encode(overrides.background || "background") }
  ];
}

test("attestation is deterministic across input ordering", () => {
  const first = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  const second = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: [...files()].reverse() });
  assert.deepEqual(first, second);
  assert.deepEqual(first.files.map((file) => file.path), ["extension/background.js", "manifest.json"]);
  assert.match(first.packageDigest, /^[a-f0-9]{64}$/u);
});

test("one-byte tamper fails file-set verification", () => {
  const attestation = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  assert.throws(
    () => verifyBuildAttestation({
      attestation,
      component: "EXTENSION",
      sourceHead: HEAD,
      files: files({ background: "backgroune" })
    }),
    (error) => error instanceof BuildAttestationError && error.code === "BUILD_FILE_SET_MISMATCH"
  );
});

test("wrong, zero and placeholder source heads fail closed", () => {
  for (const sourceHead of ["0".repeat(40), "__INJECT_AT_BUILD__", "not-a-commit"]) {
    assert.throws(
      () => createBuildAttestation({ component: "EXTENSION", sourceHead, files: files() }),
      (error) => error.code === "BUILD_SOURCE_HEAD_INVALID"
    );
  }
  const attestation = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  assert.throws(
    () => verifyBuildAttestation({ attestation, component: "EXTENSION", sourceHead: OTHER_HEAD, files: files() }),
    (error) => ["BUILD_ATTESTATION_BINDING_MISMATCH", "BUILD_FILE_SET_MISMATCH"].includes(error.code)
  );
});

test("extension and native agent from different heads cannot pair", () => {
  const extension = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  const agent = createBuildAttestation({ component: "NATIVE_AGENT", sourceHead: OTHER_HEAD, files: files() });
  assert.throws(
    () => verifyPairedBuildAttestations(extension, agent),
    (error) => error.code === "BUILD_PAIR_SOURCE_MISMATCH"
  );
});

test("verified same-head component pair has a deterministic pair ID", () => {
  const extension = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  const agent = createBuildAttestation({ component: "NATIVE_AGENT", sourceHead: HEAD, files: files({ manifest: "agent-a" }) });
  const first = verifyPairedBuildAttestations(extension, agent);
  const second = verifyPairedBuildAttestations(extension, agent);
  assert.deepEqual(first, second);
  assert.equal(first.status, "PAIRED_BUILD_ATTESTATION_VERIFIED");
});

test("missing, duplicate, unsafe and extra runtime paths fail closed", () => {
  assert.throws(
    () => createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: [] }),
    (error) => error.code === "BUILD_FILE_SET_EMPTY"
  );
  assert.throws(
    () => createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: [files()[0], files()[0]] }),
    (error) => error.code === "BUILD_DUPLICATE_PATH"
  );
  assert.throws(
    () => createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: [{ path: "../secret", bytes: encoder.encode("x") }] }),
    (error) => error.code === "BUILD_PATH_INVALID"
  );
  const attestation = createBuildAttestation({ component: "EXTENSION", sourceHead: HEAD, files: files() });
  assert.throws(
    () => verifyBuildAttestation({
      attestation,
      component: "EXTENSION",
      sourceHead: HEAD,
      files: [...files(), { path: "extra.js", bytes: encoder.encode("extra") }]
    }),
    (error) => error.code === "BUILD_FILE_SET_MISMATCH"
  );
});

test("runtime config is explicit, sorted by attestation and excludes evidence and tests", async () => {
  const config = JSON.parse(await readFile(new URL("../build/runtime-files.json", import.meta.url), "utf8"));
  assert.equal(config.schemaVersion, 1);
  for (const component of ["EXTENSION", "NATIVE_AGENT"]) {
    assert.ok(config[component].length > 0);
    assert.equal(new Set(config[component]).size, config[component].length);
    assert.ok(config[component].every((path) => !path.startsWith("evidence/") && !path.startsWith("tests/")));
  }
  assert.ok(config.EXTENSION.includes("manifest.json"));
  assert.ok(config.NATIVE_AGENT.includes("native/intake.mjs"));
});
