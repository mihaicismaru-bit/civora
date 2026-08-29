#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  BuildAttestationError,
  createBuildAttestation
} from "../core/build-attestation.mjs";

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!key || argv[index + 1] == null) {
      throw new BuildAttestationError("BUILD_ARGUMENTS_INVALID", "Arguments must be --key value pairs.");
    }
    values[key] = argv[index + 1];
  }
  return values;
}

try {
  const values = parseArguments(process.argv.slice(2));
  const root = resolve(values.root || ".");
  const component = values.component;
  const config = JSON.parse(await readFile(resolve(root, values.config || "build/runtime-files.json"), "utf8"));
  if (config.schemaVersion !== 1 || !Array.isArray(config[component])) {
    throw new BuildAttestationError("BUILD_CONFIG_INVALID", "Runtime file config does not declare the requested component.");
  }
  const files = await Promise.all(config[component].map(async (path) => ({
    path,
    bytes: await readFile(resolve(root, path))
  })));
  const attestation = createBuildAttestation({
    component,
    sourceHead: values["source-head"],
    files
  });
  process.stdout.write(`${JSON.stringify(attestation, null, 2)}\n`);
} catch (error) {
  const payload = error instanceof BuildAttestationError
    ? { status: "FAIL_CLOSED", code: error.code, message: error.message, details: error.details }
    : { status: "FAIL_CLOSED", code: "UNEXPECTED_ERROR", message: error.message };
  process.stderr.write(`${JSON.stringify(payload)}\n`);
  process.exitCode = 1;
}
