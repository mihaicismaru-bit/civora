#!/usr/bin/env python3
"""Generic fail-closed signal radar for LOCAL NEWS OS instances.

The radar turns recent T2/T3 press links into primary-verification tasks. It has
zero publication authority: a signal is never a fact, story or source of a
material claim. Instance-specific source families and verification routes live
in config; the engine remains geography/brand agnostic.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import html.parser
import json
import re
import ssl
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
GENERIC_LABELS = {
    "acasa", "acasă", "contact", "despre noi", "politica", "politică", "sport",
    "actualitate", "administratie", "administrație", "evenimente", "stiri", "știri",
    "mai mult", "citește", "citeste", "detalii", "următoarea", "urmatoarea",
}
SKIP_PATH_PARTS = (
    "/category/", "/categorie/", "/tag/", "/author/", "/page/", "/feed", "/rss",
    "/wp-json", "/contact", "/despre", "/privacy", "/confidential", "/termeni",
)
DATE_PATTERNS = (
    r'"datePublished"\s*:\s*"([^"]+)"',
    r'<meta\b(?=[^>]*(?:property|name)=["\']article:published_time["\'])(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>',
    r'<time\b[^>]*datetime=["\']([^"\']+)["\']',
)


class AnchorParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text)))
            self._href = None
            self._text = []


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def repo_file(raw: str) -> Path:
    if not raw or Path(raw).is_absolute():
        raise ValueError(f"invalid repository-relative path: {raw!r}")
    path = (ROOT / raw).resolve()
    path.relative_to(ROOT.resolve())
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def clean(value: str) -> str:
    value = html.unescape(re.sub(r"<[^>]+>", " ", value or ""))
    return re.sub(r"\s+", " ", value).strip(" \t\r\n-|•")


def norm_text(value: str) -> str:
    value = clean(value).casefold()
    value = value.translate(str.maketrans("ăâîșț", "aaist"))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value)).strip()


def same_host(a: str, b: str) -> bool:
    ha = (urllib.parse.urlsplit(a).hostname or "").lower().removeprefix("www.")
    hb = (urllib.parse.urlsplit(b).hostname or "").lower().removeprefix("www.")
    return ha == hb or ha.endswith("." + hb) or hb.endswith("." + ha)


def parse_time(value: str, tz: ZoneInfo) -> datetime | None:
    raw = html.unescape(str(value or "")).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)
    except ValueError:
        return None


def strict_published_at(text: str, tz: ZoneInfo) -> datetime | None:
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text, flags=re.I | re.S)
        if match:
            parsed = parse_time(match.group(1), tz)
            if parsed:
                return parsed
    return None


def fetch(url: str, max_bytes: int = 2_000_000, timeout: int = 14) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 LOCAL-NEWS-OS-Signal-Radar/1.0",
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.6",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.3",
        "Connection": "close",
    })
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        raw = response.read(max_bytes)
        ctype = (response.headers.get("content-type") or "").lower()
        if "html" not in ctype and not raw.lstrip().startswith(b"<"):
            raise RuntimeError(f"not_html:{ctype}")
        charset = "utf-8"
        match = re.search(r"charset=([\w-]+)", ctype)
        if match:
            charset = match.group(1)
        return raw.decode(charset, errors="replace"), str(response.geturl())


def article_like(root_url: str, href: str, label: str) -> tuple[str, str] | None:
    title = clean(label)
    generic = {norm_text(x) for x in GENERIC_LABELS}
    if len(title) < 20 or len(title) > 240 or norm_text(title) in generic:
        return None
    absolute = urllib.parse.urljoin(root_url, html.unescape(href).strip()).split("#", 1)[0]
    parsed = urllib.parse.urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not same_host(absolute, root_url):
        return None
    path = parsed.path.lower()
    if absolute.rstrip("/") == root_url.rstrip("/") or any(part in path for part in SKIP_PATH_PARTS):
        return None
    if re.search(r"\.(?:jpg|jpeg|png|gif|webp|pdf|zip|docx?|xlsx?)$", path):
        return None
    leaf = path.rstrip("/").split("/")[-1]
    article_shape = bool(
        re.search(r"/20\d{2}/(?:0?[1-9]|1[0-2])/(?:0?[1-9]|[12]\d|3[01])(?:/|$)", path)
        or len(leaf) >= 18
        or leaf.count("-") >= 2
        or leaf.endswith(".html")
        or re.search(r"(?:^|&)p=\d+(?:&|$)", parsed.query)
    )
    return (absolute, title) if article_shape else None


def load_config(instance_id: str) -> tuple[dict[str, Any], ZoneInfo]:
    instance = load(ROOT / "local-news-os" / "instances" / instance_id / "instance.json")
    if instance.get("instance_id") != instance_id:
        raise ValueError("instance id mismatch")
    source_pack = repo_file(str(instance.get("packs", {}).get("source_pack", "")))
    pack = load(source_pack)
    config_path = repo_file(str(pack.get("signal_radar_config") or ""))
    config = load(config_path)
    if config.get("contract") != "LOCAL_NEWS_OS_SIGNAL_RADAR_CONFIG_V1":
        raise ValueError("signal radar contract mismatch")
    if config.get("instance_id") != instance_id or config.get("publication_authority") != "NONE":
        raise ValueError("signal radar instance/authority mismatch")
    return config, ZoneInfo(str(instance["timezone"]))


def seed_rows(config: dict[str, Any]) -> list[dict[str, Any]]:
    tiers = {str(x) for x in config.get("signal_tiers") or []}
    families = {str(x) for x in config.get("signal_families") or []}
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_path in config.get("seed_registries") or []:
        doc = load(repo_file(str(raw_path)))
        for raw in doc.get("seed_sources") or []:
            if not isinstance(raw, list) or len(raw) != 6:
                raise ValueError(f"malformed source-intelligence seed: {raw!r}")
            sid, publisher, url, tier, family, sensitive = raw
            if str(tier) not in tiers or str(family) not in families:
                continue
            if str(sid) in seen:
                raise ValueError(f"duplicate radar seed id: {sid}")
            seen.add(str(sid))
            rows.append({
                "id": str(sid), "publisher": str(publisher), "url": str(url), "tier": str(tier),
                "family": str(family), "sensitive": bool(sensitive),
            })
    return rows


def resolve_registry_targets(config: dict[str, Any]) -> None:
    news = load(repo_file(str(config.get("news_registry_path") or "")))
    manual = load(repo_file(str(config.get("manual_watch_registry_path") or "")))
    news_ids = {str(row.get("id")) for row in news.get("sources") or []}
    manual_ids = {str(row.get("id")) for row in manual.get("sources") or []}
    for rule in config.get("rules") or []:
        for target in rule.get("verification_targets") or []:
            ref_type, sid = str(target.get("ref_type")), str(target.get("id"))
            if ref_type == "news_source_id" and sid not in news_ids:
                raise ValueError(f"unknown news verification target: {sid}")
            if ref_type == "manual_watch_source_id" and sid not in manual_ids:
                raise ValueError(f"unknown manual verification target: {sid}")
            if ref_type not in {"news_source_id", "manual_watch_source_id"}:
                raise ValueError(f"unsupported verification target type: {ref_type}")


def classify(title: str, config: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    hay = norm_text(title)
    for rule in config.get("rules") or []:
        if any(norm_text(str(keyword)) in hay for keyword in rule.get("keywords") or []):
            return str(rule["id"]), [dict(row) for row in rule.get("verification_targets") or []]
    return "general_local_signal", []


def probe_seed(seed: dict[str, Any], config: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, Any]:
    row: dict[str, Any] = {
        "seed_id": seed["id"], "publisher": seed["publisher"], "tier": seed["tier"],
        "family": seed["family"], "status": "DEGRADED", "error": None, "signals": [],
    }
    try:
        listing, final = fetch(seed["url"])
        parser = AnchorParser()
        parser.feed(listing)
        candidates: list[tuple[str, str]] = []
        seen: set[str] = set()
        for href, label in parser.links:
            candidate = article_like(final, href, label)
            if candidate and candidate[0] not in seen:
                seen.add(candidate[0])
                candidates.append(candidate)
            if len(candidates) >= int(config.get("max_links_per_source") or 14):
                break
        ttl = timedelta(hours=int(config.get("signal_ttl_hours") or 36))
        max_fetch = int(config.get("max_article_fetches_per_source") or 8)
        signals: list[dict[str, Any]] = []
        undated_budget = 2
        for url, listing_title in candidates[:max_fetch]:
            published: datetime | None = None
            try:
                article, final_article = fetch(url, max_bytes=1_200_000, timeout=12)
                published = strict_published_at(article, tz)
                url = final_article
            except Exception:
                pass
            if published is not None:
                age = now - published
                if age < timedelta(hours=-6) or age > ttl:
                    continue
                date_state = "STRICT_SOURCE_METADATA"
            else:
                if undated_budget <= 0:
                    continue
                undated_budget -= 1
                date_state = "DATE_UNVERIFIED_SIGNAL_ONLY"
            route_id, targets = classify(listing_title, config)
            signals.append({
                "signal_id": hashlib.sha256((seed["id"] + "\0" + url).encode()).hexdigest()[:24],
                "signal_title": listing_title,
                "signal_url": url,
                "signal_publisher": seed["publisher"],
                "signal_tier": seed["tier"],
                "signal_family": seed["family"],
                "signal_sensitive": seed["sensitive"],
                "published_at": published.isoformat(timespec="seconds") if published else None,
                "date_provenance": date_state,
                "observed_at": now.isoformat(timespec="seconds"),
                "verification_route_id": route_id,
                "verification_targets": targets,
                "status": "NEEDS_PRIMARY_VERIFICATION",
                "required_authority": "T1_OR_T1B_PRIMARY",
                "publication_authority": "NONE",
                "public_projection": False,
                "auto_publication": False,
            })
        row.update({"status": "PASS", "final_url": final, "links_examined": len(candidates), "signals": signals})
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[:500]
    return row


def merge_queue(current_signals: list[dict[str, Any]], previous: dict[str, Any], config: dict[str, Any], tz: ZoneInfo, now: datetime) -> list[dict[str, Any]]:
    ttl = timedelta(hours=int(config.get("signal_ttl_hours") or 36))
    prior = {str(row.get("signal_id")): row for row in previous.get("tasks") or [] if row.get("signal_id")}
    merged: dict[str, dict[str, Any]] = {}
    for signal in current_signals:
        sid = str(signal["signal_id"])
        old = prior.get(sid) or {}
        task = dict(signal)
        task["first_seen_at"] = old.get("first_seen_at") or signal["observed_at"]
        task["last_seen_at"] = signal["observed_at"]
        merged[sid] = task
    for sid, old in prior.items():
        if sid in merged:
            continue
        last_seen = parse_time(str(old.get("last_seen_at") or ""), tz)
        if last_seen and now - last_seen <= ttl:
            merged[sid] = old
    return sorted(
        merged.values(),
        key=lambda row: (row.get("published_at") is not None, row.get("published_at") or row.get("last_seen_at") or "", row["signal_id"]),
        reverse=True,
    )


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    config, tz = load_config(instance_id)
    resolve_registry_targets(config)
    seeds = seed_rows(config)
    if not seeds:
        raise ValueError("signal radar has no configured seeds")
    now = datetime.now(tz)
    max_workers = max(1, min(int(config.get("max_workers") or 8), 12, len(seeds)))
    observations: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"signal-{instance_id}") as pool:
        futures = {pool.submit(probe_seed, seed, config, tz, now): seed for seed in seeds}
        for future in as_completed(futures):
            observations.append(future.result())
    observations.sort(key=lambda row: row["seed_id"])
    current_signals = [signal for row in observations for signal in row.get("signals") or []]
    state_path = ROOT / str(config["state_path"])
    queue_path = ROOT / str(config["queue_path"])
    previous_queue = load(queue_path) if queue_path.is_file() else {}
    tasks = merge_queue(current_signals, previous_queue, config, tz, now)
    today = now.date().isoformat()
    today_count = sum(1 for row in tasks if str(row.get("published_at") or "").startswith(today))
    sources_ok = sum(1 for row in observations if row.get("status") == "PASS")
    threshold_hour = int(config.get("same_day_health_after_local_hour") or 12)
    health = "PASS"
    if now.hour >= threshold_hour and sources_ok > 0 and today_count == 0:
        health = "YELLOW_NO_SAME_DAY_SIGNALS"
    state = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_SIGNAL_RADAR_STATE_V1",
        "instance_id": instance_id,
        "observed_at": now.isoformat(timespec="seconds"),
        "publication_authority": "NONE",
        "health": health,
        "source_count": len(observations),
        "sources_ok": sources_ok,
        "current_signal_count": len(current_signals),
        "today_signal_count": today_count,
        "observations": observations,
    }
    queue = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_SIGNAL_VERIFICATION_QUEUE_V1",
        "instance_id": instance_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "publication_authority": "NONE",
        "signal_is_fact": False,
        "signal_may_publish_directly": False,
        "required_next_gate": "PRIMARY_VERIFICATION_THEN_FACT_KERNEL_THEN_EDITORIAL_WRITER",
        "pending_count": len(tasks),
        "today_signal_count": today_count,
        "tasks": tasks,
    }
    if write:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        queue_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "PASS", "state": state, "queue": queue, "state_path": str(state_path), "queue_path": str(queue_path)}


def validate(instance_id: str) -> dict[str, Any]:
    config, _ = load_config(instance_id)
    resolve_registry_targets(config)
    seeds = seed_rows(config)
    if config.get("publication_authority") != "NONE":
        raise ValueError("signal radar must have zero publication authority")
    interval = int(config.get("poll_interval_minutes") or 0)
    if interval <= 0 or interval > 15:
        raise ValueError("signal radar polling interval must be between 1 and 15 minutes")
    return {"status": "PASS", "instance_id": instance_id, "seed_count": len(seeds), "rule_count": len(config.get("rules") or []), "publication_authority": "NONE"}


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    html_doc = '<meta property="article:published_time" content="2026-08-17T14:30:00+03:00">'
    assert strict_published_at(html_doc, tz) == datetime(2026, 8, 17, 14, 30, tzinfo=tz)
    assert article_like("https://news.example/", "/accident-grav-pe-dn7-la-oras/", "Accident grav pe DN7, două persoane rănite") is not None
    assert article_like("https://news.example/", "/category/sport/", "Sport") is None
    cfg = {"rules": [{"id": "safety", "keywords": ["accident", "rutier"], "verification_targets": [{"ref_type": "x", "id": "y"}]}]}
    route, targets = classify("Accident rutier pe DN7", cfg)
    assert route == "safety" and targets[0]["id"] == "y"
    signal = {"signal_id": "a", "observed_at": "2026-08-17T15:00:00+03:00", "publication_authority": "NONE", "public_projection": False, "auto_publication": False}
    queue = merge_queue([signal], {"tasks": []}, {"signal_ttl_hours": 36}, tz, datetime(2026, 8, 17, 15, 0, tzinfo=tz))
    assert queue[0]["publication_authority"] == "NONE" and queue[0]["public_projection"] is False
    print("LOCAL NEWS OS signal radar self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", required=False)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance:
        parser.error("--instance is required")
    if args.validate_only:
        print(json.dumps(validate(args.instance), ensure_ascii=False))
        return 0
    result = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": result["status"],
        "health": result["state"]["health"],
        "sources_ok": result["state"]["sources_ok"],
        "source_count": result["state"]["source_count"],
        "pending_verification": result["queue"]["pending_count"],
        "today_signals": result["queue"]["today_signal_count"],
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
