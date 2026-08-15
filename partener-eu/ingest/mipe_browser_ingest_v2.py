#!/usr/bin/env python3
"""Direct Romanian-browser MIPE collector with semantic quality gates.

The collector uses a repository-owned Windows runner and a real Microsoft Edge
instance. It preserves canonical MIPE URLs, extracts page-specific titles and
article bodies, attaches official documents, excludes navigation/listing pages,
and exits within an explicit runtime budget so verified results can always be
persisted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import heapq
import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Any

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "partener-eu/ingest/state/mipe_state.json"
OUT = ROOT / "partener-eu/web/mipe-news.js"

ROOT_URL = "https://mfe.gov.ro/"
PROGRAM_ROOTS = [
    "https://mfe.gov.ro/ghiduri_peos/",
    "https://mfe.gov.ro/ghiduri_pids/",
    "https://mfe.gov.ro/pdds/despre-program-programare/",
    "https://mfe.gov.ro/pnrr/",
]
SEEDS = [ROOT_URL, *PROGRAM_ROOTS]
HOSTS = {"mfe.gov.ro", "www.mfe.gov.ro"}
SCOPES = ("/pdds/", "/ghiduri_peos/", "/ghiduri_pids/", "/pnrr/")

KW = [
    "fonduri", "finanț", "finant", "apel", "ghid", "program", "proiect",
    "investi", "beneficiar", "grant", "alocare", "buget", "pdds",
    "dezvoltare durabil", "prioritate", "consultare", "corrigendum", "termen",
    "eligibil", "mysmis", "fse", "feder", "tranziție justă", "tranzitie justa",
    "peo", "pids", "poids", "step", "pnrr", "formare", "educație", "educatie",
]
EXCLUDED = [
    "post vacant", "concurs recrutare", "declarație de avere", "declaratie de avere",
    "achiziție publică", "achizitie publica", "anunț de angajare", "anunt de angajare",
]
GENERIC_TITLE_PARTS = [
    "ministerul investițiilor și proiectelor europene bine ați venit",
    "ministerul investitiilor si proiectelor europene bine ati venit",
    "bine ați venit pe site-ul ministerului",
    "bine ati venit pe site-ul ministerului",
]
NAV_PREFIXES = [
    "search acasă minister despre minister",
    "search acasa minister despre minister",
    "acasă minister despre minister legislație",
    "acasa minister despre minister legislatie",
]
MONTHS = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sept", "oct", "nov", "dec"]
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".7z", ".rar")
ASSET_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".woff2")
CONTENT_SELECTORS = [
    ".entry-content",
    ".elementor-widget-theme-post-content",
    ".wp-block-post-content",
    "article .post-content",
    "article",
    "main article",
    "main",
]
TITLE_SELECTORS = [
    ".entry-title",
    ".page-title",
    ".post-title",
    "article h1",
    "main h1",
    "article h2",
    "main h2",
]

MAX_PAGES = max(5, int(os.environ.get("MIPE_MAX_PAGES", "36")))
RUNTIME_SECONDS = max(120, int(os.environ.get("MIPE_RUNTIME_SECONDS", "540")))
PAGE_TIMEOUT_MS = max(5000, int(os.environ.get("MIPE_PAGE_TIMEOUT_MS", "15000")))
PAGE_WAIT_MS = max(0, int(os.environ.get("MIPE_PAGE_WAIT_MS", "500")))
FORCE_IP = os.environ.get("MIPE_FORCE_IP", "").strip()
BROWSER_CHANNEL = os.environ.get("MIPE_BROWSER_CHANNEL", "").strip()
BROWSER_EXECUTABLE = os.environ.get("MIPE_BROWSER_EXECUTABLE", "").strip()
HEADLESS = os.environ.get("MIPE_HEADLESS", "1").strip().lower() not in {"0", "false", "no"}


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_text(value: Any) -> str:
    return clean(value).lower().translate(str.maketrans("ăâîșţț", "aaisțt"))


def canonicalize(url: str, base: str | None = None) -> str | None:
    try:
        if base:
            url = urllib.parse.urljoin(base, url)
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"} or host not in HOSTS:
            return None
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        query = [(k, v) for k, v in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True) if not k.lower().startswith("utm_")]
        return urllib.parse.urlunparse(("https", host, path, "", urllib.parse.urlencode(query), ""))
    except Exception:
        return None


def scoped_path(url: str) -> str | None:
    path = urllib.parse.urlparse(url).path
    for scope in SCOPES:
        if path.startswith(scope):
            return scope
    return None


def same_scope(parent: str, child: str) -> bool:
    parent_scope = scoped_path(parent)
    return bool(parent_scope and urllib.parse.urlparse(child).path.startswith(parent_scope))


def is_listing_url(url: str) -> bool:
    if url in SEEDS:
        return True
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query))
    if query.get("display") in {"cards", "table"}:
        return True
    if re.search(r"/page/\d+/?$", parsed.path):
        return True
    return False


def is_generic_title(title: str) -> bool:
    value = normalize_text(title)
    if not value or len(value) < 12:
        return True
    return any(normalize_text(part) in value for part in GENERIC_TITLE_PARTS)


def is_navigation_text(text: str) -> bool:
    value = normalize_text(text[:500])
    return any(normalize_text(prefix) in value for prefix in NAV_PREFIXES)


def relevance(title: str, body: str, url: str) -> int:
    haystack = f"{title} {body[:5000]} {url}".lower()
    score = sum(3 if token in title.lower() else 1 for token in KW if token in haystack)
    if any(token in title.lower() for token in EXCLUDED):
        score -= 12
    return score


def classify_kind(title: str, body: str) -> str:
    text = f"{title} {body[:2200]}".lower()
    if "prelung" in text and "termen" in text:
        return "DEADLINE_EXTENDED"
    if "corrigendum" in text or "corrigend" in text or "rectific" in title.lower():
        return "GUIDE_MODIFIED"
    if "consultare" in text and ("ghid" in text or "apel" in text):
        return "CONSULTATION_OPENED"
    if any(token in text for token in ("apelul este deschis", "apel deschis", "lansarea apelului", "s-a lansat apelul", "se lansează apelul", "se lanseaza apelul")):
        return "CALL_OPENED"
    if "ghid" in text and any(token in text for token in ("publicat", "aprobat", "final")):
        return "GUIDE_PUBLISHED"
    if "rezultat" in text or "lista proiectelor" in text:
        return "RESULTS_PUBLISHED"
    return "OFFICIAL_UPDATE"


def classify_tag(text: str) -> str:
    value = text.lower()
    if "/pdds/" in value or "pdds" in value or "dezvoltare durabil" in value:
        return "PDDS"
    if "/ghiduri_pids/" in value or "poids" in value or "pids" in value:
        return "PoIDS"
    if "/ghiduri_peos/" in value or re.search(r"\bpeo\b", value):
        return "PEO"
    if "/pnrr/" in value or "pnrr" in value:
        return "PNRR"
    if "tranziție justă" in value or "tranzitie justa" in value:
        return "PTJ"
    return "MIPE"


def parse_date(text: str) -> dt.date | None:
    sample = text[:12000]
    patterns = [
        (r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", "ymd"),
        (r"\b(\d{1,2})[./-](\d{1,2})[./-](20\d{2})\b", "dmy"),
    ]
    for pattern, order in patterns:
        match = re.search(pattern, sample)
        if not match:
            continue
        try:
            if order == "ymd":
                year, month, day = map(int, match.groups())
            else:
                day, month, year = map(int, match.groups())
            return dt.date(year, month, day)
        except ValueError:
            pass
    return None


def date_label(value: dt.date | None) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}" if value else "Data publicării neconfirmată"


def slug_title(url: str) -> str:
    slug = urllib.parse.urlparse(url).path.rstrip("/").split("/")[-1]
    slug = urllib.parse.unquote(slug).replace("-", " ").replace("_", " ")
    return clean(slug).capitalize()


def safe_locator_text(page: Any, selector: str) -> list[str]:
    try:
        return [clean(value) for value in page.locator(selector).all_text_contents() if clean(value)]
    except Exception:
        return []


def choose_title(page: Any, url: str, title_hint: str) -> tuple[str, str]:
    candidates: list[tuple[int, str, str]] = []

    hint = clean(title_hint)
    if hint and not is_generic_title(hint):
        candidates.append((100 + min(len(hint), 200), hint, "OFFICIAL_LINK_TEXT"))

    for selector, source in [
        ('meta[property="og:title"]', "OFFICIAL_PAGE_METADATA"),
        ('meta[name="twitter:title"]', "OFFICIAL_PAGE_METADATA"),
    ]:
        try:
            value = clean(page.locator(selector).first.get_attribute("content"))
            if value and not is_generic_title(value):
                candidates.append((90 + min(len(value), 200), value, source))
        except Exception:
            pass

    for selector in TITLE_SELECTORS:
        for value in safe_locator_text(page, selector)[:8]:
            if not is_generic_title(value):
                candidates.append((80 + min(len(value), 200), value, "OFFICIAL_PAGE_DOM"))

    try:
        document_title = clean(page.title())
        for part in re.split(r"\s+[|–—]\s+", document_title):
            part = clean(part)
            if part and not is_generic_title(part):
                candidates.append((60 + min(len(part), 200), part, "OFFICIAL_PAGE_TITLE"))
    except Exception:
        pass

    fallback = slug_title(url)
    if fallback and not is_generic_title(fallback):
        candidates.append((30 + min(len(fallback), 200), fallback, "EXTRACTED_FROM_CANONICAL_URL"))

    if not candidates:
        return "", "UNAVAILABLE"
    candidates.sort(key=lambda row: (row[0], len(row[1])), reverse=True)
    return candidates[0][1][:360], candidates[0][2]


def extract_article_text(page: Any, title: str) -> tuple[str, str]:
    for selector in CONTENT_SELECTORS:
        texts = safe_locator_text(page, selector)
        if not texts:
            continue
        candidate = max(texts, key=len)
        if len(candidate) < 100:
            continue
        if title and title.lower() in candidate.lower():
            position = candidate.lower().find(title.lower())
            if 0 <= position <= 300:
                candidate = clean(candidate[position + len(title):])
        if not is_navigation_text(candidate):
            return candidate, selector

    body = clean(page.locator("body").inner_text(timeout=6000))
    if title and title.lower() in body.lower():
        position = body.lower().find(title.lower())
        if 0 <= position <= 4000:
            body = clean(body[position + len(title):])
    return body, "body-fallback"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": [], "runs": []}


def previous_item_is_usable(item: dict[str, Any]) -> bool:
    url = item.get("url", "")
    if not canonicalize(url) or is_listing_url(url):
        return False
    if is_generic_title(item.get("title", "")):
        return False
    if is_navigation_text(item.get("summary", "")):
        return False
    return True


def write_state(previous: dict[str, Any], fresh: list[dict[str, Any]], run: dict[str, Any]) -> None:
    merged = {
        item.get("url"): item
        for item in previous.get("items", [])
        if item.get("url") and previous_item_is_usable(item)
    }
    for item in fresh:
        merged[item["url"]] = item
    items = sorted(
        merged.values(),
        key=lambda item: (item.get("date", ""), item.get("observedAt", "")),
        reverse=True,
    )[:80]

    if run.get("sourceAvailable") and fresh:
        status = "OK"
    elif run.get("sourceAvailable"):
        status = "OK_NO_NEW_RELEVANT_ITEMS"
    else:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"

    run["status"] = status
    run["publishedItemCount"] = len(items)
    state = {
        "status": status,
        "lastRun": run,
        "items": items,
        "runs": (previous.get("runs") or [])[-39:] + [run],
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    metadata = {
        "status": status,
        "asOf": run["observedAt"],
        "source": "MIPE official web properties",
        "roots": run.get("roots", []),
        "itemCount": len(items),
        "transport": run.get("transport"),
        "sourceAvailable": run.get("sourceAvailable"),
        "deadlineReached": run.get("deadlineReached"),
        "qualityRejectedCount": run.get("qualityRejectedCount"),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
        + "window.PARTENER_DATA.mipeIngestion="
        + json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
        + ";\nwindow.PARTENER_DATA.mipeNews="
        + json.dumps(items, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)


def main() -> int:
    previous = load_state()
    fresh: list[dict[str, Any]] = []
    seen: set[str] = set()
    queued: set[str] = set()
    queue: list[tuple[int, int, str, int, str]] = []
    sequence = 0

    def enqueue(url: str, depth: int, hint: str = "", priority: int | None = None) -> None:
        nonlocal sequence
        canonical = canonicalize(url)
        if not canonical or canonical in seen or canonical in queued:
            return
        sequence += 1
        rank = priority if priority is not None else -(relevance(hint, "", canonical) * 10 - depth)
        heapq.heappush(queue, (rank, sequence, canonical, depth, clean(hint)))
        queued.add(canonical)

    for seed in SEEDS:
        enqueue(seed, 0, priority=-10000 + SEEDS.index(seed))

    root_set = set(SEEDS)
    roots: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    source_available = False
    quality_rejected = 0
    started = time.monotonic()
    deadline = started + RUNTIME_SECONDS

    with sync_playwright() as playwright:
        args = [
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
        ]
        browser_name = BROWSER_CHANNEL or (Path(BROWSER_EXECUTABLE).name if BROWSER_EXECUTABLE else "chromium")
        mode = "headless" if HEADLESS else "headed"
        transport = f"playwright-{browser_name}-{mode}-romania"
        if FORCE_IP:
            args.append(f"--host-resolver-rules=MAP mfe.gov.ro {FORCE_IP},MAP www.mfe.gov.ro {FORCE_IP},EXCLUDE localhost")
            transport += f"-resolve:{FORCE_IP}"

        launch: dict[str, Any] = {"headless": HEADLESS, "args": args}
        if BROWSER_EXECUTABLE:
            launch["executable_path"] = BROWSER_EXECUTABLE
        elif BROWSER_CHANNEL:
            launch["channel"] = BROWSER_CHANNEL

        browser = playwright.chromium.launch(**launch)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
            locale="ro-RO",
            timezone_id="Europe/Bucharest",
            ignore_https_errors=False,
            viewport={"width": 1440, "height": 1000},
        )
        context.set_default_timeout(5000)
        context.set_default_navigation_timeout(PAGE_TIMEOUT_MS)
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined});")
        context.route(
            "**/*",
            lambda route: route.abort()
            if route.request.resource_type in {"image", "media", "font", "stylesheet"}
            else route.continue_(),
        )

        while queue and len(seen) < MAX_PAGES and time.monotonic() < deadline:
            _priority, _sequence, url, depth, title_hint = heapq.heappop(queue)
            queued.discard(url)
            if url in seen:
                continue
            if depth > 0 and not scoped_path(url):
                continue
            seen.add(url)
            page = context.new_page()
            print(f"[MIPE {len(seen)}/{MAX_PAGES}] {url}", flush=True)
            try:
                response = page.goto(url, wait_until="commit", timeout=PAGE_TIMEOUT_MS)
                try:
                    page.wait_for_load_state("domcontentloaded", timeout=min(6000, PAGE_TIMEOUT_MS))
                except PlaywrightTimeoutError:
                    pass
                if PAGE_WAIT_MS:
                    page.wait_for_timeout(PAGE_WAIT_MS)

                status = response.status if response else 0
                if status and status >= 400:
                    raise RuntimeError(f"HTTP {status}")
                final = canonicalize(page.url)
                if not final:
                    raise RuntimeError("redirected outside official MIPE host")
                source_available = True

                links = page.locator("a[href]").evaluate_all(
                    "els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||'').trim()}))"
                )
                title, title_source = choose_title(page, final, title_hint)
                article_text, content_selector = extract_article_text(page, title)
                documents: list[dict[str, str]] = []
                for link in links:
                    href = canonicalize(link.get("href"), final)
                    if not href:
                        continue
                    path = urllib.parse.urlparse(href).path.lower()
                    if path.endswith(DOCUMENT_EXTENSIONS):
                        documents.append({"name": clean(link.get("text")) or Path(path).name, "url": href})

                listing = is_listing_url(final)
                accepted = (
                    not listing
                    and not is_generic_title(title)
                    and not is_navigation_text(article_text)
                    and len(article_text) >= 100
                    and relevance(title, article_text, final) >= 3
                )
                if accepted:
                    published = parse_date(article_text)
                    description = ""
                    try:
                        description = clean(page.locator('meta[name="description"]').first.get_attribute("content"))
                    except Exception:
                        pass
                    if is_generic_title(description) or is_navigation_text(description):
                        description = ""
                    summary = clean(description or article_text[:1000])[:1000]
                    identifier = hashlib.sha256(f"{final}\n{title}".encode()).hexdigest()[:20]
                    fresh.append(
                        {
                            "id": identifier,
                            "title": title,
                            "titleSource": title_source,
                            "url": final,
                            "date": published.isoformat() if published else "",
                            "dateLabel": date_label(published),
                            "dateConfidence": "OFFICIAL_PAGE" if published else "OBSERVED_ONLY",
                            "summary": summary,
                            "tag": classify_tag(f"{final} {title} {summary}"),
                            "kind": classify_kind(title, article_text),
                            "tier": "T1",
                            "source": "MIPE",
                            "observedAt": now().isoformat(),
                            "discovery": transport,
                            "retrievalTransport": transport,
                            "verification": "CANONICAL_OFFICIAL_FETCH",
                            "documents": documents[:30],
                            "contentHash": hashlib.sha256(article_text.encode()).hexdigest(),
                            "contentSelector": content_selector,
                        }
                    )
                elif not listing:
                    quality_rejected += 1
                    print(
                        f"  REJECT title={title[:90]!r} titleSource={title_source} "
                        f"body={len(article_text)} nav={is_navigation_text(article_text)}",
                        flush=True,
                    )

                if depth < 2:
                    for link in links:
                        candidate = canonicalize(link.get("href"), final)
                        if not candidate:
                            continue
                        path = urllib.parse.urlparse(candidate).path.lower()
                        if path.endswith(DOCUMENT_EXTENSIONS) or path.endswith(ASSET_EXTENSIONS):
                            continue
                        hint = clean(link.get("text"))
                        if same_scope(final, candidate):
                            enqueue(candidate, depth + 1, hint)
                        elif final == ROOT_URL and relevance(hint, "", candidate) > 0:
                            enqueue(candidate, 1, hint)

                if url in root_set:
                    roots.append({"root": url, "ok": True, "transport": transport, "status": status, "finalUrl": final})
                print(
                    f"  OK status={status} accepted={accepted} title={title[:90]!r} "
                    f"titleSource={title_source} links={len(links)} docs={len(documents)}",
                    flush=True,
                )
            except Exception as exc:  # noqa: BLE001 - persisted as source evidence
                error = f"{type(exc).__name__}: {exc}"
                failures.append({"url": url, "error": error})
                if url in root_set:
                    roots.append({"root": url, "ok": False, "transport": transport, "error": error})
                print(f"  FAIL {error}", flush=True)
            finally:
                page.close()

        context.close()
        browser.close()

    unique = {item["url"]: item for item in fresh}
    run = {
        "observedAt": now().isoformat(),
        "roots": roots,
        "sourceAvailable": source_available,
        "candidateCount": len(seen),
        "queuedRemaining": len(queue),
        "parsedRelevantCount": len(unique),
        "qualityRejectedCount": quality_rejected,
        "browserFailures": failures[:40],
        "transport": transport,
        "forcedIp": FORCE_IP or None,
        "browserChannel": BROWSER_CHANNEL or None,
        "browserExecutable": BROWSER_EXECUTABLE or None,
        "headless": HEADLESS,
        "runtimeSeconds": round(time.monotonic() - started, 2),
        "runtimeBudgetSeconds": RUNTIME_SECONDS,
        "deadlineReached": time.monotonic() >= deadline,
        "maxPages": MAX_PAGES,
        "semanticCollectorVersion": "2.0",
    }
    write_state(previous, list(unique.values()), run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
