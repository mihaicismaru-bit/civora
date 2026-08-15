#!/usr/bin/env python3
"""PARTENER.EU / CIVORA P10 — AFIR official corpus collector.

Discovers and fingerprints public AFIR pages and attached documents. It does NOT
promote deadline, budget, eligibility or scoring changes into material facts.
Those changes remain resolution candidates until authoritative evidence is
reviewed by the existing P10 resolution path. Authentication redirects are
recorded as external access dependencies and never treated as official changes.
"""
import datetime as dt
import hashlib
import html
import json
import os
import re
import ssl
import tempfile
import urllib.parse
import urllib.request
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu" / "ingest" / "state" / "afir_state.json"
CORPUS = ROOT / "partener-eu" / "ingest" / "state" / "afir_corpus.json"

HOSTS = {"afir.ro", "www.afir.ro"}
SEEDS = [
    "https://www.afir.ro/info-la-zi/",
    "https://www.afir.ro/instrumente/sesiuni/sesiuni-primire-proiecte/",
    "https://www.afir.ro/instrumente/sesiuni/detalii-mentiuni-si-informatii-derulare-sesiuni-depunere-proiecte/",
    "https://www.afir.ro/comunicare/utile/dezbatere-publica/",
    "https://www.afir.ro/finantare/",
]
UA = "PARTENER.EU-CIVORA-AFIR-Ingest/1.1 (+https://partener.eu)"
DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ods", ".zip")
MATERIAL_TERMS = (
    "termen", "deadline", "eligibil", "buget", "alocare", "punctaj",
    "scoring", "prag de calitate", "criterii de selectie", "criterii de selecție",
)
AUTH_PATH_MARKERS = (
    "/umbraco/surface/authentication/",
    "/account/login",
    "/signin",
    "/sign-in",
)
AUTH_TEXT_MARKERS = (
    "we can't sign you in",
    "you need to sign in",
    "authentication required",
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def norm(url, base=None):
    if base:
        url = urllib.parse.urljoin(base, url)
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in HOSTS:
        return None
    path = (p.path or "/").lower()
    if any(marker in path for marker in AUTH_PATH_MARKERS):
        return None
    return urllib.parse.urlunparse(("https", p.netloc.lower(), p.path or "/", "", p.query, ""))


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "ro,en;q=0.7"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            data = r.read(12_000_000)
            return {"ok": True, "url": r.geturl(), "status": getattr(r, "status", 200),
                    "content_type": r.headers.get("Content-Type", ""), "data": data}
    except Exception as e:
        return {"ok": False, "url": url, "error": f"{type(e).__name__}: {e}"}


class Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.h1 = []
        self.text = []
        self.links = []
        self._tag = ""
        self._href = None
        self._a = []

    def handle_starttag(self, tag, attrs):
        self._tag = tag
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._a = []

    def handle_endtag(self, tag):
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._a).strip()))
            self._href = None
            self._a = []
        self._tag = ""

    def handle_data(self, data):
        s = data.strip()
        if not s:
            return
        self.text.append(s)
        if self._tag == "title":
            self.title.append(s)
        if self._tag == "h1":
            self.h1.append(s)
        if self._href is not None:
            self._a.append(s)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


def is_auth_dependency(requested_url, final_url, title="", text=""):
    parsed = urllib.parse.urlparse(final_url or requested_url)
    path = (parsed.path or "").lower()
    query = urllib.parse.parse_qs(parsed.query)
    sample = (title + " " + text[:5000]).lower()
    return (
        any(marker in path for marker in AUTH_PATH_MARKERS)
        or any(key.lower() in {"redirecturl", "returnurl"} for key in query)
        or any(marker in sample for marker in AUTH_TEXT_MARKERS)
    )


def auth_link_dependency(href, base):
    """Return a normalized dependency record for an AFIR authentication link."""
    absolute = urllib.parse.urljoin(base, href or "")
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in ("http", "https") or (parsed.hostname or "").lower() not in HOSTS:
        return None
    path = (parsed.path or "").lower()
    if not any(marker in path for marker in AUTH_PATH_MARKERS):
        return None
    return {
        "requestedUrl": absolute,
        "sourcePage": base,
        "status": "AUTH_OR_ACCESS_DEPENDENT",
        "materialFactAction": "NONE",
        "reason": "AFIR exposes this route through an authentication surface; no access was fabricated.",
    }


