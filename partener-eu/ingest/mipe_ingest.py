#!/usr/bin/env python3
import datetime as dt
import hashlib
import html
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT / "partener-eu" / "ingest" / "state" / "mipe_state.json"
WEB_PATH = ROOT / "partener-eu" / "web" / "mipe-news.js"

SOURCE_ROOTS = [
    "https://mfe.gov.ro/",
    "https://www.fonduri-ue.gov.ro/",
    "https://www.fonduri-ue.ro/",
]
OFFICIAL_HOSTS = {
    "mfe.gov.ro", "www.mfe.gov.ro",
    "fonduri-ue.gov.ro", "www.fonduri-ue.gov.ro",
    "fonduri-ue.ro", "www.fonduri-ue.ro",
}
USER_AGENT = "PARTENER.EU-CIVORA-MIPE-Ingest/1.0 (+https://partener.eu)"
MAX_ITEMS = 40
MAX_PAGE_FETCHES = 60

FUNDING_KEYWORDS = [
    "fonduri", "finanț", "finant", "apel", "ghid", "program", "proiect",
    "investi", "beneficiar", "grant", "alocare", "buget", "poids", "pids",
    "peo", "pnrr", "coeziune", "consultare", "corrigendum", "termen",
    "eligibil", "my smis", "mysmis", "fse+", "feder", "ftj", "tranziție justă",
]
EXCLUDE_HINTS = [
    "post vacant", "concurs recrutare", "declarație de avere", "declaratie de avere",
    "achiziție publică", "achizitie publica", "anunț de angajare", "anunt de angajare",
]

MONTHS_RO = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sept", "oct", "nov", "dec"]


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def clean_text(value):
    if value is None:
        return ""
    value = html.unescape(str(value))
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def official_url(url):
    try:
        return urllib.parse.urlparse(url).hostname in OFFICIAL_HOSTS
    except Exception:
        return False


def normalize_url(url, base=None):
    if base:
        url = urllib.parse.urljoin(base, url)
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or p.hostname not in OFFICIAL_HOSTS:
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    return urllib.parse.urlunparse(("https", p.netloc.lower(), path, "", p.query, ""))


def fetch(url, timeout=25, attempts=3):
    last = None
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "ro,en;q=0.7",
    })
    ctx = ssl.create_default_context()
    for i in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                data = r.read(3_000_000)
                return {
                    "ok": True,
                    "status": getattr(r, "status", 200),
                    "url": r.geturl(),
                    "content_type": r.headers.get("Content-Type", ""),
                    "data": data,
                }
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(1.5 * (i + 1))
    return {"ok": False, "error": last, "url": url}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title_parts = []
        self.h1_parts = []
        self.p_parts = []
        self.links = []
        self.meta = {}
        self.time_values = []
        self._stack = []
        self._anchor_href = None
        self._anchor_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self._stack.append(tag)
        if tag == "a":
            self._anchor_href = attrs.get("href")
            self._anchor_text = []
        elif tag == "meta":
            key = (attrs.get("property") or attrs.get("name") or "").lower()
            val = attrs.get("content")
            if key and val:
                self.meta[key] = val
        elif tag == "time":
            if attrs.get("datetime"):
                self.time_values.append(attrs.get("datetime"))

    def handle_endtag(self, tag):
        if tag == "a" and self._anchor_href:
            self.links.append((self._anchor_href, clean_text(" ".join(self._anchor_text))))
            self._anchor_href = None
            self._anchor_text = []
        if self._stack:
            for i in range(len(self._stack) - 1, -1, -1):
                if self._stack[i] == tag:
                    self._stack = self._stack[:i]
                    break

    def handle_data(self, data):
        if not data or not data.strip():
            return
        current = self._stack[-1] if self._stack else ""
        if current == "title":
            self.title_parts.append(data)
        if current == "h1":
            self.h1_parts.append(data)
        if current == "p":
            self.p_parts.append(data)
        if self._anchor_href is not None:
            self._anchor_text.append(data)


