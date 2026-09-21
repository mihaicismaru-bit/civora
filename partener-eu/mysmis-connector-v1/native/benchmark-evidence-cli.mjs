#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  BenchmarkEvidenceError,
  createBenchmarkEvidenceFailureReceipt,
  verifyBenchmarkDiscoveryEvidence
} from "../core/benchmark-evidence.mjs";

const ALLOWED = new Set(["admission", "benchmarks", "chain", "responses"]);

function parse(argv) {
  if (argv.length !== 8) throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_ARGUMENTS_INVALID", "Four bounded JSON inputs are required.");
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!ALLOWED.has(key) || values[key] || !argv[index + 1]) {
      throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_ARGUMENTS_INVALID", "Unique bounded JSON inputs are required.");
    }
    values[key] = argv[index + 1];
  }
  if ([...ALLOWED].some((key) => !values[key])) {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_ARGUMENTS_INVALID", "Four bounded JSON inputs are required.");
  }
  return values;
}

async function json(path) {
  let content;
  try {
    content = await readFile(path, "utf8");
  } catch {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_INPUT_UNAVAILABLE", "Benchmark evidence input is unavailable.");
  }
  try {
    return JSON.parse(content);
  } catch {
    throw new BenchmarkEvidenceError("BENCHMARK_EVIDENCE_INPUT_INVALID", "Benchmark evidence input is invalid JSON.");
  }
}

try {
  const values = parse(process.argv.slice(2));
  const [handoffChain, benchmarkSpec, admission, responses] = await Promise.all([
    json(values.chain), json(values.benchmarks), json(values.admission), json(values.responses)
  ]);
  process.stdout.write(`${JSON.stringify(verifyBenchmarkDiscoveryEvidence({
    handoffChain, benchmarkSpec, admission, responses
  }), null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify(createBenchmarkEvidenceFailureReceipt({ error }))}\n`);
  process.exitCode = 1;
}
