#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  createAuthorizedInstallationPlan,
  createInstallAuthorizationFailureReceipt,
  InstallAuthorizationError
} from "./install-authorization.mjs";

function parseArguments(argv) {
  if (argv.length !== 4) {
    throw new InstallAuthorizationError("INSTALL_AUTH_ARGUMENTS_INVALID", "Expected --preflight and --authorization.");
  }
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!new Set(["preflight", "authorization"]).has(key) || values[key] || argv[index + 1] == null) {
      throw new InstallAuthorizationError("INSTALL_AUTH_ARGUMENTS_INVALID", "Expected unique bounded input arguments.");
    }
    values[key] = argv[index + 1];
  }
  if (!values.preflight || !values.authorization) {
    throw new InstallAuthorizationError("INSTALL_AUTH_ARGUMENTS_INVALID", "Expected --preflight and --authorization.");
  }
  return values;
}

async function readJson(path) {
  let bytes;
  try {
    bytes = await readFile(path, "utf8");
  } catch {
    throw new InstallAuthorizationError("INSTALL_AUTH_INPUT_UNAVAILABLE", "A required local input is unavailable.");
  }
  try {
    return JSON.parse(bytes);
  } catch {
    throw new InstallAuthorizationError("INSTALL_AUTH_INPUT_INVALID", "A required local input is not valid JSON.");
  }
}

try {
  const values = parseArguments(process.argv.slice(2));
  const [preflightReceipt, authorization] = await Promise.all([
    readJson(values.preflight),
    readJson(values.authorization)
  ]);
  const plan = createAuthorizedInstallationPlan({ preflightReceipt, authorization });
  process.stdout.write(`${JSON.stringify(plan, null, 2)}\n`);
} catch (error) {
  const receipt = createInstallAuthorizationFailureReceipt({ error });
  process.stderr.write(`${JSON.stringify(receipt)}\n`);
  process.exitCode = 1;
}