def parse_html(raw):
    text = raw.decode("utf-8", errors="replace")
    p = PageParser()
    p.feed(text)
    title = clean_text(p.meta.get("og:title") or p.meta.get("twitter:title") or " ".join(p.h1_parts) or " ".join(p.title_parts))
    description = clean_text(p.meta.get("description") or p.meta.get("og:description") or p.meta.get("twitter:description"))
    body = clean_text(" ".join(p.p_parts))
    return p, title, description, body, text


def parse_date(value, body=""):
    candidates = [value] if value else []
    if body:
        candidates += re.findall(r"\b(20\d{2}[-/.]\d{1,2}[-/.]\d{1,2})\b", body[:5000])
        candidates += re.findall(r"\b(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\b", body[:5000])
    for v in candidates:
        if not v:
            continue
        s = str(v).strip()
        try:
            z = s.replace("Z", "+00:00")
            return dt.datetime.fromisoformat(z).date()
        except Exception:
            pass
        for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return dt.datetime.strptime(s[:10], fmt).date()
            except Exception:
                pass
    return None


def ro_date(d):
    if not d:
        d = now_utc().date()
    return f"{d.day} {MONTHS_RO[d.month-1]} {d.year}"


def score_relevance(title, description, body, url):
    hay = " ".join([title, description, body[:2500], url]).lower()
    score = sum(2 if k in title.lower() else 1 for k in FUNDING_KEYWORDS if k in hay)
    if any(x in title.lower() for x in EXCLUDE_HINTS):
        score -= 8
    return score


def classify_tag(text):
    t = text.lower()
    if "poids" in t or "pids" in t or "incluziune și demnitate socială" in t or "incluziune si demnitate sociala" in t:
        return "PoIDS"
    if re.search(r"\bpeo\b", t) or "educație și ocupare" in t or "educatie si ocupare" in t:
        return "PEO"
    if "pnrr" in t or "redresare și reziliență" in t or "redresare si rezilienta" in t:
        return "PNRR"
    if "tranziție justă" in t or "tranzitie justa" in t or re.search(r"\bptj\b", t):
        return "PTJ"
    if "program regional" in t or "regiunea" in t or "adr " in t:
        return "REGIONAL"
    return "MIPE"


def classify_kind(title):
    t = title.lower()
    if ("prelung" in t and "termen" in t) or "termenul de depunere" in t and "prelung" in t:
        return "DEADLINE_EXTENDED"
    if "corrigendum" in t or "corrigend" in t:
        return "GUIDE_MODIFIED"
    if "consultare" in t and ("ghid" in t or "apel" in t):
        return "CONSULTATION_OPENED"
    if ("ghid" in t and ("publicat" in t or "aprobat" in t or "final" in t)):
        return "GUIDE_PUBLISHED"
    if ("lans" in t and "apel" in t) or "apel de proiecte" in t or "apelul este deschis" in t:
        return "CALL_OPENED"
    return "OFFICIAL_UPDATE"


def candidate_from_wp_json(root):
    out = []
    endpoint = urllib.parse.urljoin(root, "/wp-json/wp/v2/posts?per_page=40&_fields=link,date,title,excerpt")
    r = fetch(endpoint, timeout=18, attempts=2)
    if not r["ok"]:
        return out
    try:
        arr = json.loads(r["data"].decode("utf-8", errors="replace"))
        if isinstance(arr, list):
            for row in arr:
                u = normalize_url(row.get("link", ""))
                if not u:
                    continue
                out.append({
                    "url": u,
                    "title_hint": clean_text((row.get("title") or {}).get("rendered")),
                    "excerpt_hint": clean_text((row.get("excerpt") or {}).get("rendered")),
                    "date_hint": row.get("date"),
                    "discovery": "wp-json",
                })
    except Exception:
        pass
    return out


