import { lstat, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { createMclenovoRuntime } from "./mclenovo-runtime.mjs";

const MAX_PLAN_BYTES = 1024 * 1024;

function safeFailure(error) {
  return {
    schemaVersion: 1,
    status: "MCLENOVO_RUNTIME_START_REJECTED",
    errorCode: typeof error?.code === "string" ? error.code : "MCLENOVO_RUNTIME_START_REJECTED",
    runtimeStarted: false,
    liveEvidenceAccepted: false,
    safety: { mysmisWrites: 0, arbitraryShell: false, publicPortOpened: false }
  };
}

function parseArgs(argv) {
  if (argv.length !== 4) throw Object.assign(new Error("Invalid arguments."), { code: "MCLENOVO_RUNTIME_ARGUMENTS_INVALID" });
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    if (!["--plan", "--mailbox-root"].includes(argv[index]) || values[argv[index]]) {
      throw Object.assign(new Error("Invalid arguments."), { code: "MCLENOVO_RUNTIME_ARGUMENTS_INVALID" });
    }
    values[argv[index]] = argv[index + 1];
  }
  if (!values["--plan"] || !values["--mailbox-root"]) {
    throw Object.assign(new Error("Missing arguments."), { code: "MCLENOVO_RUNTIME_ARGUMENTS_INVALID" });
  }
  return values;
}

async function readRegularPlan(filePath) {
  const info = await lstat(filePath);
  if (!info.isFile() || info.isSymbolicLink() || info.size <= 0 || info.size > MAX_PLAN_BYTES) {
    throw Object.assign(new Error("Invalid plan file."), { code: "MCLENOVO_RUNTIME_PLAN_FILE_INVALID" });
  }
  return JSON.parse(await readFile(filePath, "utf8"));
}

export async function main(argv = process.argv.slice(2)) {
  let runtime;
  try {
    const args = parseArgs(argv);
    const plan = await readRegularPlan(path.resolve(args["--plan"]));
    runtime = createMclenovoRuntime({ plan, mailboxRoot: path.resolve(args["--mailbox-root"]) });
    const status = await runtime.start();
    process.stdout.write(`${JSON.stringify(status)}\n`);
    const stop = async () => {
      await runtime.stop();
      process.exitCode = 0;
    };
    process.once("SIGINT", stop);
    process.once("SIGTERM", stop);
    return new Promise(() => {});
  } catch (error) {
    await runtime?.stop?.().catch(() => undefined);
    process.stdout.write(`${JSON.stringify(safeFailure(error))}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main();
}