def doc_text(data, url):
    """Best-effort text for OpenXML; PDFs are fingerprinted and parsed when pypdf is available."""
    low = urllib.parse.urlparse(url).path.lower()
    try:
        if low.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            return clean(" ".join((p.extract_text() or "") for p in reader.pages[:80]))[:500000]
        if low.endswith((".docx", ".xlsx")):
            out = []
            with zipfile.ZipFile(BytesIO(data)) as z:
                names = z.namelist()
                targets = [n for n in names if (low.endswith(".docx") and n.startswith("word/") and n.endswith(".xml")) or
                           (low.endswith(".xlsx") and n.startswith("xl/") and n.endswith(".xml"))]
                for n in targets[:80]:
                    raw = z.read(n).decode("utf-8", "ignore")
                    out.extend(re.findall(r">([^<>]{2,})<", raw))
            return clean(" ".join(out))[:500000]
    except Exception:
        pass
    return ""


def previous():
    try:
        return json.loads(CORPUS.read_text(encoding="utf-8"))
    except Exception:
        return {"items": []}


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build_payload(prior, observed_at, discovered_items, errors, access_dependencies=None):
    access_dependencies = list(access_dependencies or [])
    run_status = "PASS" if len(discovered_items) >= 3 else "DEGRADED" if discovered_items else "SOURCE_UNAVAILABLE"
    last_run = {
        "observedAt": observed_at,
        "status": run_status,
        "discoveredItemCount": len(discovered_items),
        "errorCount": len(errors),
    }
    policy = {
        "failClosed": True,
        "materialFactsAutoPromoted": False,
        "materialChanges": "resolution-task-only",
        "authenticatedRoutes": "external-dependency-only-no-fabricated-access",
        "sourceFailure": "preserve-last-known-good-and-block-dependent-facts-only",
    }
    if run_status != "PASS" and prior.get("items"):
        payload = dict(prior)
        payload.update({
            "schemaVersion": 2,
            "source": "AFIR",
            "officialHosts": sorted(HOSTS),
            "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
            "lastRun": last_run,
            "lastSuccessfulAt": prior.get("generatedAt") or prior.get("lastSuccessfulAt"),
            "errors": errors[:30],
            "accessDependencies": access_dependencies[:100],
            "policy": policy,
        })
        return payload
    return {
        "schemaVersion": 2,
        "source": "AFIR",
        "officialHosts": sorted(HOSTS),
        "generatedAt": observed_at,
        "lastSuccessfulAt": observed_at if run_status == "PASS" else None,
        "lastRun": last_run,
        "status": run_status,
        "seedCount": len(SEEDS),
        "items": sorted(discovered_items, key=lambda x: x["url"]),
        "errors": errors[:30],
        "accessDependencies": access_dependencies[:100],
        "policy": policy,
    }



def classify_page(url, title, text):
    """Classify an AFIR object without promoting material facts."""
    value = clean(f"{url} {title} {text[:2500]}").lower()
    if re.search(r"\bdr\s*[-–]?\s*\d{1,3}\b", value) or "schema de energie" in value or "investalim" in value:
        return "INTERVENTION_OR_CALL"
    if any(token in value for token in ("sesiune de depunere", "sesiuni depuneri", "sesiuni primire", "anunțurilor de primire", "anunturilor de primire")):
        return "SESSION"
    if any(token in value for token in ("ghidul și anexele", "ghidul si anexele", "detalii și anexe", "detalii si anexe", "ghid solicitant")):
        return "GUIDE"
    if any(token in value for token in ("apel de proiecte", "intervenția", "interventia", "transfer de cunoștințe", "transfer de cunostinte")):
        return "CALL_CANDIDATE"
    if url.lower().endswith(DOC_EXT):
        return "DOCUMENT"
    return "GENERIC_SOURCE_PAGE"


def linked_evidence(links, base):
    """Return official document/page references discovered on the source page."""
    documents = []
    relevant_pages = []
    doc_seen = set()
    page_seen = set()
    for href, label in links:
        absolute = norm(href, base)
        if not absolute:
            continue
        path = urllib.parse.urlparse(absolute).path.lower()
        entry = {"name": clean(label) or Path(path).name or "Document oficial", "url": absolute}
        if path.endswith(DOC_EXT):
            if absolute not in doc_seen:
                doc_seen.add(absolute)
                documents.append(entry)
            continue
        signal = clean(f"{label} {absolute}").lower()
        if any(token in signal for token in ("sesiun", "ghid", "apel", "finant", "finanț", "dezbatere", "consult", "anunt", "anunț", "calendar", "dr-", "dr ")):
            if absolute not in page_seen:
                page_seen.add(absolute)
                relevant_pages.append(entry)
    return documents[:80], relevant_pages[:80]