def candidate_from_feed(root):
    out = []
    for suffix in ("/feed/", "/rss/", "/feed"):
        r = fetch(urllib.parse.urljoin(root, suffix), timeout=18, attempts=1)
        if not r["ok"]:
            continue
        try:
            tree = ET.fromstring(r["data"])
            for item in tree.findall(".//item"):
                link = clean_text(item.findtext("link"))
                u = normalize_url(link)
                if u:
                    out.append({"url": u, "title_hint": clean_text(item.findtext("title")), "date_hint": clean_text(item.findtext("pubDate")), "discovery": "rss"})
            ns = {"a": "http://www.w3.org/2005/Atom"}
            for entry in tree.findall(".//a:entry", ns):
                link_el = entry.find("a:link", ns)
                u = normalize_url(link_el.attrib.get("href", "") if link_el is not None else "")
                if u:
                    out.append({"url": u, "title_hint": clean_text(entry.findtext("a:title", default="", namespaces=ns)), "date_hint": clean_text(entry.findtext("a:updated", default="", namespaces=ns)), "discovery": "atom"})
        except Exception:
            continue
    return out


def candidate_from_sitemap(root):
    out = []
    seeds = [urllib.parse.urljoin(root, "/wp-sitemap.xml"), urllib.parse.urljoin(root, "/sitemap.xml")]
    child_maps = []
    for su in seeds:
        r = fetch(su, timeout=18, attempts=1)
        if not r["ok"]:
            continue
        try:
            tree = ET.fromstring(r["data"])
            locs = [clean_text(e.text) for e in tree.iter() if e.tag.endswith("loc") and e.text]
            for loc in locs[:200]:
                if loc.endswith(".xml"):
                    child_maps.append(loc)
                else:
                    u = normalize_url(loc)
                    if u and score_relevance("", "", "", u) > 0:
                        out.append({"url": u, "discovery": "sitemap"})
        except Exception:
            pass
    for sm in child_maps[:8]:
        r = fetch(sm, timeout=18, attempts=1)
        if not r["ok"]:
            continue
        try:
            tree = ET.fromstring(r["data"])
            for e in tree.iter():
                if e.tag.endswith("loc") and e.text:
                    u = normalize_url(clean_text(e.text))
                    if u and score_relevance("", "", "", u) > 0:
                        out.append({"url": u, "discovery": "sitemap-child"})
        except Exception:
            pass
    return out


def candidate_from_home(root):
    r = fetch(root, timeout=25, attempts=3)
    if not r["ok"]:
        return [], r.get("error")
    try:
        p, title, description, body, raw = parse_html(r["data"])
    except Exception as e:
        return [], f"parse:{e}"
    out = []
    base = r.get("url") or root
    for href, anchor in p.links:
        u = normalize_url(href, base)
        if not u:
            continue
        if re.search(r"\.(?:jpg|jpeg|png|gif|svg|pdf|docx?|xlsx?|zip)(?:\?|$)", u, re.I):
            continue
        if score_relevance(anchor, "", "", u) > 0:
            out.append({"url": u, "title_hint": anchor, "discovery": "homepage"})
    return out, None


def load_state():
    if not STATE_PATH.exists():
        return {"items": [], "runs": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"items": [], "runs": []}


def item_fingerprint(url, title):
    return hashlib.sha256((url + "\n" + title).encode("utf-8")).hexdigest()[:20]


