(async () => {
  const { createPageWriter, pageMessageAllowed } = await import(chrome.runtime.getURL("extension/cyberstep-writer.mjs"));
  const writer = createPageWriter({ doc: document, location });
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message?.type?.startsWith("CYBERSTEP_PAGE_")) return false;
    if (!pageMessageAllowed(message, sender, chrome.runtime.id)) {
      sendResponse({ ok: false, error: "CYBERSTEP_SENDER_DENIED" });
      return false;
    }
    Promise.resolve().then(() => {
      if (message.type === "CYBERSTEP_PAGE_PREPARE") return writer.prepare(message.token);
      if (message.type === "CYBERSTEP_PAGE_COMMIT") return writer.commit(message.token);
      return writer.readback();
    }).then(result => sendResponse({ ok: true, result }), error => sendResponse({ ok: false,
      error: /^CYBERSTEP_[A-Z_]+$/u.test(error?.message) ? error.message : "CYBERSTEP_PAGE_UNAVAILABLE" }));
    return true;
  });
  const { respondToCreateFormInspection } = await import(chrome.runtime.getURL("extension/create-form-snapshot.mjs"));
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const response = respondToCreateFormInspection({ message, sender, runtimeId: chrome.runtime.id,
      documentLike: document, locationLike: location });
    if (response === undefined) return false;
    sendResponse(response);
    return false;
  });
  const [{ discoverArtifacts, planAcquisition }, { captureCurrentPageSnapshot }] = await Promise.all([
    import(chrome.runtime.getURL("core/artifact-discovery.mjs")),
    import(chrome.runtime.getURL("extension/page-snapshot.mjs"))
  ]);

  const snapshotCurrentPage = () => captureCurrentPageSnapshot({
    documentLike: document,
    locationLike: location,
    captureId: `browser-${Date.now()}`
  });
  const snapshot = snapshotCurrentPage();
  const inventory = discoverArtifacts(snapshot);
  const plan = planAcquisition(inventory);

  chrome.runtime.sendMessage({
    type: "MYSMIS_INVENTORY_DISCOVERED",
    payload: { inventory, plan }
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== "MYSMIS_CAPTURE_CURRENT_PAGE") return false;
    if (sender?.id !== chrome.runtime.id) {
      sendResponse({ ok: false, error: { code: "MV3_EXTERNAL_SENDER_DENIED" } });
      return false;
    }
    sendResponse({ ok: true, snapshot: snapshotCurrentPage() });
    return false;
  });
})();
