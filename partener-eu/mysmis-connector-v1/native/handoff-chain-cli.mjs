#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import {
  createHandoffChainFailureReceipt,
  HandoffChainError,
  verifyHandoffChain
} from "./handoff-chain.mjs";

function pathFrom(argv) {
  if (argv.length !== 2 || argv[0] !== "--chain" || !argv[1]) {
    throw new HandoffChainError("HANDOFF_CHAIN_ARGUMENTS_INVALID", "Expected exactly --chain path.");
  }
  return argv[1];
}

async function readChain(path) {
  let bytes;
  try {
    bytes = await readFile(path, "utf8");
  } catch {
    throw new HandoffChainError("HANDOFF_CHAIN_INPUT_UNAVAILABLE", "Handoff chain input is unavailable.");
  }
  try {
    return JSON.parse(bytes);
  } catch {
    throw new HandoffChainError("HANDOFF_CHAIN_INPUT_INVALID", "Handoff chain input is not valid JSON.");
  }
}

try {
  const chain = await readChain(pathFrom(process.argv.slice(2)));
  process.stdout.write(`${JSON.stringify(verifyHandoffChain({ chain }), null, 2)}\n`);
} catch (error) {
  process.stderr.write(`${JSON.stringify(createHandoffChainFailureReceipt({ error }))}\n`);
  process.exitCode = 1;
}
