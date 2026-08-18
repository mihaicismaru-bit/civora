#!/usr/bin/env python3
"""Monitor VÂLCEA CLAR performing-arts sources and queue material changes.

This is a source-signal layer for the general newsroom. Event dates remain event
semantics, not publication timestamps. A source hash change never publishes by
itself; it only creates a verification candidate for the general editorial engine.
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
REGISTRY = ROOT / "editorial" / "performing_arts_source_registry.json"
STATE = ROOT / "state" / "performing_arts_source_state.json"
QUEUE = ROOT / "editorial" / "performing_arts_update_candidates.json"
TZ = ZoneInfo("Europe/Bucharest")
UA = "Mozilla/5.0 VÂLCEA-CLAR-Performing-Arts/1.0 (+https://valceaclar.ro/)"
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
    req = Request(str(source["url"]), headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/json,text/plain;q=0.9,*/*;q=0.6",
    })
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


def keyword_hits(text: str, terms: list[str]) -> list[str]:
    folded = text.casefold()
    return sorted({term for term in terms if term.casefold() in folded})


def excerpt(text: str, terms: list[str], limit: int = 1000) -> str:
    folded = text.casefold()
    indexes = [folded.find(term.casefold()) for term in terms if term and folded.find(term.casefold()) >= 0]
    start = max(0, (min(indexes) if indexes else 0) - 180)
    return re.sub(r"\s+", " ", text[start:start + limit]).strip()


def queue_key(source_id: str, sha: str) -> str:
    return hashlib.sha256(f"performing-arts:{source_id}:{sha}".encode()).hexdigest()[:20]


def run() -> tuple[int, dict]:
    registry = load(REGISTRY, {})
    sources = registry.get("sources") or []
    if not isinstance(sources, list) or not sources:
        raise SystemExit("Performing arts source registry is empty")
    policy = registry.get("policy") or {}
    money_terms = [str(x) for x in policy.get("public_money_terms") or []]
    programme_terms = [str(x) for x in policy.get("programme_terms") or []]

    state = load(STATE, {"schema_version":"1.0","sources":{}})
    state_rows = state.setdefault("sources", {})
    queue_doc = load(QUEUE, {
        "schema_version":"1.0",
        "product":"VÂLCEA CLAR performing arts update candidates",
        "candidates":[],
    })
    candidates = queue_doc.setdefault("candidates", [])
    known_keys = {str(row.get("key") or "") for row in candidates if isinstance(row, dict)}
    now = datetime.now(TZ).isoformat(timespec="seconds")
    new_candidates = status_changes = initialized = 0

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
                    "status":"ACTIVE","sha256":sha,"url":source["url"],
                    "final_url":transport["final_url"],"last_material_change_at":now,"last_error":None,
                    "source_contract":source.get("source_contract"),
                }
                continue
            if sha != previous_sha:
                key = queue_key(source_id, sha)
                if key not in known_keys:
                    money_hits = keyword_hits(text, money_terms)
                    programme_hits = keyword_hits(text, programme_terms)
                    candidates.append({
                        "key":key,
                        "status":"needs_editorial_verification",
                        "detected_at":now,
                        "source_id":source_id,
                        "institution":source.get("institution"),
                        "source_contract":source.get("source_contract"),
                        "tier":source.get("tier"),
                        "url":source.get("url"),
                        "scope":source.get("scope") or [],
                        "previous_sha256":previous_sha,
                        "current_sha256":sha,
                        "public_money_signal":bool(money_hits),
                        "public_money_terms":money_hits,
                        "programme_signal":bool(programme_hits),
                        "programme_terms":programme_hits,
                        "excerpt":excerpt(text, [str(source.get("institution") or "")] + money_terms + programme_terms),
                        "event_date_is_not_published_at":True,
                        "publication_authority":False,
                    })
                    known_keys.add(key)
                    new_candidates += 1
                state_rows[source_id] = {
                    "status":"ACTIVE","sha256":sha,"url":source["url"],
                    "final_url":transport["final_url"],"last_material_change_at":now,"last_error":None,
                    "source_contract":source.get("source_contract"),
                }
            elif previous_status != "ACTIVE":
                status_changes += 1
                state_rows[source_id] = {**previous,"status":"ACTIVE","url":source["url"],"final_url":transport["final_url"],"last_error":None}
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            if previous_status != "ERROR" or str(previous.get("last_error") or "") != error:
                status_changes += 1
                state_rows[source_id] = {**previous,"status":"ERROR","url":source.get("url"),"last_error":error,"last_error_at":now,"source_contract":source.get("source_contract")}

    if initialized or new_candidates or status_changes or not STATE.is_file():
        STATE.parent.mkdir(parents=True, exist_ok=True)
        state["policy"] = {
            "last_known_good_preserved":True,
            "source_change_is_not_publishable_fact":True,
            "event_date_is_not_published_at":True,
        }
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if new_candidates or not QUEUE.is_file():
        queue_doc["candidate_count"] = len(candidates)
        queue_doc["policy"] = {
            "source_change_is_not_publishable_fact":True,
            "editorial_verification_required":True,
            "autopublish_from_hash_change":False,
            "feed_general_editorial_opportunity_engine":True,
        }
        QUEUE.write_text(json.dumps(queue_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    report = {"status":"PASS","sources":len(sources),"initialized":initialized,"new_candidates":new_candidates,"status_changes":status_changes,"queued_total":len(candidates)}
    print(json.dumps(report, ensure_ascii=False))
    return (3 if new_candidates else 0), report


def self_test() -> None:
    sample = b"<html><body><h1>Concert</h1><p>21 septembrie 2026, bilete 40 lei</p></body></html>"
    text = normalize_text(sample, "text/html")
    assert "Concert" in text and "40 lei" in text
    assert keyword_hits(text, ["concert","premier"]) == ["concert"]
    assert queue_key("x","y") == queue_key("x","y")
    print("VÂLCEA CLAR performing arts source monitor self-test: PASS")


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