def main():
    prior = previous()
    old = {x.get("url"): x for x in prior.get("items", [])}
    queue = list(SEEDS)
    seen = set()
    items = []
    errors = []
    access_dependencies = []
    access_dependency_urls = set()
    max_pages = 80

    while queue and len(seen) < max_pages:
        url = queue.pop(0)
        url = norm(url)
        if not url or url in seen:
            continue
        seen.add(url)
        r = fetch(url)
        if not r["ok"]:
            errors.append({"url": url, "error": r.get("error")})
            continue
        ct = (r.get("content_type") or "").lower()
        data = r["data"]
        sha = hashlib.sha256(data).hexdigest()
        pathlow = urllib.parse.urlparse(url).path.lower()
        is_doc = pathlow.endswith(DOC_EXT) or not ("html" in ct or pathlow.endswith("/"))
        title = ""
        text = ""
        links = []
        if not is_doc:
            p = Parser()
            p.feed(data.decode("utf-8", "replace"))
            title = clean(" ".join(p.h1) or " ".join(p.title))
            text = clean(" ".join(p.text))[:500000]
            links = p.links
            if is_auth_dependency(url, r.get("url"), title, text):
                access_dependencies.append({
                    "requestedUrl": url,
                    "finalUrl": r.get("url"),
                    "status": "AUTH_OR_ACCESS_DEPENDENT",
                    "materialFactAction": "NONE",
                    "reason": "AFIR redirected the public route to an authentication surface; no access was fabricated.",
                })
                continue
            for href, label in links:
                dependency = auth_link_dependency(href, url)
                if dependency:
                    dep_url = dependency["requestedUrl"]
                    if dep_url not in access_dependency_urls:
                        access_dependency_urls.add(dep_url)
                        access_dependencies.append(dependency)
                    continue
                u = norm(href, url)
                if not u:
                    continue
                lp = urllib.parse.urlparse(u).path.lower()
                signal = (label + " " + u).lower()
                if lp.endswith(DOC_EXT) or any(k in signal for k in ("sesiun", "ghid", "apel", "finant", "finanț", "dezbatere", "consult", "anunt", "anunț", "calendar")):
                    if u not in seen and len(queue) < 250:
                        queue.append(u)
        else:
            title = clean(urllib.parse.unquote(Path(urllib.parse.urlparse(url).path).name))
            text = doc_text(data, url)

        oldrow = old.get(url) or {}
        changed = bool(oldrow.get("sha256") and oldrow.get("sha256") != sha)
        material_signal = changed and any(k in (text[:150000] + " " + title).lower() for k in MATERIAL_TERMS)
        page_class = classify_page(url, title, text)
        document_links, relevant_links = linked_evidence(links, url) if links else ([], [])
        keep_text = page_class in {"INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE", "DOCUMENT"}
        items.append({
            "url": url,
            "title": title[:500],
            "contentType": ct,
            "bytes": len(data),
            "sha256": sha,
            "observedAt": now(),
            "pageClass": page_class,
            "textExtracted": bool(text),
            "textChars": len(text),
            "textPreview": text[:80000] if keep_text else text[:4000],
            "documentLinks": document_links,
            "relevantLinks": relevant_links,
            "changedFromPrevious": changed,
            "materialChangeCandidate": material_signal,
            "materialFactAction": "RESOLUTION_TASK_ONLY" if material_signal else "NONE",
        })

    observed_at = now()
    payload = build_payload(prior, observed_at, items, errors, access_dependencies)
    atomic_json(CORPUS, payload)
    state = {"source": "AFIR", "checkedAt": observed_at, "status": payload["status"],
             "itemCount": len(payload["items"]), "discoveredItemCount": len(items), "errorCount": len(errors),
             "authDependencyCount": len(access_dependencies),
             "changeCandidates": sum(1 for x in items if x["changedFromPrevious"]),
             "materialResolutionCandidates": sum(1 for x in items if x["materialChangeCandidate"]),
             "lastSuccessfulAt": payload.get("lastSuccessfulAt") or payload.get("generatedAt"),
             "lastKnownGoodPreserved": payload["status"] == "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
             "failClosed": True}
    atomic_json(STATE, state)
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
