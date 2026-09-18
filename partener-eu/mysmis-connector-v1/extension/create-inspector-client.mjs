import { CREATE_FORM_MESSAGE, createFormPageIdentity } from "./create-form-snapshot.mjs";

export async function inspectActiveCreateForm(chromeApi, captureId) {
  const tabs = await chromeApi.tabs.query({ active: true, currentWindow: true });
  if (tabs.length !== 1 || !Number.isInteger(tabs[0].id)) throw new Error("CREATE_CAPTURE_ACTIVE_TAB_REQUIRED");
  const tab = tabs[0];
  const pageUrl = createFormPageIdentity(tab.url);
  const response = await chromeApi.tabs.sendMessage(tab.id, { type: CREATE_FORM_MESSAGE, captureId }, { frameId: 0 });
  const after = await chromeApi.tabs.get(tab.id);
  if (after.url !== tab.url) throw new Error("CREATE_CAPTURE_PAGE_CHANGED");
  const snapshot = response?.snapshot;
  if (response?.ok !== true) throw new Error(response?.error?.code || "CREATE_CAPTURE_NO_RESPONSE");
  if (snapshot?.captureId !== captureId || snapshot?.page?.url !== pageUrl
    || snapshot?.kind !== "LIVE_CREATE_FORM_STRUCTURE_READ_ONLY"
    || snapshot?.invariants?.controlsClicked !== 0 || snapshot?.invariants?.valuesWritten !== 0
    || snapshot?.invariants?.formSubmissions !== 0 || snapshot?.invariants?.authenticatedSessionClaimed !== false) {
    throw new Error("CREATE_CAPTURE_RESPONSE_MISMATCH");
  }
  return snapshot;
}
