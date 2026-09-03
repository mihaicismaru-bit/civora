import {
  EXTENSION_LOOPBACK_CONFIG_KEY,
  ExtensionLoopbackBindingError,
  verifyExtensionLoopbackConfig
} from "./loopback-binding.mjs";

const configInput = document.getElementById("config");
const applyButton = document.getElementById("apply");
const statusOutput = document.getElementById("status");

applyButton.addEventListener("click", async () => {
  statusOutput.textContent = "Validating exact-build configuration…";
  try {
    const parsed = JSON.parse(configInput.value);
    const verified = await verifyExtensionLoopbackConfig({ config: parsed, runtimeId: chrome.runtime.id });
    await chrome.storage.local.set({ [EXTENSION_LOOPBACK_CONFIG_KEY]: verified });
    configInput.value = "";
    statusOutput.textContent = "Enabled for the verified build and installed extension identity.";
  } catch (error) {
    const errorCode = error instanceof ExtensionLoopbackBindingError
      ? error.code
      : error instanceof SyntaxError
        ? "MV3_LOOPBACK_CONFIG_JSON_INVALID"
        : "MV3_LOOPBACK_CONFIG_REJECTED";
    statusOutput.textContent = `Rejected (${errorCode}). The connector remains disabled.`;
  }
});
