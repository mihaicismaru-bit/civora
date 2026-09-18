#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  RestartDedupEvidenceError,
  createRestartDedupEvidenceFailureReceipt,
  verifyRestartDedupVersionEvidence
} from "../core/restart-dedup-evidence.mjs";

const ALLOWED = new Set([
  "representative", "restart", "replay-intake", "replay-sync",
  "version-intake", "version-sync", "version-proposal", "version-readback"
]);

function parse(argv) {
  if (argv.length !== 16) throw new RestartDedupEvidenceError("RESTART_DEDUP_ARGUMENTS_INVALID", "Eight bounded inputs are required.");
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!ALLOWED.has(key) || values[key] || !argv[index + 1]) {
      throw new RestartDedupEvidenceError("RESTART_DEDUP_ARGUMENTS_INVALID", "Unique bounded inputs are required.");
    }
    values[key] = argv[index + 1];
  }
  if ([...ALLOWED].some((key) => !values[key])) {
    throw new RestartDedupEvidenceError("RESTART_DEDUP_ARGUMENTS_INVALID", "Eight bounded inputs are required.");
  }
  return values;
}

async function json(path) {
  let content;
  try { content = await readFile(path, "utf8"); }
  catch { throw new RestartDedupEvidenceError("RESTART_DEDUP_INPUT_UNAVAILABLE", "Restart evidence input is unavailable."); }
  try { return JSON.parse(content); }
  catch { throw new RestartDedupEvidenceError("RESTART_DEDUP_INPUT_INVALID", "Restart evidence input is invalid JSON."); }
}

try {
  const values = parse(process.argv.slice(2));
  const [representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt,
    versionIntakeReceipt, versionDriveReceipt, versionProposal, versionReadbackBytes] = await Promise.all([
    json(values.representative), json(values.restart), json(values["replay-intake"]), json(values["replay-sync"]),
    json(values["version-intake"]), json(values["version-sync"]), json(values["version-proposal"]),
    readFile(values["version-readback"])
  ]);
  process.stdout.write(`${JSON.stringify(verifyRestartDedupVersionEvidence({
    representativeEvidence, restartObservation, replayIntakeReceipt, replayDriveReceipt,
    versionIntakeReceipt, versionDriveReceipt, versionProposal, versionReadbackBytes
  }), null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify(createRestartDedupEvidenceFailureReceipt({ error }))}\n`);
  process.exitCode = 1;
}
