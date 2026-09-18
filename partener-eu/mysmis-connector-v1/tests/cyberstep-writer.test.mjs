import test from "node:test";
import assert from "node:assert/strict";
import { PILOT, PAGE, bindCreateForm, createPageWriter, pageMessageAllowed } from "../extension/cyberstep-writer.mjs";
import { ATTEMPT_KEY, installCyberstepCoordinator } from "../extension/cyberstep-coordinator.mjs";

// Synthetic DOM adapter fixture; not a claim of browser or live-portal acceptance.
class Element {
  constructor(tag, attrs = {}, text = "", children = []) {
    this.tagName = tag.toUpperCase(); this.attrs = attrs; this.text = text; this.children = children;
    this.disabled = false; this.hidden = false; this.maxLength = -1; this.clicks = 0;
    children.forEach(child => { child.parentElement = this; });
  }
  get type() { return this.attrs.type || "text"; }
  get innerText() { return [this.text, ...this.children.map(child => child.innerText)].join(" "); }
  getAttribute(key) { return this.attrs[key] ?? null; }
  getClientRects() { return this.hidden ? [] : [1]; }
  closest() { for (let p = this; p; p = p.parentElement) if (p.hidden || p.attrs["aria-hidden"] === "true" || p.attrs.inert) return p; return null; }
  matches(selector) {
    const notHidden = selector.includes(':not([type="hidden"])');
    if (notHidden) selector = selector.replace(':not([type="hidden"])', "");
    const match = selector.match(/^(\w+)?(?:\[([\w-]+)="([^"\]]+)"\])?$/u);
    if (!match) throw new Error(`Fixture selector unsupported ${selector}`);
    return (!match[1] || this.tagName === match[1].toUpperCase()) && (!match[2] || this.attrs[match[2]] === match[3]) && (!notHidden || this.attrs.type !== "hidden");
  }
  querySelectorAll(selector) {
    const result = [];
    for (const child of this.children) {
      if (selector.split(",").some(part => child.matches(part))) result.push(child);
      result.push(...child.querySelectorAll(selector));
    }
    return result;
  }
  click() { this.clicks++; if (this.onClick) this.onClick(); }
  dispatchEvent() { return true; }
}
class Input extends Element { get value() { return this._value ?? ""; } set value(value) { this._value = value; } }
const el = (...args) => new Element(...args);
function fixture({ applicant = PILOT.applicant, call = PILOT.call, title = "", duplicate = false } = {}) {
  const titleEl = new Input("input", { name: "nume", type: "text" }); titleEl.value = title;
  const comboA = new Input("input", { role: "combobox", "aria-expanded": "false" });
  const comboC = new Input("input", { role: "combobox", "aria-expanded": "false" });
  const applicantGroup = el("div", {}, `Entitate juridică * ${applicant}`, [comboA]);
  const callGroup = el("div", {}, `Apel * ${call} - STEP-LLL`, [comboC]);
  const button = el("button", { type: "submit" }, "Adaugă");
  const form = el("form", {}, "", [applicantGroup, el("div", {}, "Titlu proiect *", [titleEl]), callGroup, button]);
  const dialog = el("div", { role: "dialog" }, "Adaugă proiect", [form]);
  const row = el("tr", {}, "", [el("td", {}, "123456"), el("td", {}, duplicate ? PILOT.title : "ALT PROIECT")]);
  const doc = el("body", {}, "", [dialog, el("table", {}, "", [row])]);
  doc.defaultView = { HTMLInputElement: Input, Event: class {}, getComputedStyle() { return { display: "block", visibility: "visible" }; } };
  const location = { href: PAGE + "?fixture=1" };
  let clock = 0;
  const writer = createPageWriter({ doc, location, now: () => clock, settle: async () => {} });
  return { doc, location, titleEl, comboA, comboC, applicantGroup, callGroup, button, form, dialog, row, writer, advance() { clock += 120001; } };
}
test("preparation fills only blank title and requires an explicit commit", async () => {
  const f = fixture();
  const result = await f.writer.prepare("token");
  assert.equal(result.status, "PREPARED_NOT_CREATED");
  assert.equal(f.titleEl.value, PILOT.title); assert.equal(f.button.clicks, 0);
  assert.equal(f.writer.commit("token").buttonInvocations, 1);
  assert.equal(f.button.clicks, 1);
  assert.throws(() => f.writer.commit("token"), /ATTEMPT_ALREADY/);
  await assert.rejects(() => f.writer.prepare("new"), /ATTEMPT_ALREADY/);
});
test("mismatched applicant, call, title and visible duplicates stop before any write", async () => {
  for (const options of [{ applicant: "ALT SOLICITANT" }, { applicant: PILOT.applicant + " SUCURSALA" }, { call: "PEO/1161/PEO_P11/OP4/ESO4.7/PEO_A66" }, { title: "ALT TITLU" }, { duplicate: true }]) {
    const f = fixture(options); const before = f.titleEl.value;
    await assert.rejects(() => f.writer.prepare("token"), /CYBERSTEP_/);
    assert.equal(f.button.clicks, 0); assert.equal(f.titleEl.value, before);
  }
});
test("context changes between preparation and click are rejected", async () => {
  for (const mutate of [f => { f.callGroup.text = "Apel * PEO/999/PEO_P11/OP4/ESO4.7/PEO_A66"; }, f => { f.applicantGroup.text = "Entitate juridică * ALT"; }, f => { f.location.href += "2"; }, f => { f.titleEl.value = "ALT"; }, f => { f.button.disabled = true; }, f => { f.comboA.attrs["aria-expanded"] = "true"; }, f => f.advance()]) {
    const f = fixture(); await f.writer.prepare("token"); mutate(f);
    assert.throws(() => f.writer.commit("token"), /CYBERSTEP_/); assert.equal(f.button.clicks, 0);
  }
});
test("extra visible fields, wrong page and detached/scope changes fail closed", async () => {
  for (const mutate of [f => { const other = new Input("input"); other.parentElement = f.form; f.form.children.push(other); }, f => { f.location.href = "https://evil.test/proiect"; }, f => { f.dialog.text = "Editează proiect"; }, f => { f.button.text = "Depune"; }]) {
    const f = fixture(); mutate(f); await assert.rejects(() => f.writer.prepare("token")); assert.equal(f.button.clicks, 0);
  }
});
test("Romanian cedilla/comma variants match; disabled submission is not clicked", async () => {
  const f = fixture({ applicant: PILOT.applicant.replace("Ț", "Ţ") });
  assert.ok(bindCreateForm(f.doc, f.location)); f.button.disabled = true;
  await assert.rejects(() => f.writer.prepare("token"), /SUBMIT_DISABLED/); assert.equal(f.button.clicks, 0);
});
test("a throwing click consumes the page's attempt", async () => {
  const f = fixture(); await f.writer.prepare("token"); f.button.onClick = () => { throw new Error("navigation/lost response"); };
  assert.throws(() => f.writer.commit("token")); assert.throws(() => f.writer.commit("token"), /ATTEMPT_ALREADY/); assert.equal(f.button.clicks, 1);
});
test("readback returns only a candidate, never a fully verified creation", () => {
  const f = fixture({ duplicate: true }); const result = f.writer.readback();
  assert.equal(result.smisCode, "123456"); assert.equal(result.fullContextVerified, false);
  f.row.children[1].text = "CYBERSTEP similar"; assert.equal(f.writer.readback().smisCode, null);
});
test("page writer accepts only same-extension background messages", () => {
  const id = "test-extension"; const msg = { type: "CYBERSTEP_PAGE_COMMIT" };
  assert.equal(pageMessageAllowed(msg, { id, url: `chrome-extension://${id}/extension/background.js` }, id), true);
  assert.equal(pageMessageAllowed(msg, { id }, id), true);
  for (const sender of [{ id: "other" }, { id, tab: { id: 1 } }, { id, url: `chrome-extension://${id}/extension/create-inspector.html` }, { id, url: PAGE }]) assert.equal(pageMessageAllowed(msg, sender, id), false);
});
function runtime({ saved = {}, failStore = false, loseResponse = false, changeAfterPrepare = false } = {}) {
  let listener, counter = 0, commits = 0;
  const id = "test-extension", tab = { id: 8, url: PAGE };
  const sender = { id, url: `chrome-extension://${id}/extension/create-inspector.html` };
  const api = {
    runtime: { id, onMessage: { addListener(fn) { listener = fn; } } },
    storage: { local: { async get(key) { return { [key]: saved[key] }; }, async set(data) { if (failStore) throw new Error("disk error"); Object.assign(saved, structuredClone(data)); } } },
    tabs: {
      async query() { return [{ ...tab }]; }, async get() { return { ...tab }; },
      async sendMessage(tabId, message, options) {
        assert.equal(tabId, 8); assert.deepEqual(options, { frameId: 0 });
        if (message.type === "CYBERSTEP_PAGE_PREPARE") {
          if (changeAfterPrepare) tab.url += "?changed=1";
          return { ok: true, result: { ...PILOT, token: message.token, status: "PREPARED_NOT_CREATED" } };
        }
        if (message.type === "CYBERSTEP_PAGE_COMMIT") {
          commits++; assert.ok(saved[ATTEMPT_KEY], "durable lock must precede commit");
          if (loseResponse) throw new Error("channel closed");
          return { ok: true, result: { ...PILOT, status: "CLICK_DISPATCHED_RESULT_UNVERIFIED", buttonInvocations: 1 } };
        }
        return { ok: true, result: { status: "RESULT_UNVERIFIED" } };
      }
    }
  };
  const boot = () => installCyberstepCoordinator(api, { uuid: () => `id-${++counter}`, now: () => 1 });
  boot();
  return { saved, tab, boot, get commits() { return commits; }, call(message, from = sender) { return new Promise(resolve => listener(message, from, resolve)); } };
}
async function prepared(r) { const reply = await r.call({ type: "CYBERSTEP_PREPARE" }); assert.equal(reply.ok, true); return reply.result.token; }
test("coordinator serializes concurrent create requests and survives restart", async () => {
  const r = runtime(); const token = await prepared(r);
  const requests = await Promise.all([1, 2].map(() => r.call({ type: "CYBERSTEP_CREATE", token, fullListChecked: true })));
  assert.equal(requests.filter(x => x.ok).length, 1); assert.equal(r.commits, 1);
  r.boot(); assert.match((await r.call({ type: "CYBERSTEP_PREPARE" })).error, /ATTEMPT_LOCKED/);
});
test("lost response is durable uncertainty, without automatic retry", async () => {
  const r = runtime({ loseResponse: true }); const token = await prepared(r);
  const result = await r.call({ type: "CYBERSTEP_CREATE", token, fullListChecked: true });
  assert.equal(result.result.attempt.status, "RESULT_UNKNOWN_DO_NOT_RETRY");
  r.boot(); assert.equal((await r.call({ type: "CYBERSTEP_CREATE", token, fullListChecked: true })).ok, false); assert.equal(r.commits, 1);
});
test("storage failure prevents sending the creation request", async () => {
  const r = runtime({ failStore: true }); const token = await prepared(r);
  assert.equal((await r.call({ type: "CYBERSTEP_CREATE", token, fullListChecked: true })).ok, false); assert.equal(r.commits, 0);
});
test("operator full-list check, current tab and fresh prepare are required", async () => {
  for (const mode of ["missing-check", "wrong-token", "changed-tab"]) {
    const r = runtime(); const token = await prepared(r);
    if (mode === "changed-tab") r.tab.id = 9;
    const reply = await r.call({ type: "CYBERSTEP_CREATE", token: mode === "wrong-token" ? "bad" : token, fullListChecked: mode !== "missing-check" });
    assert.equal(reply.ok, false); assert.equal(r.commits, 0); assert.equal(r.saved[ATTEMPT_KEY], undefined);
  }
});
test("navigation during prepare rejects result and cannot create", async () => {
  const r = runtime({ changeAfterPrepare: true }); assert.equal((await r.call({ type: "CYBERSTEP_PREPARE" })).ok, false); assert.equal(r.commits, 0);
});
test("content scripts and other extensions cannot invoke coordinator", async () => {
  const r = runtime();
  for (const sender of [{ id: "other" }, { id: "test-extension", url: PAGE }, { id: "test-extension" }]) {
    assert.equal((await r.call({ type: "CYBERSTEP_PREPARE" }, sender)).error, "CYBERSTEP_SENDER_DENIED");
  }
});
