import { createExtensionLoopbackClient, FIXED_LOOPBACK_ORIGIN } from "./loopback-client.mjs";
import { createLiveExtensionDispatcher } from "./live-runtime.mjs";

const CONFIG_KEY = "mysmisLoopbackRuntimeV1";
const LAST_CYCLE_KEY = "mysmisLoopbackLastCycleV1";
const ALARM_NAME = "mysmisLoopbackPollV1";
const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const EXTENSION_ID_PATTERN = /^[a-p]{32}$/u;
const HEX64_PATTERN = /^[a-f0-9]{64}$/u;
const CONFIG_KEYS = Object.freeze([
  "agentBuildId", "brokerOrigin", "configurationId", "enabled", "extensionId",
  "pairId", "schemaVersion", "sourceHead"
]);

export class ExtensionLoopbackBindingError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "ExtensionLoopbackBindingError";
    this.code = code;
  }
}

function exactKeys(value, keys) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join(",") === [...keys].sort().join(",");
}

export function validateExtensionLoopbackConfig({ config, runtimeId }) {
  if (!exactKeys(config, CONFIG_KEYS) || config.schemaVersion !== 1 || config.enabled !== true) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_CONFIG_INVALID", "Loopback configuration must match the exact enabled schema.");
  }
  if (!EXTENSION_ID_PATTERN.test(runtimeId) || config.extensionId !== runtimeId) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_CONFIG_EXTENSION_MISMATCH", "Configuration does not match the installed extension ID.");
  }
  if (!BUILD_PATTERN.test(config.sourceHead) || config.agentBuildId !== config.sourceHead) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_CONFIG_BUILD_MISMATCH", "Configuration requires one exact connector/agent build.");
  }
  if (!HEX64_PATTERN.test(config.pairId) || !HEX64_PATTERN.test(config.configurationId)) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_CONFIG_ATTESTATION_INVALID", "Configuration requires bounded pair and configuration identities.");
  }
  if (config.brokerOrigin !== FIXED_LOOPBACK_ORIGIN) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_CONFIG_ORIGIN_DENIED", "Configuration may use only the fixed loopback origin.");
  }
  return Object.freeze({ ...config });
}

async function storeCycle(chromeApi, value, clock) {
  const safe = {
    schemaVersion: 1,
    recordedAt: clock().toISOString(),
    status: value.status,
    commandId: typeof value.commandId === "string" ? value.commandId : null,
    operation: typeof value.operation === "string" ? value.operation : null,
    errorCode: typeof value.errorCode === "string" ? value.errorCode : null,
    liveEvidenceAccepted: false,
    safety: {
      mysmisWrites: 0,
      controlsClicked: 0,
      browserSecretsRead: false,
      arbitraryShell: false
    }
  };
  await chromeApi.storage.session.set({ [LAST_CYCLE_KEY]: safe });
  return safe;
}

export function installExtensionLoopbackBinding({
  chromeApi,
  fetchImpl = globalThis.fetch,
  clock = () => new Date(),
  pollPeriodMinutes = 0.5
}) {
  if (!chromeApi?.runtime?.id || !chromeApi?.storage?.local || !chromeApi?.storage?.session
    || !chromeApi?.alarms?.onAlarm || typeof chromeApi.alarms.create !== "function") {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_BINDING_APIS_MISSING", "Runtime, storage and alarms APIs are required.");
  }
  if (pollPeriodMinutes !== 0.5) {
    throw new ExtensionLoopbackBindingError("MV3_LOOPBACK_POLL_PERIOD_DENIED", "The bounded polling period is fixed at 30 seconds.");
  }

  const runOnce = async () => {
    const stored = await chromeApi.storage.local.get(CONFIG_KEY);
    if (stored?.[CONFIG_KEY] == null) {
      return storeCycle(chromeApi, {
        status: "MV3_LOOPBACK_DISABLED_NO_ATTESTED_CONFIG",
        liveEvidenceAccepted: false
      }, clock);
    }
    let config;
    try {
      config = validateExtensionLoopbackConfig({ config: stored[CONFIG_KEY], runtimeId: chromeApi.runtime.id });
    } catch (error) {
      return storeCycle(chromeApi, {
        status: "MV3_LOOPBACK_DISABLED_INVALID_CONFIG",
        errorCode: error instanceof ExtensionLoopbackBindingError ? error.code : "MV3_LOOPBACK_CONFIG_INVALID",
        liveEvidenceAccepted: false
      }, clock);
    }
    const dispatch = createLiveExtensionDispatcher({
      chromeApi,
      sourceHead: config.sourceHead,
      agentBuildId: config.agentBuildId,
      clock
    });
    const client = createExtensionLoopbackClient({
      sourceHead: config.sourceHead,
      extensionId: config.extensionId,
      brokerOrigin: config.brokerOrigin,
      dispatch,
      fetchImpl,
      clock
    });
    const result = await client.pollOnce();
    return storeCycle(chromeApi, result, clock);
  };

  const alarmListener = (alarm) => {
    if (alarm?.name === ALARM_NAME) runOnce().catch(() => undefined);
  };
  const initialize = async () => {
    await chromeApi.alarms.create(ALARM_NAME, { periodInMinutes: pollPeriodMinutes });
    return runOnce();
  };
  const startupListener = () => initialize().catch(() => undefined);

  chromeApi.alarms.onAlarm.addListener(alarmListener);
  chromeApi.runtime.onInstalled?.addListener?.(startupListener);
  chromeApi.runtime.onStartup?.addListener?.(startupListener);

  return Object.freeze({
    initialize,
    runOnce,
    uninstall() {
      chromeApi.alarms.onAlarm.removeListener?.(alarmListener);
      chromeApi.runtime.onInstalled?.removeListener?.(startupListener);
      chromeApi.runtime.onStartup?.removeListener?.(startupListener);
    }
  });
}

export const EXTENSION_LOOPBACK_CONFIG_KEY = CONFIG_KEY;
export const EXTENSION_LOOPBACK_ALARM_NAME = ALARM_NAME;
