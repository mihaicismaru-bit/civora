#!/usr/bin/env python3
"""PARTENER.EU / CIVORA P10 — AFIR official corpus collector.

Discovers and fingerprints public AFIR pages and attached documents. It does NOT
promote deadline, budget, eligibility or scoring changes into material facts.
Those changes remain resolution candidates until authoritative evidence is
reviewed by the existing P10 resolution path.
"""
import datetime as dt
import hashlib
import html
import json
import re
import ssl
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
UA = "PARTENER.EU-CIVORA-AFIR-Ingest/1.0 (+https://partener.eu)"
DOC_EXT = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ods", ".zip")
MATERIAL_TERMS = (
    "termen", "deadline", "eligibil", "buget", "alocare", "punctaj",
    "scoring", "prag de calitate", "criterii de selectie", "criterii de selecție",
)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def norm(url, base=None):
    if base:
        url = urllib.parse.urljoin(base, url)
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or (p.hostname or "").lower() not in HOSTS:
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
        if self._tag == "title": self.title.append(s)
        if self._tag == "h1": self.h1.append(s)
        if self._href is not None: self._a.append(s)


def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()


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


def main():
    old = {x.get("url"): x for x in previous().get("items", [])}
    queue = list(SEEDS)
    seen = set()
    items = []
    errors = []
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
            p = Parser(); p.feed(data.decode("utf-8", "replace"))
            title = clean(" ".join(p.h1) or " ".join(p.title))
            text = clean(" ".join(p.text))[:500000]
            links = p.links
            for href, label in links:
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
        items.append({
            "url": url, "title": title[:500], "contentType": ct, "bytes": len(data),
            "sha256": sha, "textExtracted": bool(text), "textChars": len(text),
            "changedFromPrevious": changed,
            "materialChangeCandidate": material_signal,
            "materialFactAction": "RESOLUTION_TASK_ONLY" if material_signal else "NONE",
        })

    status = "PASS" if len(items) >= 3 else "DEGRADED" if items else "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
    payload = {
        "schemaVersion": 1, "source": "AFIR", "officialHosts": sorted(HOSTS),
        "generatedAt": now(), "status": status, "seedCount": len(SEEDS),
        "items": sorted(items, key=lambda x: x["url"]), "errors": errors[:30],
        "policy": {"failClosed": True, "materialFactsAutoPromoted": False,
                   "materialChanges": "resolution-task-only"},
    }
    CORPUS.parent.mkdir(parents=True, exist_ok=True)
    CORPUS.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    state = {"source": "AFIR", "checkedAt": payload["generatedAt"], "status": status,
             "itemCount": len(items), "errorCount": len(errors),
             "changeCandidates": sum(1 for x in items if x["changedFromPrevious"]),
             "materialResolutionCandidates": sum(1 for x in items if x["materialChangeCandidate"]),
             "failClosed": True}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
