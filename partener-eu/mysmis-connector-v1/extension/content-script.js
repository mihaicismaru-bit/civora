(async () => {
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
