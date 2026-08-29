export const ARTIFACT_SELECTORS = "a,button,input[type='button'],input[type='submit'],form,object,embed,iframe";

function bounded(value, maximum = 1_000) {
  return value == null ? null : String(value).replace(/\s+/gu, " ").trim().slice(0, maximum);
}

export function captureCurrentPageSnapshot({
  documentLike,
  locationLike,
  captureId,
  project = null
}) {
  if (!documentLike || typeof documentLike.querySelectorAll !== "function") {
    throw new Error("A readable current-page document is required.");
  }
  const elements = [...documentLike.querySelectorAll(ARTIFACT_SELECTORS)].map((element) => ({
    tag: bounded(element.tagName, 32)?.toLowerCase() || "unknown",
    text: bounded(element.innerText || element.textContent || ""),
    ariaLabel: bounded(element.getAttribute?.("aria-label")),
    title: bounded(element.getAttribute?.("title")),
    name: bounded(element.getAttribute?.("name")),
    value: bounded(element.getAttribute?.("value")),
    href: bounded(element.href),
    action: bounded(element.action),
    src: bounded(element.src),
    data: bounded(element.data),
    method: bounded(element.method || "GET", 16),
    download: Boolean(element.hasAttribute?.("download"))
  }));
  return {
    capture: {
      id: bounded(captureId || `browser-${Date.now()}`, 128),
      kind: "LIVE_DOM_READ_ONLY"
    },
    project,
    page: {
      url: bounded(locationLike?.href, 2_048),
      title: bounded(documentLike.title)
    },
    elements,
    invariants: {
      controlsClicked: 0,
      routeMutations: 0,
      formSubmissions: 0
    }
  };
}
