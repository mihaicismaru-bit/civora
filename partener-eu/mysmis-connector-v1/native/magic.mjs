import { extname } from "node:path";

const MIME_ALIASES = new Map([
  ["application/x-pdf", "application/pdf"],
  ["application/x-zip-compressed", "application/zip"],
  ["text/json", "application/json"]
]);

const ZIP_CONTAINER_MIMES = new Set([
  "application/zip",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation"
]);

export function normalizeMime(value) {
  if (!value) return null;
  const mime = String(value).split(";", 1)[0].trim().toLowerCase();
  return MIME_ALIASES.get(mime) || mime || null;
}

export function detectMagic(buffer) {
  const bytes = Buffer.isBuffer(buffer) ? buffer : Buffer.from(buffer || []);
  const prefix = bytes.subarray(0, 16);
  const ascii = bytes.subarray(0, 4096).toString("utf8").trimStart().toLowerCase();

  if (prefix.subarray(0, 5).toString("ascii") === "%PDF-") {
    return { family: "PDF", mime: "application/pdf", binary: true };
  }
  if (prefix[0] === 0x50 && prefix[1] === 0x4b && [0x03, 0x05, 0x07].includes(prefix[2])) {
    return { family: "ZIP", mime: "application/zip", binary: true };
  }
  if (prefix[0] === 0xd0 && prefix[1] === 0xcf && prefix[2] === 0x11 && prefix[3] === 0xe0) {
    return { family: "OLE", mime: "application/x-ole-storage", binary: true };
  }
  if (prefix.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) {
    return { family: "PNG", mime: "image/png", binary: true };
  }
  if (prefix[0] === 0xff && prefix[1] === 0xd8 && prefix[2] === 0xff) {
    return { family: "JPEG", mime: "image/jpeg", binary: true };
  }
  if (ascii.startsWith("<!doctype html") || ascii.startsWith("<html") || /<html[\s>]/u.test(ascii.slice(0, 512))) {
    return { family: "HTML", mime: "text/html", binary: false };
  }
  if (ascii.startsWith("<?xml") || ascii.startsWith("<root") || ascii.startsWith("<document")) {
    return { family: "XML", mime: "application/xml", binary: false };
  }
  if (ascii.startsWith("{") || ascii.startsWith("[")) {
    try {
      JSON.parse(bytes.toString("utf8"));
      return { family: "JSON", mime: "application/json", binary: false };
    } catch {
      return { family: "UNKNOWN", mime: null, binary: null };
    }
  }
  return { family: "UNKNOWN", mime: null, binary: null };
}

export function validateMime({ magic, declaredMime, filename }) {
  const declared = normalizeMime(declaredMime);
  const extension = extname(filename || "").toLowerCase();
  const reasons = [];

  if (magic.family === "UNKNOWN") reasons.push("MAGIC_UNKNOWN");
  if (magic.family === "HTML") reasons.push("NON_BINARY_HTML_DENIED");
  if (declared) {
    const compatible = declared === magic.mime
      || (magic.family === "ZIP" && ZIP_CONTAINER_MIMES.has(declared))
      || (magic.family === "XML" && ["application/xml", "text/xml"].includes(declared));
    if (!compatible) reasons.push("DECLARED_MIME_MAGIC_MISMATCH");
  }
  if (extension === ".pdf" && magic.family !== "PDF") reasons.push("PDF_EXTENSION_MAGIC_MISMATCH");
  if ([".docx", ".xlsx", ".pptx", ".zip"].includes(extension) && magic.family !== "ZIP") {
    reasons.push("ZIP_CONTAINER_EXTENSION_MAGIC_MISMATCH");
  }

  return {
    ok: reasons.length === 0,
    reasons,
    declaredMime: declared,
    detectedMime: magic.mime,
    magicFamily: magic.family
  };
}
