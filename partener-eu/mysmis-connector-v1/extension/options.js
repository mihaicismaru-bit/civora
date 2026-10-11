import {
  EXTENSION_LOOPBACK_CONFIG_KEY,
  ExtensionLoopbackBindingError,
  verifyExtensionLoopbackConfig
} from "./loopback-binding.mjs";

const configInput = document.getElementById("config");
const applyButton = document.getElementById("apply");
const statusOutput = document.getElementById("status");

function parseConfigInput(raw) {
  const parsed = JSON.parse(raw);
  if (parsed && typeof parsed === "object" && !Array.isArray(parsed) && parsed.extensionConfig) {
    return parsed.extensionConfig;
  }
  return parsed;
}

function safeErrorCode(error) {
  if (error instanceof ExtensionLoopbackBindingError) return error.code;
  if (error instanceof SyntaxError) return "MV3_LOOPBACK_CONFIG_JSON_INVALID";
  if (typeof error?.code === "string" && /^[A-Z0-9_]{3,96}$/u.test(error.code)) return error.code;
  return "MV3_LOOPBACK_CONFIG_REJECTED";
}

async function persistVerifiedConfig(verified) {
  try {
    await chrome.storage.local.set({ [EXTENSION_LOOPBACK_CONFIG_KEY]: verified });
  } catch {
    throw new ExtensionLoopbackBindingError(
      "MV3_LOOPBACK_STORAGE_WRITE_FAILED",
      "Verified configuration could not be persisted to extension storage."
    );
  }

  let stored;
  try {
    stored = await chrome.storage.local.get(EXTENSION_LOOPBACK_CONFIG_KEY);
  } catch {
    throw new ExtensionLoopbackBindingError(
      "MV3_LOOPBACK_STORAGE_READ_FAILED",
      "Verified configuration could not be read back from extension storage."
    );
  }

  if (stored?.[EXTENSION_LOOPBACK_CONFIG_KEY] == null) {
    throw new ExtensionLoopbackBindingError(
      "MV3_LOOPBACK_STORAGE_READBACK_MISSING",
      "Verified configuration was not present after storage write."
    );
  }

  let readback;
  try {
    readback = await verifyExtensionLoopbackConfig({
      config: stored[EXTENSION_LOOPBACK_CONFIG_KEY],
      runtimeId: chrome.runtime.id
    });
  } catch (error) {
    throw new ExtensionLoopbackBindingError(
      "MV3_LOOPBACK_STORAGE_READBACK_INVALID",
      `Stored configuration failed exact readback validation: ${safeErrorCode(error)}`
    );
  }

  if (JSON.stringify(readback) !== JSON.stringify(verified)) {
    throw new ExtensionLoopbackBindingError(
      "MV3_LOOPBACK_STORAGE_READBACK_MISMATCH",
      "Stored configuration differs from the verified configuration."
    );
  }

  return readback;
}

statusOutput.textContent = `Ready. Installed extension ID: ${chrome.runtime.id}`;

applyButton.addEventListener("click", async () => {
  statusOutput.textContent = "Validating exact-build configuration…";
  try {
    const config = parseConfigInput(configInput.value);
    const verified = await verifyExtensionLoopbackConfig({ config, runtimeId: chrome.runtime.id });
    await persistVerifiedConfig(verified);
    statusOutput.textContent = `Enabled for verified build ${verified.sourceHead.slice(0, 12)}… and installed extension ${chrome.runtime.id}.`;
  } catch (error) {
    const errorCode = safeErrorCode(error);
    statusOutput.textContent = `Rejected (${errorCode}). Installed extension ID: ${chrome.runtime.id}. Input preserved for diagnosis.`;
  }
});