def make_item(candidate):
    url = candidate["url"]
    r = fetch(url, timeout=22, attempts=2)
    if not r["ok"]:
        return None
    ctype = r.get("content_type", "").lower()
    if "html" not in ctype and not r["data"].lstrip().startswith(b"<"):
        return None
    try:
        p, title, description, body, raw = parse_html(r["data"])
    except Exception:
        return None
    title = clean_text(title or candidate.get("title_hint"))
    description = clean_text(description or candidate.get("excerpt_hint"))
    if not title or len(title) < 8:
        return None
    score = score_relevance(title, description, body, url)
    if score < 2:
        return None
    published = None
    for k in ("article:published_time", "date", "datepublished", "dc.date", "og:published_time"):
        if p.meta.get(k):
            published = parse_date(p.meta.get(k), body)
            if published:
                break
    if not published and p.time_values:
        published = parse_date(p.time_values[0], body)
    if not published:
        published = parse_date(candidate.get("date_hint"), body)
    if not published:
        published = parse_date(None, body)
    summary = description
    if not summary or len(summary) < 40:
        summary = body[:900]
    summary = clean_text(summary)[:900]
    combined = " ".join([title, description, body[:3000]])
    tag = classify_tag(combined)
    kind = classify_kind(title)
    d = published or now_utc().date()
    return {
        "id": item_fingerprint(url, title),
        "title": title[:360],
        "url": normalize_url(r.get("url") or url) or url,
        "date": d.isoformat(),
        "dateLabel": ro_date(d),
        "summary": summary,
        "tag": tag,
        "kind": kind,
        "tier": "T1",
        "source": "MIPE",
        "observedAt": now_utc().isoformat(),
        "relevanceScore": score,
        "discovery": candidate.get("discovery", "crawl"),
    }


def main():
    state = load_state()
    previous = {x.get("url"): x for x in state.get("items", []) if x.get("url")}
    candidates = []
    health = []

    for root in SOURCE_ROOTS:
        root_candidates, root_error = candidate_from_home(root)
        ok = root_error is None
        health.append({"root": root, "ok": ok, "error": root_error})
        if not ok:
            continue
        candidates.extend(root_candidates)
        candidates.extend(candidate_from_wp_json(root))
        candidates.extend(candidate_from_feed(root))
        candidates.extend(candidate_from_sitemap(root))

    dedup = {}
    for c in candidates:
        u = c.get("url")
        if u and official_url(u):
            old = dedup.get(u)
            if not old or len(c.get("title_hint", "")) > len(old.get("title_hint", "")):
                dedup[u] = c

    # Prefer candidates with funding terms in title/URL and newest discovery sources.
    priority = {"wp-json": 0, "rss": 1, "atom": 1, "homepage": 2, "sitemap": 3, "sitemap-child": 4}
    queue = sorted(dedup.values(), key=lambda c: (priority.get(c.get("discovery"), 9), -score_relevance(c.get("title_hint", ""), c.get("excerpt_hint", ""), "", c.get("url", ""))))

    current = []
    for c in queue[:MAX_PAGE_FETCHES]:
        item = make_item(c)
        if item:
            current.append(item)

    merged = dict(previous)
    for item in current:
        merged[item["url"]] = item

    def sort_key(x):
        return (x.get("date", "0000-00-00"), x.get("observedAt", ""))

    items = sorted(merged.values(), key=sort_key, reverse=True)[:MAX_ITEMS]
    sources_up = sum(1 for h in health if h["ok"])
    if sources_up == 0:
        status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"
    elif current:
        status = "OK"
    else:
        status = "OK_NO_NEW_RELEVANT_ITEMS"

    run = {
        "observedAt": now_utc().isoformat(),
        "status": status,
        "roots": health,
        "candidateCount": len(dedup),
        "parsedRelevantCount": len(current),
        "publishedItemCount": len(items),
    }
    runs = (state.get("runs") or [])[-29:] + [run]
    out_state = {"status": status, "lastRun": run, "items": items, "runs": runs}
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(out_state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "status": status,
        "asOf": run["observedAt"],
        "source": "MIPE official web properties",
        "roots": health,
        "itemCount": len(items),
    }
    js = "window.PARTENER_DATA=window.PARTENER_DATA||{};\n"
    js += "window.PARTENER_DATA.mipeIngestion=" + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n"
    js += "window.PARTENER_DATA.mipeNews=" + json.dumps(items, ensure_ascii=False, separators=(",", ":")) + ";\n"
    WEB_PATH.parent.mkdir(parents=True, exist_ok=True)
    WEB_PATH.write_text(js, encoding="utf-8")

    print(json.dumps(run, ensure_ascii=False, indent=2))
    # Source outage is recorded and preserved, but does not destroy the last-known-good feed.
    return 0


if __name__ == "__main__":
    sys.exit(main())
