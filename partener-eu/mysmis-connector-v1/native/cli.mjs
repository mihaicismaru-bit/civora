#!/usr/bin/env node
import { resolve } from "node:path";
import { intakeManualDownload, IntakeError } from "./intake.mjs";

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!key || argv[index + 1] == null) throw new IntakeError("INVALID_ARGUMENTS", "Arguments must be --key value pairs.");
    values[key] = argv[index + 1];
  }
  return values;
}

try {
  const args = parseArguments(process.argv.slice(2));
  const receipt = await intakeManualDownload({
    sourcePath: resolve(args.source),
    spoolRoot: resolve(args.spool),
    metadata: {
      projectCode: args.project,
      track: args.track,
      artifactKind: args.kind,
      logicalName: args.name,
      originalFilename: args.filename,
      declaredMime: args.mime,
      expectedBytes: args.bytes == null ? null : Number(args.bytes),
      sourceChannel: "MANUAL_DOWNLOAD"
    }
  });
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
} catch (error) {
  const payload = error instanceof IntakeError
    ? { status: "FAIL_CLOSED", code: error.code, message: error.message, details: error.details }
    : { status: "FAIL_CLOSED", code: "UNEXPECTED_ERROR", message: error.message };
  process.stderr.write(`${JSON.stringify(payload)}\n`);
  process.exitCode = 1;
}
