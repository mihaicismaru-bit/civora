#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  RepresentativeArtifactEvidenceError,
  createRepresentativeArtifactEvidenceFailureReceipt,
  verifyRepresentativeArtifactEvidence
} from "../core/representative-artifact-evidence.mjs";

const ALLOWED = new Set(["benchmark-evidence", "retrieval", "intake", "sync", "proposal", "readback"]);

function parse(argv) {
  if (argv.length !== 12) throw new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_ARGUMENTS_INVALID", "Six bounded inputs are required.");
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!ALLOWED.has(key) || values[key] || !argv[index + 1]) {
      throw new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_ARGUMENTS_INVALID", "Unique bounded inputs are required.");
    }
    values[key] = argv[index + 1];
  }
  if ([...ALLOWED].some((key) => !values[key])) {
    throw new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_ARGUMENTS_INVALID", "Six bounded inputs are required.");
  }
  return values;
}

async function json(path) {
  let content;
  try { content = await readFile(path, "utf8"); }
  catch { throw new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_INPUT_UNAVAILABLE", "Artifact evidence input is unavailable."); }
  try { return JSON.parse(content); }
  catch { throw new RepresentativeArtifactEvidenceError("REPRESENTATIVE_ARTIFACT_INPUT_INVALID", "Artifact evidence input is invalid JSON."); }
}

try {
  const values = parse(process.argv.slice(2));
  const [benchmarkEvidence, retrievalObservation, intakeReceipt, driveReceipt, proposal, readbackBytes] = await Promise.all([
    json(values["benchmark-evidence"]), json(values.retrieval), json(values.intake),
    json(values.sync), json(values.proposal), readFile(values.readback)
  ]);
  process.stdout.write(`${JSON.stringify(verifyRepresentativeArtifactEvidence({
    benchmarkEvidence, retrievalObservation, intakeReceipt, driveReceipt, proposal, readbackBytes
  }), null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify(createRepresentativeArtifactEvidenceFailureReceipt({ error }))}\n`);
  process.exitCode = 1;
}
