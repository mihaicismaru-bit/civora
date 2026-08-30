import assert from "node:assert/strict";
import test from "node:test";
import {
  EXTENSION_LOOPBACK_ALARM_NAME,
  EXTENSION_LOOPBACK_CONFIG_KEY,
  installExtensionLoopbackBinding,
  validateExtensionLoopbackConfig
} from "../extension/loopback-binding.mjs";

const BUILD = "8".repeat(40);
const EXTENSION_ID = "a".repeat(32);
const clock = () => new Date("2026-08-30T08:10:00.000Z");

function config(overrides = {}) {
  return {
    schemaVersion: 1,
    enabled: true,
    sourceHead: BUILD,
    agentBuildId: BUILD,
    brokerOrigin: "http://127.0.0.1:43127",
    extensionId: EXTENSION_ID,
    pairId: "b".repeat(64),
    configurationId: "c".repeat(64),
    ...overrides
  };
}

function event() {
  let listener;
  return {
    addListener(value) { listener = value; },
    removeListener(value) { if (listener === value) listener = undefined; },
    fire(value) { return listener?.(value); }
  };
}

function chromeBinding(storedConfig) {
  const alarmEvent = event();
  const installedEvent = event();
  const startupEvent = event();
  const cycles = [];
  const alarms = [];
  const chromeApi = {
    runtime: { id: EXTENSION_ID, onInstalled: installedEvent, onStartup: startupEvent },
    storage: {
      local: { async get(key) { return storedConfig == null ? {} : { [key]: structuredClone(storedConfig) }; } },
      session: {
        async get() { return {}; },
        async set(value) { cycles.push(structuredClone(value)); }
      }
    },
    alarms: {
      onAlarm: alarmEvent,
      async create(name, details) { alarms.push({ name, details }); }
    },
    tabs: { async query() { return []; }, async sendMessage() { throw new Error("not used"); } }
  };
  return { chromeApi, alarmEvent, installedEvent, startupEvent, cycles, alarms };
}

test("missing attested configuration makes zero broker requests", async () => {
  const runtime = chromeBinding();
  let fetches = 0;
  const binding = installExtensionLoopbackBinding({
    chromeApi: runtime.chromeApi,
    fetchImpl: async () => { fetches += 1; },
    clock
  });
  const result = await binding.initialize();
  assert.equal(result.status, "MV3_LOOPBACK_DISABLED_NO_ATTESTED_CONFIG");
  assert.equal(fetches, 0);
  assert.deepEqual(runtime.alarms, [{ name: EXTENSION_LOOPBACK_ALARM_NAME, details: { periodInMinutes: 0.5 } }]);
  assert.equal(runtime.cycles.length, 1);
  assert.equal(runtime.cycles[0].mysmisLoopbackLastCycleV1.safety.mysmisWrites, 0);
});

test("invalid build, extension identity, origin and extra fields are disabled before fetch", async () => {
  for (const invalid of [
    config({ agentBuildId: "7".repeat(40) }),
    config({ extensionId: "d".repeat(32) }),
    config({ brokerOrigin: "http://0.0.0.0:43127" }),
    { ...config(), command: "shell" }
  ]) {
    const runtime = chromeBinding(invalid);
    let fetches = 0;
    const result = await installExtensionLoopbackBinding({
      chromeApi: runtime.chromeApi, fetchImpl: async () => { fetches += 1; }, clock
    }).runOnce();
    assert.equal(result.status, "MV3_LOOPBACK_DISABLED_INVALID_CONFIG");
    assert.equal(fetches, 0);
  }
});

test("valid exact-build configuration polls only the fixed loopback endpoint", async () => {
  const runtime = chromeBinding(config());
  const requests = [];
  const result = await installExtensionLoopbackBinding({
    chromeApi: runtime.chromeApi,
    fetchImpl: async (url, options) => {
      requests.push({ url, options });
      return new Response(null, { status: 204 });
    },
    clock
  }).runOnce();
  assert.equal(result.status, "MV3_LOOPBACK_NO_COMMAND");
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, `http://127.0.0.1:43127/v1/next?extensionId=${EXTENSION_ID}`);
  assert.equal(requests[0].options.credentials, "omit");
  assert.equal(requests[0].options.redirect, "error");
});

test("configuration schema validates exact identities and cannot be broadened", () => {
  const value = validateExtensionLoopbackConfig({ config: config(), runtimeId: EXTENSION_ID });
  assert.equal(value.sourceHead, BUILD);
  assert.equal(value.extensionId, EXTENSION_ID);
  assert.throws(
    () => validateExtensionLoopbackConfig({ config: config({ enabled: false }), runtimeId: EXTENSION_ID }),
    (error) => error.code === "MV3_LOOPBACK_CONFIG_INVALID"
  );
});

test("the alarm listener ignores unrelated alarms and retains no live-evidence claim", async () => {
  const runtime = chromeBinding();
  const binding = installExtensionLoopbackBinding({ chromeApi: runtime.chromeApi, fetchImpl: async () => null, clock });
  runtime.alarmEvent.fire({ name: "unrelated" });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(runtime.cycles.length, 0);
  runtime.alarmEvent.fire({ name: EXTENSION_LOOPBACK_ALARM_NAME });
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.equal(runtime.cycles.length, 1);
  assert.equal(runtime.cycles[0].mysmisLoopbackLastCycleV1.liveEvidenceAccepted, false);
  binding.uninstall();
});

test("the runtime manifest exposes alarms and exact loopback without privileged transports", async () => {
  const manifest = JSON.parse(await (await import("node:fs/promises")).readFile(
    new URL("../manifest.json", import.meta.url), "utf8"
  ));
  assert.equal(manifest.permissions.includes("alarms"), true);
  assert.equal(manifest.host_permissions.includes("http://127.0.0.1/*"), true);
  assert.equal(manifest.permissions.includes("nativeMessaging"), false);
  assert.equal(manifest.permissions.includes("debugger"), false);
  assert.equal(Object.hasOwn(manifest, "externally_connectable"), false);
  assert.equal(EXTENSION_LOOPBACK_CONFIG_KEY, "mysmisLoopbackRuntimeV1");
});
