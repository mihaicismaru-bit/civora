(async () => {
  const { discoverArtifacts, planAcquisition } = await import(
    chrome.runtime.getURL("core/artifact-discovery.mjs")
  );

  const selectors = "a,button,input[type='button'],input[type='submit'],form,object,embed,iframe";
  const elements = [...document.querySelectorAll(selectors)].map((element) => ({
    tag: element.tagName.toLowerCase(),
    text: element.innerText || element.textContent || "",
    ariaLabel: element.getAttribute("aria-label"),
    title: element.getAttribute("title"),
    name: element.getAttribute("name"),
    value: element.getAttribute("value"),
    href: element.href || null,
    action: element.action || null,
    src: element.src || null,
    data: element.data || null,
    method: element.method || "GET",
    download: element.hasAttribute("download")
  }));

  const snapshot = {
    capture: { id: `browser-${Date.now()}`, kind: "LIVE_DOM_READ_ONLY" },
    page: { url: location.href, title: document.title },
    elements
  };
  const inventory = discoverArtifacts(snapshot);
  const plan = planAcquisition(inventory);

  chrome.runtime.sendMessage({
    type: "MYSMIS_INVENTORY_DISCOVERED",
    payload: { inventory, plan }
  });
})();
