#!/usr/bin/env python3
"""Monitor VÂLCEA CLAR festival sources and queue material source changes.

A changed web page is only a signal. This monitor never rewrites a public story
from arbitrary HTML and never treats a changed hash as a verified fact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "festival_source_registry.json"
STATE = ROOT / "state" / "festival_source_state.json"
QUEUE = ROOT / "editorial" / "festival_update_candidates.json"
TZ = ZoneInfo("Europe/Bucharest")
UA = "Mozilla/5.0 VÂLCEA-CLAR-Festival-Monitor/1.0 (+https://valceaclar.ro/)"
MAX_BYTES = 2_500_000


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data)


def load(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return value if isinstance(value, dict) else default


def normalize_text(raw: bytes, content_type: str) -> str:
    text = raw.decode("utf-8", errors="replace")
    if "html" in content_type.lower() or "<html" in text[:2000].lower():
        parser = TextExtractor()
        parser.feed(text)
        text = "\n".join(parser.parts)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def fetch(source: dict) -> tuple[str, dict]:
    req = Request(str(source["url"]), headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.6"})
    with urlopen(req, timeout=22) as response:
        raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raw = raw[:MAX_BYTES]
        ctype = str(response.headers.get("Content-Type") or "")
        final_url = str(response.geturl())
        status = int(getattr(response, "status", 200) or 200)
    normalized = normalize_text(raw, ctype)
    if len(normalized) < 80:
        raise ValueError("source body too thin after normalization")
    return normalized, {"http_status": status, "final_url": final_url, "content_type": ctype, "bytes": len(raw)}


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def excerpt(text: str, terms: list[str], limit: int = 900) -> str:
    folded = text.casefold()
    indexes = [folded.find(t.casefold()) for t in terms if t and folded.find(t.casefold()) >= 0]
    start = max(0, (min(indexes) if indexes else 0) - 180)
    value = text[start:start + limit]
    return re.sub(r"\s+", " ", value).strip()


def keyword_hits(text: str, terms: list[str]) -> list[str]:
    folded = text.casefold()
    return sorted({term for term in terms if term.casefold() in folded})


def queue_key(source_id: str, sha: str) -> str:
    return hashlib.sha256(f"{source_id}:{sha}".encode()).hexdigest()[:20]


def run() -> tuple[int, dict]:
    registry = load(REGISTRY, {})
    sources = registry.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise SystemExit("Festival source registry is empty")
    policy = registry.get("policy") or {}
    money_terms = [str(x) for x in policy.get("public_money_terms") or []]
    lineup_terms = [str(x) for x in policy.get("lineup_terms") or []]

    state = load(STATE, {"schema_version": "1.0", "sources": {}})
    state_rows = state.setdefault("sources", {})
    queue_doc = load(QUEUE, {"schema_version": "1.0", "product": "VÂLCEA CLAR festival update candidates", "candidates": []})
    candidates = queue_doc.setdefault("candidates", [])
    known_keys = {str(row.get("key") or "") for row in candidates if isinstance(row, dict)}
    now = datetime.now(TZ).isoformat(timespec="seconds")
    new_candidates = 0
    status_changes = 0
    initialized = 0

    for source in sources:
        source_id = str(source.get("id") or "").strip()
        if not source_id or not source.get("url"):
            continue
        previous = state_rows.get(source_id) if isinstance(state_rows.get(source_id), dict) else {}
        previous_sha = str(previous.get("sha256") or "")
        previous_status = str(previous.get("status") or "")
        try:
            text, transport = fetch(source)
            sha = digest(text)
            if not previous_sha:
                initialized += 1
                state_rows[source_id] = {
                    "status": "ACTIVE",
                    "sha256": sha,
                    "url": source["url"],
                    "final_url": transport["final_url"],
                    "last_material_change_at": now,
                    "last_error": None,
                }
                continue
            if sha != previous_sha:
                terms = [str(source.get("festival") or "")] + money_terms + lineup_terms
                key = queue_key(source_id, sha)
                if key not in known_keys:
                    money_hits = keyword_hits(text, money_terms)
                    lineup_hits = keyword_hits(text, lineup_terms)
                    candidates.append({
                        "key": key,
                        "status": "needs_editorial_verification",
                        "detected_at": now,
                        "source_id": source_id,
                        "festival": source.get("festival"),
                        "story_id": source.get("story_id"),
                        "tier": source.get("tier"),
                        "url": source.get("url"),
                        "scope": source.get("scope") or [],
                        "previous_sha256": previous_sha,
                        "current_sha256": sha,
                        "public_money_signal": bool(money_hits),
                        "public_money_terms": money_hits,
                        "lineup_signal": bool(lineup_hits),
                        "lineup_terms": lineup_hits,
                        "excerpt": excerpt(text, terms),
                        "publication_authority": False
                    })
                    known_keys.add(key)
                    new_candidates += 1
                state_rows[source_id] = {
                    "status": "ACTIVE",
                    "sha256": sha,
                    "url": source["url"],
                    "final_url": transport["final_url"],
                    "last_material_change_at": now,
                    "last_error": None,
                }
            elif previous_status != "ACTIVE":
                status_changes += 1
                state_rows[source_id] = {
                    **previous,
                    "status": "ACTIVE",
                    "url": source["url"],
                    "final_url": transport["final_url"],
                    "last_error": None,
                }
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if previous_status != "ERROR" or str(previous.get("last_error") or "") != error:
                status_changes += 1
                state_rows[source_id] = {
                    **previous,
                    "status": "ERROR",
                    "url": source.get("url"),
                    "last_error": error,
                    "last_error_at": now,
                }

    if initialized or new_candidates or status_changes or not STATE.is_file():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        state["schema_version"] = "1.0"
        state["policy"] = {"last_known_good_preserved": True, "source_change_is_not_publishable_fact": True}
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if new_candidates or not QUEUE.is_file():
        queue_doc["candidate_count"] = len(candidates)
        queue_doc["policy"] = {
            "source_change_is_not_publishable_fact": True,
            "editorial_verification_required": True,
            "autopublish_from_hash_change": False
        }
        QUEUE.write_text(json.dumps(queue_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {
        "status": "PASS",
        "sources": len(sources),
        "initialized": initialized,
        "new_candidates": new_candidates,
        "status_changes": status_changes,
        "queued_total": len(candidates),
    }
    print(json.dumps(report, ensure_ascii=False))
    return (3 if new_candidates else 0), report


def self_test() -> None:
    sample = b"<html><script>bad()</script><body><h1>Festival</h1><p>Buget 100.000 lei</p></body></html>"
    text = normalize_text(sample, "text/html")
    assert "bad" not in text and "Festival" in text and "Buget" in text
    assert keyword_hits(text, ["buget", "contract"]) == ["buget"]
    assert queue_key("x", "y") == queue_key("x", "y")
    print("VÂLCEA CLAR festival source monitor self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    code, _ = run()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
