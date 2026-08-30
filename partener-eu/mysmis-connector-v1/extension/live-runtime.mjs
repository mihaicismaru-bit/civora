import { discoverArtifacts, sanitizeUrl } from "../core/artifact-discovery.mjs";
import { createFixedBridgeDispatcher } from "../core/bridge-dispatcher.mjs";
import { ChromeSessionReplayStore } from "./internal-transport.mjs";

const BUILD_PATTERN = /^[a-f0-9]{40}$/u;
const MYSMIS_HOST = /^(?:[a-z0-9-]+\.)*mysmis2021\.gov\.ro$/iu;
const PROJECT_CODE = /(?:^|\D)\d{6}(?:\D|$)/u;

export class LiveExtensionRuntimeError extends Error {
  constructor(code, message) {
    super(message);
    this.name = "LiveExtensionRuntimeError";
    this.code = code;
  }
}

function browserFamily(userAgent = globalThis.navigator?.userAgent || "") {
  return /Edg\//u.test(userAgent) ? "EDGE" : "CHROME";
}

function isMysmisUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && MYSMIS_HOST.test(url.hostname);
  } catch {
    return false;
  }
}

function snapshotText(snapshot) {
  return JSON.stringify({
    page: snapshot?.page,
    elements: Array.isArray(snapshot?.elements) ? snapshot.elements : []
  });
}

function validateSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.elements) || !isMysmisUrl(snapshot.page?.url)
    || snapshot.invariants?.controlsClicked !== 0
    || snapshot.invariants?.routeMutations !== 0
    || snapshot.invariants?.formSubmissions !== 0) {
    throw new LiveExtensionRuntimeError(
      "MV3_CURRENT_PAGE_SNAPSHOT_INVALID",
      "Current page snapshot must originate from MySMIS and prove zero interaction."
    );
  }
  return snapshot;
}

async function activeMysmisSnapshot(chromeApi) {
  let tabs;
  try {
    tabs = await chromeApi.tabs.query({ active: true, lastFocusedWindow: true });
  } catch {
    return null;
  }
  const tab = Array.isArray(tabs) ? tabs.find((value) => Number.isInteger(value?.id) && isMysmisUrl(value?.url)) : null;
  if (!tab) return null;
  let response;
  try {
    response = await chromeApi.tabs.sendMessage(tab.id, { type: "MYSMIS_CAPTURE_CURRENT_PAGE" });
  } catch {
    return null;
  }
  if (response?.ok !== true) return null;
  return validateSnapshot(response.snapshot);
}

function authenticatedProjectContext(snapshot) {
  if (!snapshot) return false;
  const url = new URL(snapshot.page.url);
  if (/\b(?:login|signin|connect|autentific)/iu.test(url.pathname)) return false;
  return PROJECT_CODE.test(snapshotText(snapshot));
}

function assertProjectBinding(snapshot, projectSelector) {
  if (typeof projectSelector !== "string" || projectSelector.length < 1 || projectSelector.length > 64
    || !snapshotText(snapshot).includes(projectSelector)) {
    throw new LiveExtensionRuntimeError(
      "MV3_PROJECT_CONTEXT_UNPROVEN",
      "Current page does not visibly prove the requested opaque project selector."
    );
  }
}

function sanitizeSnapshot(snapshot, projectSelector, track) {
  const pageUrl = sanitizeUrl(snapshot.page.url, snapshot.page.url);
  return {
    ...snapshot,
    project: { code: projectSelector, track },
    page: { ...snapshot.page, url: pageUrl },
    elements: snapshot.elements.map((element) => ({
      ...element,
      href: sanitizeUrl(element.href, pageUrl),
      action: sanitizeUrl(element.action, pageUrl),
      src: sanitizeUrl(element.src, pageUrl),
      data: sanitizeUrl(element.data, pageUrl)
    }))
  };
}

export function createLiveExtensionDispatcher({
  chromeApi,
  sourceHead,
  agentBuildId = sourceHead,
  clock = () => new Date(),
  userAgent
}) {
  if (!BUILD_PATTERN.test(sourceHead) || !BUILD_PATTERN.test(agentBuildId)) {
    throw new LiveExtensionRuntimeError("MV3_LIVE_BUILD_INVALID", "Live extension runtime requires exact connector and agent builds.");
  }
  if (!chromeApi?.tabs || !chromeApi?.storage?.session) {
    throw new LiveExtensionRuntimeError("MV3_LIVE_CHROME_API_MISSING", "Tabs and session storage APIs are required.");
  }
  const replayStore = new ChromeSessionReplayStore({ storageSession: chromeApi.storage.session });
  return createFixedBridgeDispatcher({
    connectorBuildId: sourceHead,
    agentBuildId,
    replayStore,
    clock,
    healthHandler: async ({ requiredCapabilities }) => {
      const snapshot = await activeMysmisSnapshot(chromeApi);
      return {
        agentBuildId,
        capabilities: requiredCapabilities.map((name) => ({
          name,
          mode: name.startsWith("OBSERVE_") ? "OBSERVE" : "READ_ONLY"
        })),
        runtime: {
          browserFamily: browserFamily(userAgent),
          manifestVersion: 3,
          extensionReady: true,
          nativeAgentReady: true,
          authenticatedSessionPresent: authenticatedProjectContext(snapshot),
          mysmisOriginPresent: Boolean(snapshot)
        }
      };
    },
    discoverHandler: async ({ projectSelector, track }) => {
      const snapshot = await activeMysmisSnapshot(chromeApi);
      if (!snapshot) {
        throw new LiveExtensionRuntimeError("MV3_MYSMIS_PAGE_UNAVAILABLE", "An active readable MySMIS page is required.");
      }
      assertProjectBinding(snapshot, projectSelector);
      const boundedSnapshot = sanitizeSnapshot(snapshot, projectSelector, track);
      const inventory = discoverArtifacts(boundedSnapshot);
      return {
        snapshot: boundedSnapshot,
        reportedCandidateCount: inventory.candidates.length,
        methodsObserved: ["GET"]
      };
    }
  });
}
