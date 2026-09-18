import { PAGE, PILOT, fail } from "./cyberstep-writer.mjs";
export const ATTEMPT_KEY = "cyberstepPilotAttemptV1";
function activePage(url) { try { const u = new URL(url); return u.origin + u.pathname === PAGE && !u.username && !u.password; } catch { return false; } }
function safeError(error) { return /^CYBERSTEP_[A-Z_]+$/u.test(error?.message) ? error.message : "CYBERSTEP_UNAVAILABLE"; }
export function installCyberstepCoordinator(chromeApi, { now = () => Date.now(), uuid = () => crypto.randomUUID() } = {}) {
  let queue = Promise.resolve();
  let preparation = null;
  const store = chromeApi.storage.local;
  async function active() {
    const tabs = await chromeApi.tabs.query({ active: true, currentWindow: true });
    if (tabs.length !== 1 || !Number.isInteger(tabs[0].id) || !activePage(tabs[0].url)) fail("ACTIVE_TAB_REQUIRED");
    return tabs[0];
  }
  async function send(tab, type, token) {
    const reply = await chromeApi.tabs.sendMessage(tab.id, { type, token }, { frameId: 0 });
    if (!reply?.ok) throw new Error(reply?.error || "CYBERSTEP_PAGE_UNAVAILABLE");
    return reply.result;
  }
  async function run(message) {
    const saved = (await store.get(ATTEMPT_KEY))[ATTEMPT_KEY];
    if (message.type === "CYBERSTEP_STATUS") return { attempt: saved ?? null };
    if (message.type === "CYBERSTEP_READBACK") {
      if (!saved) fail("NO_ATTEMPT_RECORDED");
      const tab = await active();
      if (tab.id !== saved.tabId) fail("TAB_CHANGED");
      const result = await send(tab, "CYBERSTEP_PAGE_READBACK");
      const after = await chromeApi.tabs.get(tab.id);
      if (after.url !== tab.url) fail("TAB_CHANGED");
      const attempt = { ...saved, observation: result, observedAt: now() };
      await store.set({ [ATTEMPT_KEY]: attempt });
      return { attempt };
    }
    if (saved) fail("ATTEMPT_LOCKED_CHECK_PROJECT_LIST");
    const tab = await active();
    if (message.type === "CYBERSTEP_PREPARE") {
      preparation = null;
      const token = uuid();
      const result = await send(tab, "CYBERSTEP_PAGE_PREPARE", token);
      const after = await chromeApi.tabs.get(tab.id);
      if (after.url !== tab.url || result?.token !== token || result?.status !== "PREPARED_NOT_CREATED"
        || Object.keys(PILOT).some(key => result[key] !== PILOT[key])) fail("PREPARE_MISMATCH");
      preparation = { tab, token, at: now() };
      return result;
    }
    const p = preparation;
    preparation = null;
    if (message.type !== "CYBERSTEP_CREATE" || message.fullListChecked !== true) fail("FULL_LIST_CHECK_REQUIRED");
    if (!p || message.token !== p.token || now() - p.at > 120000 || tab.id !== p.tab.id || tab.url !== p.tab.url) fail("PREPARATION_EXPIRED");
    // Durable lock BEFORE sending any submit request. No automatic reset/retry.
    const attempt = { id: uuid(), tabId: tab.id, createdAt: now(), status: "DISPATCH_PENDING_RESULT_UNKNOWN", ...PILOT,
      fullListCheck: "OPERATOR_ATTESTED", automaticDuplicateCheck: "VISIBLE_ROWS_ONLY" };
    await store.set({ [ATTEMPT_KEY]: attempt });
    try {
      const result = await send(tab, "CYBERSTEP_PAGE_COMMIT", p.token);
      if (result?.status !== "CLICK_DISPATCHED_RESULT_UNVERIFIED" || result?.buttonInvocations !== 1
        || Object.keys(PILOT).some(key => result[key] !== PILOT[key])) fail("COMMIT_RESPONSE_MISMATCH");
      attempt.status = result.status;
      attempt.buttonInvocations = 1;
    } catch (error) {
      attempt.status = "RESULT_UNKNOWN_DO_NOT_RETRY";
      attempt.error = safeError(error);
    }
    await store.set({ [ATTEMPT_KEY]: attempt });
    return { attempt };
  }
  chromeApi.runtime.onMessage.addListener((message, sender, respond) => {
    if (!["CYBERSTEP_STATUS", "CYBERSTEP_PREPARE", "CYBERSTEP_CREATE", "CYBERSTEP_READBACK"].includes(message?.type)) return false;
    if (sender?.id !== chromeApi.runtime.id || sender?.url !== `chrome-extension://${chromeApi.runtime.id}/extension/create-inspector.html`) {
      respond({ ok: false, error: "CYBERSTEP_SENDER_DENIED" });
      return false;
    }
    const task = queue.then(() => run(message));
    queue = task.catch(() => undefined);
    task.then(result => respond({ ok: true, result }), error => respond({ ok: false, error: safeError(error) }));
    return true;
  });
}
