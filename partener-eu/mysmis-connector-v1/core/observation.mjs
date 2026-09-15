import { sanitizeUrl } from "./artifact-discovery.mjs";
import { assertNoSensitivePersistence } from "./policy.mjs";

function boundedString(value, maximum = 512) {
  return value == null ? null : String(value).slice(0, maximum);
}

export function normalizeDownloadObservation(item) {
  const observation = {
    schemaVersion: 1,
    source: "chrome.downloads",
    browserDownloadId: Number.isInteger(item?.id) ? item.id : null,
    url: sanitizeUrl(item?.finalUrl || item?.url, item?.url),
    filename: boundedString(item?.filename, 260),
    mime: boundedString(item?.mime, 120),
    totalBytes: Number.isFinite(item?.totalBytes) ? item.totalBytes : null,
    state: boundedString(item?.state, 32),
    observedAt: new Date().toISOString()
  };
  assertNoSensitivePersistence(observation);
  return observation;
}

export function normalizeResponseMetadata(details) {
  const responseHeaders = Array.isArray(details?.responseHeaders) ? details.responseHeaders : [];
  const findHeader = (name) => responseHeaders.find((header) => header.name?.toLowerCase() === name)?.value;
  const contentLength = Number(findHeader("content-length"));
  const observation = {
    schemaVersion: 1,
    source: "chrome.webRequest.onHeadersReceived",
    requestId: boundedString(details?.requestId, 128),
    method: boundedString(details?.method, 16),
    statusCode: Number.isInteger(details?.statusCode) ? details.statusCode : null,
    url: sanitizeUrl(details?.url, details?.url),
    type: boundedString(details?.type, 40),
    mime: boundedString(findHeader("content-type"), 120),
    contentLength: Number.isFinite(contentLength) ? contentLength : null,
    contentDisposition: boundedString(findHeader("content-disposition"), 260),
    observedAt: new Date().toISOString()
  };
  assertNoSensitivePersistence(observation);
  return observation;
}
