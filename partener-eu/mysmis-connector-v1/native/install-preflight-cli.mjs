#!/usr/bin/env node
import {
  createInstallAttemptFailureReceipt,
  InstallPreflightError,
  runInstallPreflight
} from "./install-preflight.mjs";

function parseArguments(argv) {
  if (argv.length !== 4) {
    throw new InstallPreflightError("PREFLIGHT_ARGUMENTS_INVALID", "Expected --bundle and --attempt-id.");
  }
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!new Set(["bundle", "attempt-id"]).has(key) || values[key] || argv[index + 1] == null) {
      throw new InstallPreflightError("PREFLIGHT_ARGUMENTS_INVALID", "Expected unique --bundle and --attempt-id arguments.");
    }
    values[key] = argv[index + 1];
  }
  if (!values.bundle || !values["attempt-id"]) {
    throw new InstallPreflightError("PREFLIGHT_ARGUMENTS_INVALID", "Expected --bundle and --attempt-id.");
  }
  return values;
}

let attemptId = "INVALID_ATTEMPT_ID";
try {
  const values = parseArguments(process.argv.slice(2));
  attemptId = values["attempt-id"];
  const receipt = await runInstallPreflight({ bundleRoot: values.bundle, attemptId });
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
} catch (error) {
  const receipt = createInstallAttemptFailureReceipt({ attemptId, error });
  process.stderr.write(`${JSON.stringify(receipt)}\n`);
  process.exitCode = 1;
}
