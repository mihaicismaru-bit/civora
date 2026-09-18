import {
  CONNECTOR_POLICY,
  hasArtifactIntent,
  hasDeniedWriteIntent,
  isSafeMethod
} from "./policy.mjs";

const FILE_EXTENSION = /\.(pdf|docx?|xlsx?|zip|7z|rar|csv|xml|json)(?:$|[?#])/iu;
const SENSITIVE_QUERY_KEY = /^(?:access_?token|auth(?:orization)?|bearer|code|cookie|jwt|key|mfa|password|session|sig(?:nature)?|state|token)$/iu;
const ROUTE_KIND_RULES = [
  ["APPLICATION", /cerere|formular|application/iu],
  ["CONTRACT", /contract|dosar[_\s-]*contract/iu],
  ["MODIFICATION", /modific|act[_\s-]*adițional|act[_\s-]*aditional|notificare/iu],
  ["REPORT", /raport|monitorizare|progres|report/iu],
  ["ATTACHMENT", /anex|attachment|atașament|atasament/iu],
  ["CRITERIA", /criterii|etf|scor/iu],
  ["FORM_SECTION", /obiectiv|justificare|grup[_\s-]*țintă|grup[_\s-]*tinta|buget|indicator|activit|resurse[_\s-]*umane|achizi/iu]
];

const STRATEGY_RANK = Object.freeze({
  DIRECT_URL_SAFE_GET: 10,
  BROWSER_DOWNLOAD_OBSERVE: 20,
  UI_READONLY_DOWNLOAD_OBSERVE: 30,
  ROUTE_METADATA_ONLY: 40,
  MANUAL_DOWNLOAD_REQUIRED: 50,
  OPTIONAL_CDP_PERMISSION_GATED: 60,
  BLOCKED_UNSAFE_METHOD: 900,
  BLOCKED_WRITE_CONTROL: 910,
  NOT_AN_ARTIFACT: 999
});

function normalizeText(value = "") {
  return String(value).replace(/\s+/gu, " ").trim();
}

function stableId(value) {
  let hash = 0x811c9dc5;
  for (const character of value) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 0x01000193);
  }
  return `cand-${(hash >>> 0).toString(16).padStart(8, "0")}`;
}

export function sanitizeUrl(rawUrl, baseUrl) {
  if (!rawUrl) return null;
  const raw = String(rawUrl).trim();
  if (/^(?:blob:|data:)/iu.test(raw)) return raw.split("#", 1)[0];
  let parsed;
  try {
    parsed = new URL(raw, baseUrl);
  } catch {
    return null;
  }
  if (!/^https?:$/iu.test(parsed.protocol)) return null;
  for (const key of [...parsed.searchParams.keys()]) {
    if (SENSITIVE_QUERY_KEY.test(key)) parsed.searchParams.delete(key);
  }
  parsed.hash = "";
  return parsed.toString();
}

export function inferArtifactKind(value = "") {
  for (const [kind, rule] of ROUTE_KIND_RULES) {
    if (rule.test(value)) return kind;
  }
  return "OTHER";
}

function classifyStrategy({ tag, label, url, method, download, approvedReadOnly }) {
  if (hasDeniedWriteIntent(label)) return "BLOCKED_WRITE_CONTROL";
  if (!isSafeMethod(method) && approvedReadOnly !== true) return "BLOCKED_UNSAFE_METHOD";
  if (url?.startsWith("blob:") || url?.startsWith("data:")) return "BROWSER_DOWNLOAD_OBSERVE";
  if (url && (download || FILE_EXTENSION.test(url))) return "DIRECT_URL_SAFE_GET";
  if ((tag === "button" || tag === "input") && hasArtifactIntent(label)) {
    return "UI_READONLY_DOWNLOAD_OBSERVE";
  }
  if (url && (hasArtifactIntent(`${label} ${url}`) || inferArtifactKind(`${label} ${url}`) !== "OTHER")) {
    return "ROUTE_METADATA_ONLY";
  }
  if (["object", "embed", "iframe"].includes(tag) && url) return "BROWSER_DOWNLOAD_OBSERVE";
  return "NOT_AN_ARTIFACT";
}

export function discoverArtifacts(snapshot, policy = CONNECTOR_POLICY) {
  const baseUrl = sanitizeUrl(snapshot?.page?.url, snapshot?.page?.url) || "https://mysmis2021.gov.ro/";
  const elements = Array.isArray(snapshot?.elements) ? snapshot.elements : [];
  const candidates = [];

  for (const [index, element] of elements.entries()) {
    const tag = normalizeText(element.tag || "unknown").toLowerCase();
    const label = normalizeText([
      element.text,
      element.ariaLabel,
      element.title,
      element.name,
      element.value
    ].filter(Boolean).join(" "));
    const method = normalizeText(element.method || "GET").toUpperCase() || "GET";
    const rawUrl = element.href || element.action || element.src || element.data || null;
    const url = sanitizeUrl(rawUrl, baseUrl);
    const approvedReadOnly = element.approvedReadOnly === true;
    const strategy = classifyStrategy({
      tag,
      label,
      url,
      method,
      download: Boolean(element.download),
      approvedReadOnly
    });

    if (strategy === "NOT_AN_ARTIFACT" && !hasDeniedWriteIntent(label)) continue;
    const kind = inferArtifactKind(`${label} ${url || ""}`);
    const canonical = JSON.stringify({ tag, label, url, method, kind, index });
    const blockedReason = strategy === "BLOCKED_WRITE_CONTROL"
      ? "WRITE_ACTION_DENIED"
      : strategy === "BLOCKED_UNSAFE_METHOD"
        ? "NON_SAFE_METHOD_NOT_PROVEN_READ_ONLY"
        : null;

    candidates.push({
      candidateId: stableId(canonical),
      artifactKind: kind,
      label,
      tag,
      method,
      url,
      strategy,
      strategyRank: STRATEGY_RANK[strategy],
      blockedReason,
      automatedActionAllowed: false,
      manualActionRequired: strategy === "UI_READONLY_DOWNLOAD_OBSERVE",
      provenance: {
        pageUrl: baseUrl,
        elementIndex: index,
        fixtureOrCaptureId: snapshot?.capture?.id || null
      }
    });
  }

  return {
    schemaVersion: 1,
    connectorMode: policy.mode,
    project: snapshot?.project || null,
    page: { url: baseUrl, title: normalizeText(snapshot?.page?.title || "") },
    candidates,
    counts: candidates.reduce((acc, candidate) => {
      acc.total += 1;
      acc[candidate.strategy] = (acc[candidate.strategy] || 0) + 1;
      return acc;
    }, { total: 0 }),
    invariants: {
      writeActionsPerformed: 0,
      controlsClicked: 0,
      credentialsCaptured: 0,
      authorizationHeadersPersisted: 0
    }
  };
}

export function planAcquisition(inventory) {
  const candidates = [...(inventory?.candidates || [])];
  const eligible = candidates
    .filter((candidate) => candidate.strategyRank < 900)
    .sort((a, b) => a.strategyRank - b.strategyRank || a.candidateId.localeCompare(b.candidateId));
  const blocked = candidates.filter((candidate) => candidate.strategyRank >= 900);

  return {
    schemaVersion: 1,
    selected: eligible,
    blocked,
    next: eligible[0] || null,
    rule: "Inventory every exposed candidate; prefer the lowest-rank non-mutating strategy; never click automatically.",
    cdpFallback: {
      enabled: false,
      reason: "OPTIONAL_CDP_PERMISSION_GATED"
    }
  };
}
