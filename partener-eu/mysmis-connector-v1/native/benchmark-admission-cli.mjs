#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  BenchmarkAdmissionError,
  createBenchmarkAdmission,
  createBenchmarkAdmissionFailureReceipt
} from "../core/benchmark-admission.mjs";

function parse(argv) {
  if (argv.length !== 4) throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_ARGUMENTS_INVALID", "Expected --chain and --benchmarks.");
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index]?.replace(/^--/u, "");
    if (!new Set(["chain", "benchmarks"]).has(key) || values[key] || !argv[index + 1]) {
      throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_ARGUMENTS_INVALID", "Expected unique --chain and --benchmarks arguments.");
    }
    values[key] = argv[index + 1];
  }
  if (!values.chain || !values.benchmarks) {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_ARGUMENTS_INVALID", "Expected --chain and --benchmarks.");
  }
  return values;
}

async function json(path) {
  let content;
  try {
    content = await readFile(path, "utf8");
  } catch {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_INPUT_UNAVAILABLE", "Benchmark admission input is unavailable.");
  }
  try {
    return JSON.parse(content);
  } catch {
    throw new BenchmarkAdmissionError("BENCHMARK_ADMISSION_INPUT_INVALID", "Benchmark admission input is invalid JSON.");
  }
}

try {
  const values = parse(process.argv.slice(2));
  const [handoffChain, benchmarkSpec] = await Promise.all([json(values.chain), json(values.benchmarks)]);
  process.stdout.write(`${JSON.stringify(createBenchmarkAdmission({ handoffChain, benchmarkSpec }), null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify(createBenchmarkAdmissionFailureReceipt({ error }))}\n`);
  process.exitCode = 1;
}
