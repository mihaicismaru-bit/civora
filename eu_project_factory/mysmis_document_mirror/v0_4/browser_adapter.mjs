import {
  buildMirrorReceipt,
  canonicalizeMySmisUrl,
  dedupeCanonicalRoutes,
  rankDirectGetCandidates,
  summarizeReceipt
} from './mirror_core.mjs';

const CAPTURE_KEY = 'mysmis_reader_captures_v03';
const RECEIPT_KEY = 'mysmis_document_mirror_receipt_v040';
const LOAD_TIMEOUT_MS = 14000;
const POST_LOAD_WAIT_MS = 800;

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function projectUuidFromUrl(raw) {
  try {
    return new URL(raw).pathname.match(/\/(?:implementare\/)?proiect\/([^/]+)/)?.[1] || null;
  } catch {
    return null;
  }
}

export async function buildCandidateRoutesForTarget(target, projectUuid, storage = chrome.storage.local) {
  const obj = await storage.get(CAPTURE_KEY);
  const captures = Array.isArray(obj[CAPTURE_KEY]) ? obj[CAPTURE_KEY] : [];
  const names = (target.candidate_names || []).map((n) => n.toLowerCase());
  const routes = [];
  for (const capture of captures) {
    if (projectUuidFromUrl(capture?.url) !== projectUuid) continue;
    const searchable = JSON.stringify({
      pathname: capture.pathname,
      rows: capture.document_rows || [],
      download_candidates: capture.download_candidates || [],
      title: capture.document_title || ''
    }).toLowerCase();
    if (target.strategy === 'DOSAR_CONTRACT' && (capture.pathname || '').includes('/DOSAR_CONTRACT')) {
      routes.push(capture.url);
      continue;
    }
    if (names.some((name) => name && searchable.includes(name))) routes.push(capture.url);
  }
  return dedupeCanonicalRoutes(routes).slice(0, 30);
}

function waitForTabComplete(tabId, timeoutMs = LOAD_TIMEOUT_MS) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (status) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(status);
    };
    const listener = (id, info) => {
      if (id === tabId && info.status === 'complete') finish('complete');
    };
    const timer = setTimeout(() => finish('timeout'), timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
    chrome.tabs.get(tabId).then((tab) => {
      if (tab.status === 'complete') finish('complete');
    }).catch(() => {});
  });
}

async function inspectPage(tabId, target) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: (candidateNames) => {
      const norm = (s) => (s || '').replace(/\s+/g, ' ').trim();
      return Array.from(document.querySelectorAll('a[href]')).map((a) => ({
        text: norm(a.innerText || a.textContent),
        href: a.href,
        download: a.getAttribute('download') || null,
        candidate_name_match: candidateNames.some((n) =>
          norm(`${a.innerText || a.textContent} ${a.href} ${a.getAttribute('download') || ''}`).toLowerCase().includes(n.toLowerCase())
        )
      }));
    },
    args: [target.candidate_names || []]
  });
  return result || [];
}

async function fetchHashAndDownload(tabId, selected, suggestedName) {
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId },
    func: async (href, suggestedName) => {
      try {
        const target = new URL(href, location.href);
        if (target.origin !== location.origin || target.protocol !== 'https:') {
          return { status: 'BLOCKED_NOT_SAME_ORIGIN_GET' };
        }
        const response = await fetch(target.href, { method: 'GET', credentials: 'include', redirect: 'follow' });
        if (!response.ok) return { status: 'BLOCKED_HTTP', http_status: response.status };
        const blob = await response.blob();
        const bytes = await blob.arrayBuffer();
        const digest = await crypto.subtle.digest('SHA-256', bytes);
        const sha256 = Array.from(new Uint8Array(digest)).map((x) => x.toString(16).padStart(2, '0')).join('');
        const contentDisposition = response.headers.get('content-disposition') || '';
        const match = contentDisposition.match(/filename\*?=(?:UTF-8''|\")?([^\";]+)/i);
        const dispositionName = match ? decodeURIComponent(match[1].replace(/^\"|\"$/g, '')) : null;
        const filename = dispositionName || suggestedName || `mysmis_${Date.now()}.bin`;
        const objectUrl = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = objectUrl;
        link.download = filename;
        link.style.display = 'none';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
        return {
          status: 'DOWNLOADED_HASHED',
          filename,
          size: blob.size,
          mime_type: response.headers.get('content-type') || blob.type || 'application/octet-stream',
          sha256,
          source_url: target.href,
          page_url: location.href
        };
      } catch (error) {
        return { status: 'BLOCKED_FETCH_EXCEPTION', error: String(error?.message || error) };
      }
    },
    args: [selected.href, suggestedName]
  });
  return result;
}

export async function acquireTarget(target, projectUuid) {
  const routes = await buildCandidateRoutesForTarget(target, projectUuid);
  const record = { ...target, candidate_routes: routes, attempts: [], final_status: 'BLOCKED_NO_ROUTE' };

  for (const route of routes) {
    let tabId = null;
    try {
      const tab = await chrome.tabs.create({ url: canonicalizeMySmisUrl(route), active: false });
      tabId = tab.id;
      await waitForTabComplete(tabId);
      await sleep(POST_LOAD_WAIT_MS);
      const anchors = await inspectPage(tabId, target);
      const ranked = rankDirectGetCandidates(anchors, target, route);
      if (!ranked.length) {
        record.attempts.push({ route, status: 'BLOCKED_NO_DIRECT_GET' });
        record.final_status = 'BLOCKED_NO_DIRECT_GET';
        continue;
      }
      const selected = ranked[0];
      const fetched = await fetchHashAndDownload(tabId, selected, selected.matched_name || target.candidate_names?.[0]);
      record.attempts.push({ route, selected, ...fetched });
      record.final_status = fetched.status;
      if (fetched.status === 'DOWNLOADED_HASHED') {
        record.selected = fetched;
        break;
      }
    } catch (error) {
      record.attempts.push({ route, status: 'BLOCKED_TAB_EXCEPTION', error: String(error?.message || error) });
      record.final_status = 'BLOCKED_TAB_EXCEPTION';
    } finally {
      if (tabId !== null) {
        try { await chrome.tabs.remove(tabId); } catch {}
      }
    }
  }
  return record;
}

export async function runP0Mirror(queue) {
  const receipt = buildMirrorReceipt({
    project: queue.project,
    project_uuid: queue.project_uuid,
    targets: []
  });
  for (const target of [...queue.targets].sort((a, b) => a.priority - b.priority)) {
    receipt.targets.push(await acquireTarget(target, queue.project_uuid));
    await chrome.storage.local.set({ [RECEIPT_KEY]: receipt });
  }
  receipt.finished_at = new Date().toISOString();
  receipt.summary = summarizeReceipt(receipt);
  await chrome.storage.local.set({ [RECEIPT_KEY]: receipt });
  return receipt;
}
