import assert from "node:assert/strict";
import test from "node:test";
import { captureCreateFormStructure, createFormPageIdentity, respondToCreateFormInspection, CREATE_FORM_MESSAGE } from "../extension/create-form-snapshot.mjs";
import { inspectActiveCreateForm } from "../extension/create-inspector-client.mjs";

// Synthetic structure only: these paths and identifiers are NOT a MySMIS creation schema.
const PAGE = "https://mysmis2021.gov.ro/test-fixture";
const RUNTIME = "a".repeat(32);
const sender = { id: RUNTIME, url: `chrome-extension://${RUNTIME}/extension/create-inspector.html` };

function label(content) {
  return { cloneNode() { return { textContent: content, querySelectorAll() { return []; } }; } };
}
function element(tag, attrs = {}, extras = {}) {
  const item = { tagName: tag.toUpperCase(), labels: [], maxLength: -1,
    getAttribute(name) { return attrs[name] ?? null; },
    getClientRects() { return [1]; }, closest() { return null; }, ...extras };
  // Values/options must never be inspected, even accidentally.
  for (const key of ["value", "options", "selectedOptions", "innerHTML", "outerHTML", "checked", "files"]) {
    Object.defineProperty(item, key, { get() { throw new Error(`PRIVATE_READ:${key}`); } });
  }
  return item;
}
function doc(fields = [], controls = []) {
  return { defaultView: { getComputedStyle() { return { display: "block", visibility: "visible" }; } },
    querySelectorAll(selector) {
      if (selector === 'input[type="password"]') return fields.filter((el) => el.getAttribute("type") === "password");
      if (selector.startsWith("input,textarea")) return fields;
      if (selector.startsWith("button,")) return controls;
      throw new Error(`Unexpected selector: ${selector}`);
    } };
}
function capture(documentLike, href = PAGE) {
  return captureCreateFormStructure({ documentLike, locationLike: { href }, captureId: "fixture-1", capturedAt: "2026-09-18T00:00:00Z" });
}

test("captures native and custom fields without reading their values or options", () => {
  const snapshot = capture(doc([
    element("input", { id: "title", name: "title", type: "text" }, { labels: [label("Titlu proiect")], maxLength: 200, required: true }),
    element("select", { id: "call" }), element("textarea", { id: "summary" }),
    element("div", { role: "combobox", "aria-label": "Apel" })
  ], [element("button", { type: "submit" }, { textContent: "Creează" })]));
  assert.equal(snapshot.fields.length, 4);
  assert.equal(snapshot.fields[0].label, "Titlu proiect");
  assert.equal(snapshot.fields[0].maxLength, 200);
  assert.equal(snapshot.fields[0].required, true);
  assert.equal(snapshot.controls[0].text, "Creează");
  assert.equal(snapshot.status, "STRUCTURE_CAPTURED_NOT_CREATE_READY");
  assert.equal(snapshot.invariants.authenticatedSessionClaimed, false);
});

test("wrapping labels exclude descendant controls before extracting text", () => {
  let removed = false;
  const wrapping = { cloneNode() { return {
    querySelectorAll() { return [{ remove() { removed = true; } }]; },
    get textContent() { assert.equal(removed, true); return "Apel"; }
  }; } };
  assert.equal(capture(doc([element("select", {}, { labels: [wrapping] })])).fields[0].label, "Apel");
});

test("excludes hidden, file, sensitive-identified and invisible fields", () => {
  const fields = [element("input", { type: "hidden" }), element("input", { type: "file" }),
    element("input", { name: "csrf_token" }), element("input", { autocomplete: "one-time-code" }),
    element("input", { name: "cnp" }), element("input", {}, { hidden: true }),
    element("input", {}, { closest() { return {}; } }), element("input", {}, { getClientRects() { return []; } }),
    element("input", { type: "submit" })];
  assert.deepEqual(capture(doc(fields)).fields, []);
});

test("rejects sign-in screens instead of capturing them", () => {
  assert.throws(() => capture(doc([element("input", { type: "password" })])), /SIGN_IN_REQUIRED/);
  for (const url of ["https://auth.mysmis2021.gov.ro/realms/test", "https://mysmis2021.gov.ro/login", "https://mysmis2021.gov.ro/login/oauth2/code/sso"]) {
    assert.throws(() => capture(doc(), url), /ORIGIN_DENIED|SIGN_IN_REQUIRED/);
  }
});

test("excludes authentication-bearing URL query and fragment", () => {
  const result = capture(doc(), `${PAGE}?token=secret&name=private#credential`);
  assert.equal(result.page.url, PAGE);
  assert.doesNotMatch(JSON.stringify(result), /secret|private|credential/);
});

