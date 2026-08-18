#!/usr/bin/env python3
"""PARTENER.EU MIPE Windows crawler v3.

Purpose: use a temporary/self-hosted Windows runner in Romania as an official
MIPE collection node. This is a corpus crawler, not a news scraper.

It:
- visits official MIPE pages with a real browser;
- discovers relevant pages across the official host, not only four hard-coded trees;
- inventories and hashes official documents;
- extracts PDF and DOCX text when practical;
- emits page-level lifecycle evidence and call/guide candidates;
- preserves raw page text needed by the downstream dossier engine;
- persists the unseen discovery frontier and resumes it on the next run;
- updates mipe_state.json for backwards compatibility;
- writes mipe_ro_corpus.json as the richer source of truth.

No third-party factual source is accepted. Unknown facts stay unknown.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import io
import json
import os
import re
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu/ingest/state/mipe_state.json"
CORPUS_PATH = ROOT / "partener-eu/ingest/state/mipe_ro_corpus.json"
FEED_PATH = ROOT / "partener-eu/web/mipe-news.js"

OFFICIAL_HOSTS = {"mfe.gov.ro", "www.mfe.gov.ro"}
ROOT_URL = "https://mfe.gov.ro/"
SEEDS = [
    ROOT_URL,
    "https://mfe.gov.ro/ghiduri_peos/",
    "https://mfe.gov.ro/ghiduri_pids/",
    "https://mfe.gov.ro/pdds/despre-program-programare/",
    "https://mfe.gov.ro/pnrr/",
]

MAX_PAGES = max(20, int(os.getenv("MIPE_MAX_PAGES", "120")))
MAX_DEPTH = max(1, int(os.getenv("MIPE_MAX_DEPTH", "3")))
RUNTIME_SECONDS = max(300, int(os.getenv("MIPE_RUNTIME_SECONDS", "1200")))
PAGE_TIMEOUT_MS = max(7000, int(os.getenv("MIPE_PAGE_TIMEOUT_MS", "18000")))
PAGE_WAIT_MS = max(0, int(os.getenv("MIPE_PAGE_WAIT_MS", "350")))
MAX_DOC_BYTES = max(1_000_000, int(os.getenv("MIPE_MAX_DOC_BYTES", "25000000")))
MAX_DOCUMENTS = max(20, int(os.getenv("MIPE_MAX_DOCUMENTS", "160")))
MAX_FRONTIER = max(200, int(os.getenv("MIPE_MAX_FRONTIER", "3000")))
BROWSER_EXECUTABLE = os.getenv("MIPE_BROWSER_EXECUTABLE", "").strip()
HEADLESS = os.getenv("MIPE_HEADLESS", "0").strip().lower() not in {"0", "false", "no"}

DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".7z", ".rar")
ASSET_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".woff2", ".ico")

RELEVANT_TERMS = [
    "apel", "ghid", "solicitant", "finant", "finanț", "fonduri", "program",
    "eligibil", "beneficiar", "buget", "grant", "alocare", "depun", "mysmis",
    "consultare", "dezbatere", "corrigendum", "rectific", "prelung", "termen",
    "rezultat", "select", "contract", "lista proiect", "lista beneficiar",
    "peo", "pids", "poids", "pdds", "pnrr", "ptj", "tranzitie justa",
    "tranziție justă", "step", "fse", "feder", "coeziune", "educa", "ocupare",
    "incluziune", "digital", "energie", "sanatate", "sănătate", "regional",
]
EXCLUDED_TERMS = [
    "post vacant", "concurs recrutare", "declaratie de avere", "declarație de avere",
    "achizitie publica", "achiziție publică", "anunt angajare", "anunț angajare",
    "comunicat anivers", "condolean", "licitatie publica", "licitație publică",
]
GENERIC_PATH_PARTS = {
    "/contact/", "/despre-noi/", "/conducere/", "/organizare/", "/presa/",
    "/politica-de-confidentialitate/", "/cookies/", "/feed/",
}

CONTENT_SELECTORS = [
    ".entry-content", ".elementor-widget-theme-post-content", ".wp-block-post-content",
    "article .post-content", "article", "main article", "main",
]
TITLE_SELECTORS = [
    ".entry-title", ".page-title", ".post-title", "article h1", "main h1", "h1",
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    text = clean(value).lower()
    return text.translate(str.maketrans("ăâîșşțţ", "aaisstt"))


def canonicalize(url: str, base: str | None = None) -> str | None:
    try:
        absolute = urllib.parse.urljoin(base or ROOT_URL, url)
        p = urllib.parse.urlparse(absolute)
        host = (p.hostname or "").lower()
        if p.scheme not in {"http", "https"} or host not in OFFICIAL_HOSTS:
            return None
        path = re.sub(r"/{2,}", "/", p.path or "/")
        query = [
            (k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid"}
        ]
        return urllib.parse.urlunparse(("https", "mfe.gov.ro", path, "", urllib.parse.urlencode(query), ""))
    except Exception:
        return None


def path_ext(url: str) -> str:
    return Path(urllib.parse.urlparse(url).path.lower()).suffix


def is_document(url: str) -> bool:
    return path_ext(url) in DOCUMENT_EXTENSIONS


def is_asset(url: str) -> bool:
    return path_ext(url) in ASSET_EXTENSIONS


def is_generic_url(url: str) -> bool:
    path = urllib.parse.urlparse(url).path.lower()
    if any(path.startswith(x) for x in GENERIC_PATH_PARTS):
        return True
    if re.search(r"/page/\d+/?$", path):
        return False
    return False


def score_link(url: str, text: str, parent: str, depth: int) -> int:
    hay = norm(f"{url} {text}")
    score = 0
    for term in RELEVANT_TERMS:
        if norm(term) in hay:
            score += 8 if norm(term) in norm(text) else 3
    if any(norm(term) in hay for term in EXCLUDED_TERMS):
        score -= 80
    path = urllib.parse.urlparse(url).path.lower()
    if any(seg in path for seg in ("ghid", "apel", "program", "finant", "pdds", "peo", "pids", "poids", "pnrr", "ptj", "step")):
        score += 15
    if parent == ROOT_URL:
        score += 5
    score -= depth * 2
    return score


def relevant_page(title: str, text: str, url: str) -> bool:
    hay = norm(f"{title} {text[:12000]} {url}")
    if any(norm(term) in hay for term in EXCLUDED_TERMS):
        return False
    hits = sum(1 for term in RELEVANT_TERMS if norm(term) in hay)
    return hits >= 2 or any(x in urllib.parse.urlparse(url).path.lower() for x in ("ghid", "apel", "pdds", "peo", "pids", "pnrr", "ptj", "step"))


def classify_event(title: str, text: str) -> str:
    hay = norm(f"{title} {text[:8000]}")
    if any(x in hay for x in ("lista proiectelor selectate", "lista proiectelor aprobate", "rezultatele selectiei", "rezultatele selecției", "lista beneficiarilor")):
        return "RESULTS_PUBLISHED"
    if any(x in hay for x in ("contracte semnate", "contractare", "contractelor de finantare", "contractelor de finanțare")):
        return "CONTRACTING_UPDATE"
    if "prelung" in hay and "termen" in hay:
        return "DEADLINE_EXTENDED"
    if any(x in hay for x in ("corrigendum", "corrigenda", "rectificare", "modificarea ghidului")):
        return "GUIDE_MODIFIED"
    if any(x in hay for x in ("consultare publica", "consultare publică", "dezbatere publica", "dezbatere publică")) and "ghid" in hay:
        return "CONSULTATION_OPENED"
    if any(x in hay for x in ("apelul este deschis", "apel deschis", "se lanseaza apelul", "se lansează apelul", "s a lansat apelul", "lansarea apelului")):
        return "CALL_OPENED"
    if "ghid" in hay and any(x in hay for x in ("ghid final", "ghidul final", "ghid aprobat", "ghidul aprobat", "ordin")):
        return "GUIDE_PUBLISHED"
    if any(x in hay for x in ("inchiderea apelului", "închiderea apelului", "s a inchis apelul", "s-a închis apelul")):
        return "CALL_CLOSED"
    return "OFFICIAL_UPDATE"


def page_class(title: str, text: str, url: str) -> str:
    event = classify_event(title, text)
    if event != "OFFICIAL_UPDATE":
        return "CALL_LIFECYCLE_EVENT"
    hay = norm(f"{title} {text[:10000]} {url}")
    if "ghid" in hay or "apel" in hay or "solicitant" in hay:
        return "CALL_OR_GUIDE"
    if "program" in hay and any(x in hay for x in ("prioritate", "obiectiv specific", "finantare", "finanțare")):
        return "PROGRAMME_PAGE"
    return "OFFICIAL_UPDATE"


def programme_tag(url: str, title: str, text: str) -> str:
    hay = norm(f"{url} {title} {text[:3000]}")
    rules = [
        (("ghiduri_peos", " program educatie si ocupare", " peo "), "PEO"),
        (("ghiduri_pids", "program incluziune", " poids ", " pids "), "PoIDS"),
        (("/pdds/", "program dezvoltare durabila", " pdds "), "PDDS"),
        (("/pnrr/", " pnrr "), "PNRR"),
        (("tranzitie justa", " ptj "), "PTJ"),
    ]
    padded = f" {hay} "
    for needles, tag in rules:
        if any(n in padded for n in needles):
            return tag
    return "MIPE"


def safe_texts(page: Any, selector: str) -> list[str]:
    try:
        return [clean(x) for x in page.locator(selector).all_text_contents() if clean(x)]
    except Exception:
        return []


def choose_title(page: Any, url: str, hint: str = "") -> str:
    candidates: list[str] = []
    if clean(hint):
        candidates.append(clean(hint))
    for sel in ('meta[property="og:title"]', 'meta[name="twitter:title"]'):
        try:
            val = clean(page.locator(sel).first.get_attribute("content"))
            if val:
                candidates.append(val)
        except Exception:
            pass
    for sel in TITLE_SELECTORS:
        candidates.extend(safe_texts(page, sel)[:5])
    try:
        candidates.append(clean(page.title()))
    except Exception:
        pass
    bad = ("ministerul investitiilor si proiectelor europene", "bine ati venit", "search")
    for value in candidates:
        n = norm(value)
        if len(value) >= 8 and not all(x in n for x in bad[:1]) and not n.startswith("search "):
            return value[:500]
    slug = urllib.parse.unquote(urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]).replace("-", " ")
    return clean(slug).capitalize()[:500]


def extract_text(page: Any, title: str) -> tuple[str, str]:
    for selector in CONTENT_SELECTORS:
        texts = safe_texts(page, selector)
        if not texts:
            continue
        candidate = max(texts, key=len)
        if len(candidate) >= 120:
            return candidate[:120000], selector
    try:
        return clean(page.locator("body").inner_text(timeout=7000))[:120000], "body"
    except Exception:
        return "", "unavailable"


def parse_docx(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        return clean(re.sub(r"<[^>]+>", " ", xml))[:120000]
    except Exception:
        return ""


def extract_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(io.BytesIO(data))
        chunks = []
        for page in reader.pages[:250]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
            if sum(len(x) for x in chunks) > 150000:
                break
        return clean("\n".join(chunks))[:120000]
    except Exception:
        return ""


def extract_document(data: bytes, url: str) -> tuple[str, str]:
    ext = path_ext(url)
    if ext == ".pdf":
        text = extract_pdf(data)
        return text, "PDF_TEXT" if text else "HASH_ONLY"
    if ext == ".docx":
        text = parse_docx(data)
        return text, "DOCX_TEXT" if text else "HASH_ONLY"
    if ext in {".csv"}:
        try:
            return data.decode("utf-8-sig", errors="replace")[:120000], "CSV_TEXT"
        except Exception:
            pass
    return "", "HASH_ONLY"


def load_previous() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        state = {"items": [], "runs": []}
    try:
        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    except Exception:
        corpus = {"pages": [], "documents": [], "runs": [], "frontier": []}
    return state, corpus


def main() -> int:
    previous_state, previous_corpus = load_previous()
    started = time.monotonic()
    deadline = started + RUNTIME_SECONDS
    observed_at = now_iso()

    previous_urls = {
        canonicalize(str(p.get("url") or ""))
        for p in previous_corpus.get("pages", [])
        if p.get("url")
    }
    previous_urls.discard(None)
    previous_doc_urls = {
        canonicalize(str(d.get("url") or ""))
        for d in previous_corpus.get("documents", [])
        if d.get("url")
    }
    previous_doc_urls.discard(None)

    queue: list[tuple[int, int, str, int, str, str]] = []
    queued: set[str] = set()
    seen: set[str] = set()
    seq = 0

    def enqueue(url: str, depth: int, hint: str = "", parent: str = ROOT_URL, force: bool = False) -> None:
        nonlocal seq
        u = canonicalize(url, parent)
        if not u or u in queued or u in seen or is_document(u) or is_asset(u) or is_generic_url(u):
            return
        if u in previous_urls and not force:
            return
        score = 1000 if force else score_link(u, hint, parent, depth)
        if not force and depth > 0 and score <= 0:
            return
        seq += 1
        heapq.heappush(queue, (-score, seq, u, depth, clean(hint), parent))
        queued.add(u)

    for seed in SEEDS:
        enqueue(seed, 0, force=True)

    resumed = 0
    for row in previous_corpus.get("frontier") or []:
        before = len(queued)
        enqueue(
            str(row.get("url") or ""),
            int(row.get("depth") or 1),
            str(row.get("hint") or ""),
            str(row.get("parent") or ROOT_URL),
        )
        if len(queued) > before:
            resumed += 1

    pages: list[dict[str, Any]] = []
    documents: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    roots: list[dict[str, Any]] = []
    source_available = False
    seed_urls = {canonicalize(x) for x in SEEDS}

    with sync_playwright() as pw:
        launch: dict[str, Any] = {
            "headless": HEADLESS,
            "args": [
                "--disable-dev-shm-usage", "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-background-networking", "--disable-sync",
            ],
        }
        if BROWSER_EXECUTABLE:
            launch["executable_path"] = BROWSER_EXECUTABLE
        browser = pw.chromium.launch(**launch)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36 Edg/131",
            locale="ro-RO", timezone_id="Europe/Bucharest", viewport={"width": 1440, "height": 1000},
        )
        context.set_default_timeout(6000)
        context.set_default_navigation_timeout(PAGE_TIMEOUT_MS)
        context.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        context.route("**/*", lambda route: route.abort() if route.request.resource_type in {"image", "media", "font"} else route.continue_())

        while queue and len(seen) < MAX_PAGES and time.monotonic() < deadline:
            _rank, _seq, url, depth, hint, parent = heapq.heappop(queue)
            queued.discard(url)
            if url in seen:
                continue
            seen.add(url)
            page = context.new_page()
            print(f"[MIPE V3 {len(seen)}/{MAX_PAGES} d={depth}] {url}", flush=True)
            try:
                response = page.goto(url, wait_until="commit", timeout=PAGE_TIMEOUT_MS)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=min(PAGE_TIMEOUT_MS, 7000))
                except PlaywrightTimeoutError:
                    pass
                if PAGE_WAIT_MS:
                    page.wait_for_timeout(PAGE_WAIT_MS)
                status = response.status if response else 0
                if status and status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                final = canonicalize(page.url)
                if not final:
                    raise RuntimeError("redirect_outside_official_host")
                source_available = True
                title = choose_title(page, final, hint)
                text, selector = extract_text(page, title)
                links = page.locator("a[href]").evaluate_all("els=>els.map(a=>({href:a.href,text:(a.innerText||a.textContent||'').trim()}))")

                doc_refs = []
                for link in links:
                    href = canonicalize(str(link.get("href") or ""), final)
                    if not href:
                        continue
                    label = clean(link.get("text"))
                    if is_document(href):
                        doc_refs.append({"name": label or Path(urllib.parse.urlparse(href).path).name, "url": href})
                        if href not in documents and href not in previous_doc_urls and len(documents) < MAX_DOCUMENTS and time.monotonic() < deadline - 15:
                            try:
                                r = context.request.get(href, timeout=PAGE_TIMEOUT_MS, fail_on_status_code=False)
                                raw = r.body()
                                if r.ok and raw and len(raw) <= MAX_DOC_BYTES:
                                    doc_text, extraction = extract_document(raw, href)
                                    documents[href] = {
                                        "url": href,
                                        "name": label or Path(urllib.parse.urlparse(href).path).name,
                                        "status": r.status,
                                        "contentType": r.headers.get("content-type", ""),
                                        "bytes": len(raw),
                                        "sha256": hashlib.sha256(raw).hexdigest(),
                                        "extraction": extraction,
                                        "textPreview": doc_text,
                                        "observedAt": observed_at,
                                        "source": "MIPE",
                                        "tier": "T1",
                                        "verification": "CANONICAL_OFFICIAL_FETCH",
                                    }
                            except Exception as doc_exc:
                                documents[href] = {"url": href, "name": label, "error": f"{type(doc_exc).__name__}: {doc_exc}", "observedAt": observed_at}
                        continue
                    if depth < MAX_DEPTH:
                        enqueue(href, depth + 1, label, final)

                accepted = relevant_page(title, text, final) and len(text) >= 100
                if accepted:
                    event = classify_event(title, text)
                    pclass = page_class(title, text, final)
                    pages.append({
                        "id": hashlib.sha256(final.encode()).hexdigest()[:20],
                        "url": final,
                        "title": title,
                        "programme": programme_tag(final, title, text),
                        "pageClass": pclass,
                        "kind": event,
                        "summary": clean(text[:1200]),
                        "textPreview": text,
                        "documents": doc_refs[:80],
                        "contentHash": hashlib.sha256(text.encode()).hexdigest(),
                        "contentSelector": selector,
                        "tier": "T1",
                        "source": "MIPE",
                        "observedAt": observed_at,
                        "retrievalTransport": "playwright-edge-direct-romania-v3",
                        "verification": "CANONICAL_OFFICIAL_FETCH",
                    })
                if url in seed_urls:
                    roots.append({"root": url, "ok": True, "status": status, "finalUrl": final})
                print(f"  OK accepted={accepted} links={len(links)} docs={len(doc_refs)} title={title[:100]!r}", flush=True)
            except Exception as exc:
                err = f"{type(exc).__name__}: {exc}"
                failures.append({"url": url, "error": err})
                if url in seed_urls:
                    roots.append({"root": url, "ok": False, "error": err})
                print(f"  FAIL {err}", flush=True)
            finally:
                page.close()
        context.close()
        browser.close()

    current_by_url = {p["url"]: p for p in pages}
    previous_by_url = {p.get("url"): p for p in previous_corpus.get("pages", []) if p.get("url")}
    merged_pages = {**previous_by_url, **current_by_url}
    merged_docs = {d.get("url"): d for d in previous_corpus.get("documents", []) if d.get("url")}
    merged_docs.update(documents)

    frontier = []
    for rank, _order, url, depth, hint, parent in sorted(queue):
        if url in merged_pages:
            continue
        frontier.append({
            "url": url,
            "depth": depth,
            "hint": hint,
            "parent": parent,
            "score": -rank,
        })
        if len(frontier) >= MAX_FRONTIER:
            break

    run = {
        "observedAt": observed_at,
        "sourceAvailable": source_available,
        "roots": roots,
        "pagesVisited": len(seen),
        "acceptedPages": len(pages),
        "documentsObserved": len(documents),
        "queuedRemaining": len(queue),
        "resumedFrontier": resumed,
        "frontierPersisted": len(frontier),
        "failures": failures[:60],
        "runtimeSeconds": round(time.monotonic() - started, 2),
        "runtimeBudgetSeconds": RUNTIME_SECONDS,
        "deadlineReached": time.monotonic() >= deadline,
        "maxPages": MAX_PAGES,
        "maxDepth": MAX_DEPTH,
        "collectorVersion": "3.0",
        "frontierVersion": 1,
        "transport": "playwright-edge-direct-romania-v3",
    }

    corpus = {
        "schemaVersion": 3,
        "source": "MIPE",
        "officialHosts": sorted(OFFICIAL_HOSTS),
        "generatedAt": observed_at,
        "status": "PASS" if source_available else "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED",
        "lastRun": run,
        "frontierVersion": 1,
        "frontier": frontier,
        "pages": sorted(merged_pages.values(), key=lambda x: str(x.get("observedAt", "")), reverse=True)[:500],
        "documents": sorted(merged_docs.values(), key=lambda x: str(x.get("observedAt", "")), reverse=True)[:800],
        "runs": (previous_corpus.get("runs") or [])[-29:] + [run],
    }
    CORPUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CORPUS_PATH.write_text(json.dumps(corpus, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    prior_items = {i.get("url"): i for i in previous_state.get("items", []) if i.get("url")}
    for page in pages:
        prior_items[page["url"]] = {
            "id": page["id"], "title": page["title"], "url": page["url"],
            "date": "", "dateLabel": "Observat direct", "dateConfidence": "OBSERVED_ONLY",
            "summary": page["summary"], "textPreview": page["textPreview"],
            "pageClass": page["pageClass"], "tag": page["programme"], "kind": page["kind"],
            "tier": "T1", "source": "MIPE", "observedAt": observed_at,
            "retrievalTransport": page["retrievalTransport"], "verification": page["verification"],
            "documents": page["documents"], "contentHash": page["contentHash"],
        }
    items = list(prior_items.values())[:300]
    state_status = "OK" if source_available and pages else ("OK_NO_NEW_RELEVANT_ITEMS" if source_available else "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED")
    state = {
        "status": state_status,
        "lastRun": {
            "observedAt": observed_at, "roots": roots, "sourceAvailable": source_available,
            "candidateCount": len(seen), "parsedRelevantCount": len(pages),
            "documentCount": len(documents), "transport": run["transport"],
            "runtimeSeconds": run["runtimeSeconds"], "deadlineReached": run["deadlineReached"],
            "status": state_status, "directSuccessCount": sum(1 for x in roots if x.get("ok")),
            "collectorVersion": "3.0", "frontierVersion": 1,
            "frontierPersisted": len(frontier), "resumedFrontier": resumed,
        },
        "items": items,
        "runs": (previous_state.get("runs") or [])[-39:] + [run],
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    FEED_PATH.write_text(
        "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.mipeIngestion=" + json.dumps({
            "status": state_status, "asOf": observed_at, "source": "MIPE official web properties",
            "roots": roots, "itemCount": len(items), "transport": run["transport"],
            "sourceAvailable": source_available, "collectorVersion": "3.0",
            "frontierVersion": 1, "frontierPersisted": len(frontier),
            "corpusPages": len(corpus["pages"]), "corpusDocuments": len(corpus["documents"]),
        }, ensure_ascii=False, separators=(",", ":")) + ";\n"
        + "window.PARTENER_DATA.mipeNews=" + json.dumps(items, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "status": state_status, "pagesVisited": len(seen), "freshPages": len(pages),
        "corpusPages": len(corpus["pages"]), "documents": len(corpus["documents"]),
        "runtimeSeconds": run["runtimeSeconds"], "queuedRemaining": len(queue),
        "resumedFrontier": resumed, "frontierPersisted": len(frontier),
    }, ensure_ascii=False, indent=2))
    return 0 if source_available else 2


if __name__ == "__main__":
    raise SystemExit(main())
