#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import hashlib
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
    "peo", "pids", "poids", "step", "pnrr",
]
EXCLUDED = [
    "post vacant", "concurs recrutare", "declarație de avere", "declaratie de avere",
    "achiziție publică", "achizitie publica", "anunț de angajare", "anunt de angajare",
]
MONTHS = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sept", "oct", "nov", "dec"]
DOCUMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".zip", ".7z", ".rar")
ASSET_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".css", ".js", ".woff", ".woff2")

MAX_PAGES = max(5, int(os.environ.get("MIPE_MAX_PAGES", "28")))
RUNTIME_SECONDS = max(120, int(os.environ.get("MIPE_RUNTIME_SECONDS", "480")))
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


def relevance(title: str, body: str, url: str) -> int:
    haystack = f"{title} {body[:4000]} {url}".lower()
    score = sum(3 if token in title.lower() else 1 for token in KW if token in haystack)
    if any(token in title.lower() for token in EXCLUDED):
        score -= 12
    return score


def classify_kind(title: str, body: str) -> str:
    text = f"{title} {body[:1800]}".lower()
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
    sample = text[:9000]
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


def date_label(value: dt.date) -> str:
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def load_state() -> dict[str, Any]:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"items": [], "runs": []}


def write_state(previous: dict[str, Any], fresh: list[dict[str, Any]], run: dict[str, Any]) -> None:
    merged = {
        item.get("url"): item
        for item in previous.get("items", [])
        if item.get("url") and canonicalize(item.get("url"))
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
    queue: list[tuple[str, int]] = [(url, 0) for url in SEEDS]
    root_set = set(SEEDS)
    roots: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    source_available = False
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
            raw_url, depth = queue.pop(0)
            url = canonicalize(raw_url)
            if not url or url in seen:
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

                body = clean(page.locator("body").inner_text(timeout=6000))
                if len(body) < 80:
                    raise RuntimeError("page body too short")
                source_available = True

                title = clean(page.locator("h1").first.text_content(timeout=2500) if page.locator("h1").count() else page.title())
                description = ""
                try:
                    description = clean(page.locator('meta[name="description"]').get_attribute("content"))
                except Exception:
                    pass

                links = page.locator("a[href]").evaluate_all(
                    "els => els.map(a => ({href:a.href,text:(a.innerText||a.textContent||'').trim()}))"
                )
                documents: list[dict[str, str]] = []
                for link in links:
                    href = canonicalize(link.get("href"), final)
                    if not href:
                        continue
                    path = urllib.parse.urlparse(href).path.lower()
                    if path.endswith(DOCUMENT_EXTENSIONS):
                        documents.append({"name": clean(link.get("text")) or Path(path).name, "url": href})

                is_listing = final in root_set
                if relevance(title, body, final) >= 3 and not is_listing:
                    published = parse_date(body) or now().date()
                    summary = clean(description or body[:900])[:900]
                    identifier = hashlib.sha256(f"{final}\n{title}".encode()).hexdigest()[:20]
                    fresh.append(
                        {
                            "id": identifier,
                            "title": title[:360],
                            "url": final,
                            "date": published.isoformat(),
                            "dateLabel": date_label(published),
                            "dateConfidence": "OFFICIAL_PAGE_OR_OBSERVED",
                            "summary": summary,
                            "tag": classify_tag(f"{final} {title} {summary}"),
                            "kind": classify_kind(title, body),
                            "tier": "T1",
                            "source": "MIPE",
                            "observedAt": now().isoformat(),
                            "discovery": transport,
                            "retrievalTransport": transport,
                            "verification": "CANONICAL_OFFICIAL_FETCH",
                            "documents": documents[:30],
                            "contentHash": hashlib.sha256(body.encode()).hexdigest(),
                        }
                    )

                if depth < 2:
                    for link in links:
                        candidate = canonicalize(link.get("href"), final)
                        if not candidate or candidate in seen:
                            continue
                        path = urllib.parse.urlparse(candidate).path.lower()
                        if path.endswith(DOCUMENT_EXTENSIONS) or path.endswith(ASSET_EXTENSIONS):
                            continue
                        if same_scope(final, candidate):
                            queue.append((candidate, depth + 1))
                        elif final == ROOT_URL and relevance(clean(link.get("text")), "", candidate) > 0:
                            queue.append((candidate, 1))

                if url in root_set:
                    roots.append({"root": url, "ok": True, "transport": transport, "status": status, "finalUrl": final})
                print(f"  OK status={status} title={title[:90]!r} links={len(links)} docs={len(documents)}", flush=True)
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
    }
    write_state(previous, list(unique.values()), run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