test("denies non-MySMIS origins and embedded credentials", () => {
  for (const url of ["http://mysmis2021.gov.ro/home", "https://mysmis2021.gov.ro.evil.test/home", "https://user:pass@mysmis2021.gov.ro/home", "https://evil.test", "javascript:alert(1)"]) {
    assert.throws(() => createFormPageIdentity(url), /ORIGIN_DENIED/);
  }
});

test("bounds the capture rather than silently dropping excess fields or controls", () => {
  assert.throws(() => capture(doc(Array.from({ length: 121 }, () => element("input")))), /TOO_MANY_FIELDS/);
  assert.throws(() => capture(doc([], Array.from({ length: 81 }, () => element("button")))), /TOO_MANY_CONTROLS/);
});

test("does not read input button values", () => {
  const result = capture(doc([], [element("input", { type: "submit" })]));
  assert.equal(result.controls[0].text, "");
});

test("only the same extension inspector may request a capture", () => {
  const args = { message: { type: CREATE_FORM_MESSAGE, captureId: "1" }, runtimeId: RUNTIME,
    documentLike: doc(), locationLike: { href: PAGE } };
  assert.equal(respondToCreateFormInspection({ ...args, sender }).ok, true);
  for (const badSender of [null, { id: "b".repeat(32), url: sender.url }, { id: RUNTIME, url: PAGE }]) {
    assert.equal(respondToCreateFormInspection({ ...args, sender: badSender }).error.code, "CREATE_CAPTURE_SENDER_DENIED");
  }
  assert.equal(respondToCreateFormInspection({ ...args, message: { type: "CREATE_PROJECT_DRAFT" }, sender }), undefined);
});

test("sanitizes unexpected capture errors", () => {
  const result = respondToCreateFormInspection({ message: { type: CREATE_FORM_MESSAGE }, runtimeId: RUNTIME, sender,
    documentLike: { querySelectorAll() { throw new Error("private form text"); } }, locationLike: { href: PAGE } });
  assert.deepEqual(result, { ok: false, error: { code: "CREATE_CAPTURE_FAILED" } });
});

function client({ tabs = [{ id: 3, url: PAGE }], after = { id: 3, url: PAGE }, transform = (x) => x, broken = false } = {}) {
  const calls = [];
  return { calls, api: { tabs: {
    async query(args) { assert.deepEqual(args, { active: true, currentWindow: true }); return tabs; },
    async sendMessage(id, message, options) {
      calls.push(id);
      assert.equal(id, 3);
      assert.deepEqual(options, { frameId: 0 });
      if (broken) throw new Error("No content script");
      return transform({ ok: true, snapshot: { ...capture(doc()), captureId: message.captureId } });
    },
    async get(id) { assert.equal(id, 3); return after; }
  } } };
}

test("binds one active tab and its main frame, with no fallback to another project", async () => {
  const runtime = client();
  const result = await inspectActiveCreateForm(runtime.api, "request-1");
  assert.equal(result.captureId, "request-1");
  assert.deepEqual(runtime.calls, [3]);
  const unavailable = client({ broken: true });
  await assert.rejects(() => inspectActiveCreateForm(unavailable.api, "request-2"), /No content script/);
  assert.deepEqual(unavailable.calls, [3]);
});

test("rejects missing or ambiguous active tabs without sending a capture", async () => {
  for (const tabs of [[], [{ id: 3 }, { id: 4 }], [{ url: PAGE }]]) {
    const runtime = client({ tabs });
    await assert.rejects(() => inspectActiveCreateForm(runtime.api, "request"), /ACTIVE_TAB_REQUIRED/);
    assert.deepEqual(runtime.calls, []);
  }
});

test("rejects navigation during capture, including same path with changed query", async () => {
  for (const url of [`${PAGE}/other`, `${PAGE}?project=another`]) {
    await assert.rejects(() => inspectActiveCreateForm(client({ after: { id: 3, url } }).api, "request"), /PAGE_CHANGED/);
  }
});

test("rejects wrong capture ID, wrong page, mutable response and false auth claim", async () => {
  for (const patch of [
    { captureId: "wrong" }, { page: { url: `${PAGE}/other` } }, { kind: "CREATED" },
    { invariants: { controlsClicked: 1, valuesWritten: 0, formSubmissions: 0, authenticatedSessionClaimed: false } },
    { invariants: { controlsClicked: 0, valuesWritten: 0, formSubmissions: 0, authenticatedSessionClaimed: true } }
  ]) {
    const runtime = client({ transform: (reply) => ({ ...reply, snapshot: { ...reply.snapshot, ...patch } }) });
    await assert.rejects(() => inspectActiveCreateForm(runtime.api, "request"), /RESPONSE_MISMATCH/);
  }
});
