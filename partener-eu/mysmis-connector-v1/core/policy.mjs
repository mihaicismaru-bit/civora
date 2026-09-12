export const CONNECTOR_POLICY = Object.freeze({
  mode: "READ_ONLY_FAIL_CLOSED",
  automatedTraversalAuthorized: false,
  cdpAuthorized: false,
  allowedMethods: Object.freeze(["GET", "HEAD"]),
  deniedActions: Object.freeze([
    "SAVE",
    "SUBMIT",
    "DELETE",
    "SIGN",
    "UPLOAD",
    "MODIFY"
  ]),
  sensitiveFields: Object.freeze([
    "authorization",
    "cookie",
    "set-cookie",
    "password",
    "mfa",
    "localstorage",
    "sessionstorage",
    "token"
  ])
});

const DENIED_LABEL = /(salveaz(?:ă|a)|save|trimite|submit|șterge|sterge|delete|semneaz(?:ă|a)|sign|încarc(?:ă|a)|incarc(?:ă|a)|upload|modific(?:ă|a)|modify|editeaz(?:ă|a)|edit)/iu;
const DOWNLOAD_LABEL = /(descarc(?:ă|a)|download|export(?:ă|a)?|tipărește|tipareste|print|formular|document|raport|contract|notificare|cerere|anex(?:ă|a))/iu;

export function hasDeniedWriteIntent(value = "") {
  return DENIED_LABEL.test(String(value));
}

export function hasArtifactIntent(value = "") {
  return DOWNLOAD_LABEL.test(String(value));
}

export function isSafeMethod(method = "GET") {
  return CONNECTOR_POLICY.allowedMethods.includes(String(method).toUpperCase());
}

export function assertNoSensitivePersistence(value, path = "root") {
  if (value == null) return true;
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertNoSensitivePersistence(item, `${path}[${index}]`));
    return true;
  }
  if (typeof value !== "object") return true;

  for (const [key, child] of Object.entries(value)) {
    const normalized = key.toLowerCase().replace(/[^a-z]/g, "");
    if (CONNECTOR_POLICY.sensitiveFields.some((field) => normalized.includes(field))) {
      throw new Error(`Sensitive field denied at ${path}.${key}`);
    }
    assertNoSensitivePersistence(child, `${path}.${key}`);
  }
  return true;
}
