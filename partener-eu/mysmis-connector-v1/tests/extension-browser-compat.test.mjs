import assert from "node:assert/strict";
import { mkdir, mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import test from "node:test";

import {
  ExtensionBrowserCompatibilityError,
  verifyExtensionBrowserCompatibility
} from "../scripts/verify-extension-browser-compat.mjs";

async function fixture(files) {
  const root = await mkdtemp(resolve(tmpdir(), "mysmis-mv3-browser-"));
  const paths = Object.keys(files).sort();
  await mkdir(resolve(root, "build"), { recursive: true });
  await writeFile(resolve(root, "build/runtime-files.json"), JSON.stringify({
    schemaVersion: 1,
    EXTENSION: paths
  }));
  for (const [name, source] of Object.entries(files)) {
    await mkdir(dirname(resolve(root, name)), { recursive: true });
    await writeFile(resolve(root, name), source);
  }
  return root;
}

test("current attested extension payload and import closure are browser-compatible", async () => {
  const receipt = await verifyExtensionBrowserCompatibility({ root: resolve(".") });
  assert.equal(receipt.status, "MV3_EXTENSION_BROWSER_COMPATIBILITY_VERIFIED");
  assert.equal(receipt.nodeBuiltins, 0);
  assert.equal(receipt.nodeGlobals, 0);
  assert.equal(receipt.unattestedImports, 0);
});

test("node-prefixed and bare Node built-ins fail closed", async () => {
  for (const specifier of ["node:crypto", "crypto", "fs/promises"]) {
    const root = await fixture({ "extension/background.js": `import value from "${specifier}";\n` });
    await assert.rejects(
      verifyExtensionBrowserCompatibility({ root }),
      (error) => error instanceof ExtensionBrowserCompatibilityError
        && error.code === "MV3_NODE_BUILTIN_IMPORT_DENIED"
    );
  }
});

test("Node globals fail closed even without an import", async () => {
  const root = await fixture({ "extension/background.js": "const bytes = Buffer.from('denied');\n" });
  await assert.rejects(
    verifyExtensionBrowserCompatibility({ root }),
    (error) => error.code === "MV3_NODE_GLOBAL_DENIED"
  );
});

test("relative imports outside the attested extension payload fail closed", async () => {
  const root = await fixture({ "extension/background.js": "import '../core/missing.mjs';\n" });
  await assert.rejects(
    verifyExtensionBrowserCompatibility({ root }),
    (error) => error.code === "MV3_IMPORT_NOT_ATTESTED"
  );
});
