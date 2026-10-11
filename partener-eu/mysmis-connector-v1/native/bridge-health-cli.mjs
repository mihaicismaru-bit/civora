#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import {
  BridgeHealthError,
  createBridgeHealthChallenge,
  validateBridgeHealthResponse
} from "../core/bridge-health.mjs";

function parseArguments(argv) {
  const command = argv[0];
  const values = {};
  for (let index = 1; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!key || argv[index + 1] == null) throw new BridgeHealthError("INVALID_ARGUMENTS", "Arguments must be command plus --key value pairs.");
    values[key] = argv[index + 1];
  }
  return { command, values };
}

try {
  const { command, values } = parseArguments(process.argv.slice(2));
  let result;
  if (command === "challenge") {
    result = createBridgeHealthChallenge({
      connectorBuildId: values.build,
      targetLabel: values.target || "MCLENOVO"
    });
  } else if (command === "verify") {
    const challenge = JSON.parse(await readFile(resolve(values.challenge), "utf8"));
    const response = JSON.parse(await readFile(resolve(values.response), "utf8"));
    result = validateBridgeHealthResponse({
      challenge,
      response,
      observedVia: values.observedVia
    });
  } else {
    throw new BridgeHealthError("INVALID_ARGUMENTS", "Command must be challenge or verify.");
  }
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} catch (error) {
  const payload = error instanceof BridgeHealthError
    ? { status: "FAIL_CLOSED", code: error.code, message: error.message, details: error.details }
    : { status: "FAIL_CLOSED", code: "UNEXPECTED_ERROR", message: error.message };
  process.stderr.write(`${JSON.stringify(payload)}\n`);
  process.exitCode = 1;
}
