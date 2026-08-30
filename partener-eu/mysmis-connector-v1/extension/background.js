import {
  normalizeDownloadObservation,
  normalizeResponseMetadata
} from "../core/observation.mjs";
import { installExtensionLoopbackBinding } from "./loopback-binding.mjs";

const MAX_OBSERVATIONS = 100;

async function appendSessionList(key, value) {
  const current = await chrome.storage.session.get(key);
  const values = Array.isArray(current[key]) ? current[key] : [];
  values.push(value);
  await chrome.storage.session.set({ [key]: values.slice(-MAX_OBSERVATIONS) });
}

chrome.runtime.onMessage.addListener((message) => {
  if (message?.type !== "MYSMIS_INVENTORY_DISCOVERED") return;
  chrome.storage.session.set({ latestInventory: message.payload });
});

chrome.downloads.onCreated.addListener((item) => {
  appendSessionList("downloadObservations", normalizeDownloadObservation(item));
});

chrome.downloads.onChanged.addListener(async (delta) => {
  if (!Number.isInteger(delta?.id)) return;
  const [item] = await chrome.downloads.search({ id: delta.id });
  if (item) await appendSessionList("downloadObservations", normalizeDownloadObservation(item));
});

chrome.webRequest.onHeadersReceived.addListener(
  (details) => appendSessionList("responseMetadata", normalizeResponseMetadata(details)),
  { urls: ["https://mysmis2021.gov.ro/*", "https://*.mysmis2021.gov.ro/*"] },
  ["responseHeaders"]
);

const loopbackBinding = installExtensionLoopbackBinding({ chromeApi: chrome });
loopbackBinding.initialize().catch(() => undefined);
