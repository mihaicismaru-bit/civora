import assert from "node:assert/strict";
import test from "node:test";

import {
  createHandoffPlanFromBundleControls,
  MclenovoHandoffCliError,
  parseMclenovoHandoffArguments
} from "../native/mclenovo-handoff-cli.mjs";

const HEAD = "d43cb3b6c8025aec897cd0143bf5a9eab055de84";
const PAIR_ID = "6".repeat(64);
const EXTENSION_ID = "a".repeat(32);

function controls() {
  return {
    manifest: {
      schemaVersion: 1,
      status: "INSTALL_BUNDLE_MANIFEST_VERIFIED_OFFLINE",
      sourceHead: HEAD,
      pairId: PAIR_ID
    },
    pairReceipt: {
      schemaVersion: 1,
      status: "PAIRED_BUILD_ATTESTATION_VERIFIED",
      claim: "BUILD_PAIR_VERIFIED_NOT_FUNCTIONAL_ACCEPTANCE",
      sourceHead: HEAD,
      pairId: PAIR_ID,
      installationPerformed: false,
      liveMysmisEvidence: false
    },
    extensionId: EXTENSION_ID
  };
}

test("exact offline bundle controls produce a bounded deterministic runtime plan", () => {
  const first = createHandoffPlanFromBundleControls(controls());
  const second = createHandoffPlanFromBundleControls(controls());
  assert.deepEqual(first, second);
  assert.equal(first.sourceHead, HEAD);
  assert.equal(first.pairId, PAIR_ID);
  assert.equal(first.extensionId, EXTENSION_ID);
  assert.deepEqual(first.agent.allowedOperations, ["HEALTH", "DISCOVER_ARTIFACTS"]);
  assert.equal(first.safety.mysmisWrites, 0);
  assert.equal(first.safety.arbitraryShell, false);
  assert.equal(first.safety.liveEvidenceAccepted, false);
});

test("mismatched, installed or live-claiming controls fail closed", () => {
  const variants = [
    { pairReceipt: { ...controls().pairReceipt, pairId: "7".repeat(64) } },
    { pairReceipt: { ...controls().pairReceipt, installationPerformed: true } },
    { pairReceipt: { ...controls().pairReceipt, liveMysmisEvidence: true } },
    { manifest: { ...controls().manifest, sourceHead: "8".repeat(40) } }
  ];
  for (const variant of variants) {
    assert.throws(
      () => createHandoffPlanFromBundleControls({ ...controls(), ...variant }),
      (error) => error instanceof MclenovoHandoffCliError && error.code === "MCLENOVO_HANDOFF_CONTROL_MISMATCH"
    );
  }
});

test("CLI accepts only one bundle and one valid installed extension identity", () => {
  const parsed = parseMclenovoHandoffArguments([
    "--bundle", ".",
    "--extension-id", EXTENSION_ID
  ]);
  assert.equal(parsed.extensionId, EXTENSION_ID);
  assert.ok(parsed.bundleRoot);
  for (const argv of [
    ["--bundle", "."],
    ["--bundle", ".", "--extension-id", "not-an-id"],
    ["--bundle", ".", "--command", "shell"],
    ["--bundle", ".", "--bundle", ".", "--extension-id", EXTENSION_ID]
  ]) {
    assert.throws(
      () => parseMclenovoHandoffArguments(argv),
      (error) => error.code === "MCLENOVO_HANDOFF_ARGUMENTS_INVALID"
        || error.code === "MCLENOVO_HANDOFF_IDENTITY_INVALID"
    );
  }
});
