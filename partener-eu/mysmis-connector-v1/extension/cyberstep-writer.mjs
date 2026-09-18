// Local popup-only pilot. No generic selectors, scripts or endpoints accepted from messages.
import { createFormPageIdentity } from "./create-form-snapshot.mjs";
export const PILOT = Object.freeze({ title: "CYBERSTEP", applicant: "FUNDAȚIA CENTRUL DE PREGĂTIRE PROFESIONALĂ VÂLCEA", call: "PEO/1160/PEO_P11/OP4/ESO4.7/PEO_A66" });
export const PAGE = "https://mysmis2021.gov.ro/proiect";
export function fail(code) { throw new Error(`CYBERSTEP_${code}`); }
export function norm(value) { return String(value ?? "").normalize("NFD").replace(/\p{M}/gu, "").replace(/\s+/gu, " ").trim().toUpperCase(); }
function visible(el, doc) {
  if (el.hidden || el.closest('[hidden],[aria-hidden="true"],[inert]') || !el.getClientRects().length) return false;
  const css = doc.defaultView.getComputedStyle(el);
  return css.display !== "none" && !["hidden", "collapse"].includes(css.visibility);
}
function shown(root, selector, doc) { return [...root.querySelectorAll(selector)].filter(el => visible(el, doc)); }
function boundedText(el) {
  const value = String(el.innerText ?? "");
  if (value.length > 6000) fail("FORM_SCOPE_TOO_LARGE");
  return norm(value);
}
function assertPage(location) { if (createFormPageIdentity(location.href) !== PAGE) fail("PAGE_DENIED"); }
const FIELDS = 'input:not([type="hidden"]),textarea,select,[role="combobox"]';
// Captured live: title name=nume, two input comboboxes, Adaugă type=submit.
// Wrappers are discovered conservatively, not bound to generated React IDs/classes.
export function bindCreateForm(doc, location) {
  assertPage(location);
  if (shown(doc, 'input[type="password"]', doc).length) fail("SIGN_IN_REQUIRED");
  if (shown(doc, '[role="listbox"],[role="option"]', doc).length) fail("CLOSE_DROPDOWN");
  const titles = shown(doc, 'input[name="nume"]', doc);
  if (titles.length !== 1 || titles[0].type !== "text") fail("TITLE_AMBIGUOUS");
  const title = titles[0];
  let root = title.parentElement;
  let submit;
  for (let depth = 0; root && depth < 12; depth++, root = root.parentElement) {
    if (["BODY", "HTML"].includes(root.tagName)) fail("FORM_NOT_BOUND");
    const buttons = shown(root, 'button[type="submit"]', doc);
    if (!buttons.length) continue;
    if (buttons.length !== 1 || norm(buttons[0].innerText) !== norm("Adaugă")) fail("SUBMIT_AMBIGUOUS");
    if (!boundedText(root).includes(norm("Adaugă proiect"))) continue;
    submit = buttons[0];
    break;
  }
  if (!root || !submit || !boundedText(root).includes(norm("Adaugă proiect"))) fail("FORM_NOT_BOUND");
  const fields = shown(root, FIELDS, doc);
  const combos = fields.filter(el => el.getAttribute("role") === "combobox");
  if (fields.length !== 3 || combos.length !== 2 || !fields.includes(title)) fail("FORM_SCHEMA_CHANGED");
  if (fields.some(el => el.disabled || el.getAttribute("aria-disabled") === "true")) fail("FIELD_DISABLED");
  if (combos.some(el => el.getAttribute("aria-expanded") === "true")) fail("CLOSE_DROPDOWN");
  const contexts = combos.map(combo => {
    for (let node = combo.parentElement, depth = 0; node && node !== root && depth < 10; node = node.parentElement, depth++) {
      if (shown(node, FIELDS, doc).length !== 1) break;
      const text = boundedText(node);
      if (text.startsWith(norm("Entitate juridică"))) return { kind: "applicant", text, node };
      if (/^APEL(?:\s|\*)/u.test(text)) return { kind: "call", text, node };
    }
    fail("FIELD_CONTEXT_NOT_BOUND");
  });
  const applicant = contexts.filter(x => x.kind === "applicant");
  const call = contexts.filter(x => x.kind === "call");
  if (applicant.length !== 1 || call.length !== 1) fail("CONTEXT_AMBIGUOUS");
  const applicantValue = applicant[0].text.replace(/^ENTITATE JURIDICA\s*\*?\s*/u, "");
  const expectedApplicant = norm(PILOT.applicant);
  const help = norm("Entitățile juridice se pot adăuga în secțiunea entități juridice.");
  if (applicantValue !== expectedApplicant && applicantValue !== `${expectedApplicant} ${help}`
    && applicantValue !== `${expectedApplicant} ${help.slice(0, -1)}`) fail("APPLICANT_MISMATCH");
  const codes = call[0].text.match(/PEO\/\d+\/PEO_P\d+\/OP\d+\/ESO[\d.]+\/PEO_A\d+/gu) ?? [];
  if (codes.length !== 1 || codes[0] !== PILOT.call) fail("CALL_MISMATCH");
  if (title.value !== "" && title.value !== PILOT.title) fail("TITLE_MISMATCH");
  if (title.maxLength >= 0 && title.maxLength < PILOT.title.length) fail("TITLE_TOO_LONG");
  return { root, title, submit, applicant: applicant[0].node, call: call[0].node };
}
// This is only a visible-list duplicate check, never an all-pages assertion.
export function visibleCandidates(doc) {
  return shown(doc, 'tr,[role="row"]', doc).filter(row => norm(row.innerText).includes(PILOT.title));
}
function ensureNoVisibleDuplicate(doc) { if (visibleCandidates(doc).length) fail("VISIBLE_DUPLICATE"); }
export function createPageWriter({ doc, location, now = () => Date.now(), settle = () => new Promise(resolve => setTimeout(resolve, 150)) }) {
  let prepared = null;
  let attempted = false;
  return {
    async prepare(token) {
      if (attempted) fail("ATTEMPT_ALREADY_MADE");
      const before = bindCreateForm(doc, location);
      ensureNoVisibleDuplicate(doc);
      const href = location.href;
      if (before.title.value === "") {
        const setter = Object.getOwnPropertyDescriptor(doc.defaultView.HTMLInputElement.prototype, "value")?.set;
        if (!setter) fail("NATIVE_SETTER_UNAVAILABLE");
        setter.call(before.title, PILOT.title);
        before.title.dispatchEvent(new doc.defaultView.Event("input", { bubbles: true }));
        before.title.dispatchEvent(new doc.defaultView.Event("change", { bubbles: true }));
        await settle();
      }
      const after = bindCreateForm(doc, location);
      if (location.href !== href || after.root !== before.root || after.title.value !== PILOT.title) fail("FORM_CHANGED");
      if (after.submit.disabled || after.submit.getAttribute("aria-disabled") === "true") fail("SUBMIT_DISABLED");
      prepared = { token, href, bound: after, at: now() };
      return { status: "PREPARED_NOT_CREATED", ...PILOT, token, duplicateCheck: "VISIBLE_ROWS_ONLY_OPERATOR_FULL_LIST_CHECK_REQUIRED" };
    },
    commit(token) {
      if (attempted) fail("ATTEMPT_ALREADY_MADE");
      const p = prepared;
      prepared = null;
      if (!p || token !== p.token || now() - p.at > 120000 || location.href !== p.href) fail("PREPARATION_EXPIRED");
      const current = bindCreateForm(doc, location);
      ensureNoVisibleDuplicate(doc);
      if (["root", "title", "submit", "applicant", "call"].some(key => current[key] !== p.bound[key]) || current.title.value !== PILOT.title) fail("FORM_CHANGED");
      if (current.submit.disabled || current.submit.getAttribute("aria-disabled") === "true") fail("SUBMIT_DISABLED");
      attempted = true; // One invocation even when click throws or response is lost.
      current.submit.click();
      return { status: "CLICK_DISPATCHED_RESULT_UNVERIFIED", buttonInvocations: 1, ...PILOT };
    },
    readback() {
      assertPage(location);
      const codes = visibleCandidates(doc).flatMap(row => {
        const cells = shown(row, 'td,[role="cell"]', doc);
        if (!cells.some(cell => norm(cell.innerText) === PILOT.title)) return [];
        return cells.map(cell => String(cell.innerText).trim()).filter(text => /^\d{6}$/u.test(text));
      });
      const unique = [...new Set(codes)];
      return { status: unique.length === 1 ? "CANDIDATE_CODE_CONTEXT_PENDING" : "RESULT_UNVERIFIED",
        smisCode: unique.length === 1 ? unique[0] : null, ...PILOT,
        fullContextVerified: false };
    }
  };
}
export function pageMessageAllowed(message, sender, runtimeId) {
  return ["CYBERSTEP_PAGE_PREPARE", "CYBERSTEP_PAGE_COMMIT", "CYBERSTEP_PAGE_READBACK"].includes(message?.type)
    && sender?.id === runtimeId && !sender?.tab
    && (sender?.url === undefined || sender.url === `chrome-extension://${runtimeId}/extension/background.js`);
}
