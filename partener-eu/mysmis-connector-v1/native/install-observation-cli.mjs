#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  createInstallObservationFailureReceipt,
  InstallAuthorizationError,
  transitionInstallationState
} from "./install-authorization.mjs";

function parseArguments(argv) {
  if (argv.length !== 4) {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_ARGUMENTS_INVALID", "Expected --current and --observation.");
  }
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!new Set(["current", "observation"]).has(key) || values[key] || argv[index + 1] == null) {
      throw new InstallAuthorizationError("INSTALL_OBSERVATION_ARGUMENTS_INVALID", "Expected unique bounded input arguments.");
    }
    values[key] = argv[index + 1];
  }
  if (!values.current || !values.observation) {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_ARGUMENTS_INVALID", "Expected --current and --observation.");
  }
  return values;
}

async function readJson(path) {
  let bytes;
  try {
    bytes = await readFile(path, "utf8");
  } catch {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_INPUT_UNAVAILABLE", "A required local input is unavailable.");
  }
  try {
    return JSON.parse(bytes);
  } catch {
    throw new InstallAuthorizationError("INSTALL_OBSERVATION_INPUT_INVALID", "A required local input is not valid JSON.");
  }
}

try {
  const values = parseArguments(process.argv.slice(2));
  const [current, event] = await Promise.all([readJson(values.current), readJson(values.observation)]);
  const next = transitionInstallationState({ current, event });
  process.stdout.write(`${JSON.stringify(next, null, 2)}\n`);
} catch (error) {
  const receipt = createInstallObservationFailureReceipt({ error });
  process.stderr.write(`${JSON.stringify(receipt)}\n`);
  process.exitCode = 1;
}
