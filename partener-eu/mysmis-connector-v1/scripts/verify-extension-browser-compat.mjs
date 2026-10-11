#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { builtinModules } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const SOURCE_FILE = /\.(?:js|mjs)$/u;
const SAFE_PATH = /^(?!\/)(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._/-]+$/u;
const STATIC_IMPORT = /\b(?:import|export)\s+(?:[^"']*?\s+from\s+)?["']([^"']+)["']/gu;
const DYNAMIC_IMPORT = /\bimport\s*\(\s*["']([^"']+)["']\s*\)/gu;
const NODE_GLOBAL = /\b(?:Buffer|__dirname|__filename|process|require)\b/u;
const BUILTINS = new Set(builtinModules.flatMap((name) => {
  const plain = name.replace(/^node:/u, "");
  return [name, plain, plain.split("/", 1)[0]];
}));

export class ExtensionBrowserCompatibilityError extends Error {
  constructor(code, message, details = {}) {
    super(message);
    this.name = "ExtensionBrowserCompatibilityError";
    this.code = code;
    this.details = details;
  }
}

function specifiers(source) {
  const values = [];
  for (const pattern of [STATIC_IMPORT, DYNAMIC_IMPORT]) {
    pattern.lastIndex = 0;
    for (let match = pattern.exec(source); match; match = pattern.exec(source)) values.push(match[1]);
  }
  return [...new Set(values)].sort();
}

function resolveRelative(importer, specifier) {
  const resolved = path.posix.normalize(path.posix.join(path.posix.dirname(importer), specifier));
  if (!SAFE_PATH.test(resolved)) {
    throw new ExtensionBrowserCompatibilityError(
      "MV3_IMPORT_PATH_INVALID",
      "Extension import escapes the attested payload.",
      { importer, specifier }
    );
  }
  return resolved;
}

function assertBrowserSpecifier(importer, specifier) {
  const plain = specifier.replace(/^node:/u, "");
  const base = plain.split("/", 1)[0];
  if (specifier.startsWith("node:") || BUILTINS.has(specifier) || BUILTINS.has(plain) || BUILTINS.has(base)) {
    throw new ExtensionBrowserCompatibilityError(
      "MV3_NODE_BUILTIN_IMPORT_DENIED",
      "Extension payload imports a Node-only built-in.",
      { importer, specifier }
    );
  }
  if (!specifier.startsWith(".") && !specifier.startsWith("/")) {
    throw new ExtensionBrowserCompatibilityError(
      "MV3_BARE_IMPORT_DENIED",
      "Extension payload contains an unresolved bare module import.",
      { importer, specifier }
    );
  }
}

export async function verifyExtensionBrowserCompatibility({ root, configPath = "build/runtime-files.json" }) {
  const config = JSON.parse(await readFile(path.resolve(root, configPath), "utf8"));
  if (config?.schemaVersion !== 1 || !Array.isArray(config.EXTENSION) || config.EXTENSION.length === 0) {
    throw new ExtensionBrowserCompatibilityError("MV3_PAYLOAD_CONFIG_INVALID", "Extension runtime allowlist is missing or invalid.");
  }
  const payload = new Set();
  for (const file of config.EXTENSION) {
    if (typeof file !== "string" || !SAFE_PATH.test(file) || payload.has(file)) {
      throw new ExtensionBrowserCompatibilityError("MV3_PAYLOAD_PATH_INVALID", "Extension runtime paths must be unique and safe.");
    }
    payload.add(file);
  }

  let moduleCount = 0;
  let importEdgeCount = 0;
  for (const file of [...payload].sort()) {
    let source;
    try {
      source = await readFile(path.resolve(root, file), "utf8");
    } catch {
      throw new ExtensionBrowserCompatibilityError(
        "MV3_PAYLOAD_FILE_MISSING",
        "Extension runtime file is missing.",
        { file }
      );
    }
    if (!SOURCE_FILE.test(file)) continue;
    moduleCount += 1;
    if (NODE_GLOBAL.test(source)) {
      throw new ExtensionBrowserCompatibilityError(
        "MV3_NODE_GLOBAL_DENIED",
        "Extension payload references a Node-only global.",
        { file }
      );
    }
    for (const specifier of specifiers(source)) {
      importEdgeCount += 1;
      assertBrowserSpecifier(file, specifier);
      const dependency = resolveRelative(file, specifier);
      if (!payload.has(dependency)) {
        throw new ExtensionBrowserCompatibilityError(
          "MV3_IMPORT_NOT_ATTESTED",
          "Extension import is not included in the attested payload.",
          { importer: file, dependency }
        );
      }
    }
  }
  return Object.freeze({
    schemaVersion: 1,
    status: "MV3_EXTENSION_BROWSER_COMPATIBILITY_VERIFIED",
    payloadFileCount: payload.size,
    moduleCount,
    importEdgeCount,
    nodeBuiltins: 0,
    nodeGlobals: 0,
    unattestedImports: 0
  });
}

async function main() {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
  try {
    process.stdout.write(`${JSON.stringify(await verifyExtensionBrowserCompatibility({ root }))}\n`);
  } catch (error) {
    const code = error instanceof ExtensionBrowserCompatibilityError
      ? error.code : "MV3_BROWSER_COMPATIBILITY_UNEXPECTED_FAILURE";
    process.stderr.write(`${JSON.stringify({ status: "FAIL_CLOSED", code })}\n`);
    process.exitCode = 1;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
