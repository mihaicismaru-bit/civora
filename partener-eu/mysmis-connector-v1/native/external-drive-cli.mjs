#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { DriveSyncError, syncCommittedObjectToDrive } from "./drive-sync.mjs";
import { createExternalDriveExchangeAdapter } from "./external-drive-adapter.mjs";

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!key || argv[index + 1] == null) throw new DriveSyncError("INVALID_ARGUMENTS", "Arguments must be --key value pairs.");
    values[key] = argv[index + 1];
  }
  return values;
}

try {
  const args = parseArguments(process.argv.slice(2));
  const spoolRoot = resolve(args.spool);
  const exchangeRoot = resolve(args.exchange);
  const receipt = JSON.parse(await readFile(resolve(args.receipt), "utf8"));
  const adapter = createExternalDriveExchangeAdapter({ spoolRoot, exchangeRoot });
  const result = await syncCommittedObjectToDrive({ receipt, spoolRoot, adapter });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
} catch (error) {
  if (error instanceof DriveSyncError && error.code === "EXTERNAL_DRIVE_UPLOAD_PENDING") {
    process.stdout.write(`${JSON.stringify({
      status: "PENDING_EXTERNAL_DRIVE",
      code: error.code,
      ...error.details
    }, null, 2)}\n`);
  } else {
    const payload = error instanceof DriveSyncError
      ? { status: "FAIL_CLOSED", code: error.code, message: error.message, details: error.details }
      : { status: "FAIL_CLOSED", code: "UNEXPECTED_ERROR", message: error.message };
    process.stderr.write(`${JSON.stringify(payload)}\n`);
    process.exitCode = 1;
  }
}
