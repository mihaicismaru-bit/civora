// Structural observation only. No field values, option values or page body are read.
export const CREATE_FORM_MESSAGE = "MYSMIS_INSPECT_CREATE_FORM";
const FIELD_SELECTOR = "input,textarea,select,[role='combobox'],[role='textbox']";
const CONTROL_SELECTOR = "button,input[type='submit'],input[type='button'],a[role='button']";
const AUTH_PATH = /(?:^|\/)(?:login|logout|signin|oauth2|realms|auth)(?:\/|$)/iu;
const PRIVATE_HINT = /password|parol|passwd|secret|nonce|csrf|token|credential|one.?time|otp|mfa|cnp/iu;
const MAX_FIELDS = 120;
const MAX_CONTROLS = 80;

function fail(code) {
  const error = new Error(code);
  error.code = code;
  throw error;
}

function text(value, maximum = 240) {
  return String(value ?? "").replace(/\s+/gu, " ").trim().slice(0, maximum);
}

export function createFormPageIdentity(href) {
  let url;
  try { url = new URL(href); } catch { fail("CREATE_CAPTURE_ORIGIN_DENIED"); }
  // Intentionally exclude the authentication subdomain and every other origin.
  if (url.origin !== "https://mysmis2021.gov.ro" || url.username || url.password) {
    fail("CREATE_CAPTURE_ORIGIN_DENIED");
  }
  if (AUTH_PATH.test(url.pathname)) fail("CREATE_CAPTURE_SIGN_IN_REQUIRED");
  return `${url.origin}${url.pathname}`;
}

function visible(element, view) {
  if (element.hidden || element.closest?.('[hidden],[aria-hidden="true"],[inert]')) return false;
  if (!element.getClientRects?.().length) return false;
  const style = view?.getComputedStyle?.(element);
  return style?.display !== "none" && style?.visibility !== "hidden" && style?.visibility !== "collapse";
}

function labelText(label) {
  // A wrapping label may contain a select with personal option labels. Exclude controls first.
  const clone = label.cloneNode(true);
  for (const child of clone.querySelectorAll(`${FIELD_SELECTOR},button`)) child.remove();
  return text(clone.textContent);
}

function metadata(element) {
  const type = text(element.getAttribute?.("type"), 32).toLowerCase();
  const id = text(element.getAttribute?.("id"), 160);
  const name = text(element.getAttribute?.("name"), 160);
  const autocomplete = text(element.getAttribute?.("autocomplete"), 80);
  if (["hidden", "password", "file"].includes(type)
    || PRIVATE_HINT.test(`${id} ${name} ${autocomplete}`)) return null;
  return { tag: element.tagName.toLowerCase(), type, id, name,
    role: text(element.getAttribute?.("role"), 32),
    label: text([...element.labels ?? []].map(labelText).join(" ")),
    ariaLabel: text(element.getAttribute?.("aria-label")),
    disabled: Boolean(element.disabled || element.getAttribute?.("aria-disabled") === "true"),
    required: Boolean(element.required || element.getAttribute?.("aria-required") === "true") };
}

export function captureCreateFormStructure({ documentLike, locationLike, captureId, capturedAt }) {
  const pageUrl = createFormPageIdentity(locationLike?.href);
  if (!documentLike?.querySelectorAll) fail("CREATE_CAPTURE_DOCUMENT_MISSING");
  const view = documentLike.defaultView;
  if ([...documentLike.querySelectorAll('input[type="password"]')].some((el) => visible(el, view))) {
    fail("CREATE_CAPTURE_SIGN_IN_REQUIRED");
  }
  const fields = [];
  const controls = [];
  for (const element of documentLike.querySelectorAll(FIELD_SELECTOR)) {
    if (!visible(element, view)) continue;
    const value = metadata(element);
    if (!value || ["submit", "button", "reset", "image"].includes(value.type)) continue;
    fields.push({ ...value,
      maxLength: Number.isInteger(element.maxLength) && element.maxLength >= 0 ? element.maxLength : null,
      multiple: Boolean(element.multiple) });
    if (fields.length > MAX_FIELDS) fail("CREATE_CAPTURE_TOO_MANY_FIELDS");
  }
  for (const element of documentLike.querySelectorAll(CONTROL_SELECTOR)) {
    if (!visible(element, view)) continue;
    const value = metadata(element);
    if (!value) continue;
    // Input button captions are values: leave them out rather than read values.
    controls.push({ ...value, text: value.tag === "input" ? "" : text(element.textContent) });
    if (controls.length > MAX_CONTROLS) fail("CREATE_CAPTURE_TOO_MANY_CONTROLS");
  }
  const afterUrl = createFormPageIdentity(locationLike?.href);
  if (afterUrl !== pageUrl) fail("CREATE_CAPTURE_PAGE_CHANGED");
  return {
    schemaVersion: 1,
    kind: "LIVE_CREATE_FORM_STRUCTURE_READ_ONLY",
    captureId: text(captureId, 128), capturedAt,
    page: { url: pageUrl },
    fields, controls,
    status: fields.length ? "STRUCTURE_CAPTURED_NOT_CREATE_READY" : "NO_VISIBLE_FORM_FIELDS",
    omissions: ["field-values", "select-options", "hidden-fields", "page-body", "url-query", "url-fragment"],
    invariants: { controlsClicked: 0, valuesWritten: 0, formSubmissions: 0, authenticatedSessionClaimed: false }
  };
}

export function respondToCreateFormInspection({ message, sender, runtimeId, documentLike, locationLike }) {
  if (message?.type !== CREATE_FORM_MESSAGE) return undefined;
  if (!runtimeId || sender?.id !== runtimeId
    || sender?.url !== `chrome-extension://${runtimeId}/extension/create-inspector.html`) {
    return { ok: false, error: { code: "CREATE_CAPTURE_SENDER_DENIED" } };
  }
  try {
    return { ok: true, snapshot: captureCreateFormStructure({
      documentLike, locationLike, captureId: message.captureId, capturedAt: new Date().toISOString()
    }) };
  } catch (error) {
    return { ok: false, error: { code: /^CREATE_CAPTURE_[A-Z_]+$/u.test(error?.code) ? error.code : "CREATE_CAPTURE_FAILED" } };
  }
}
