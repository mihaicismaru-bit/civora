#!/usr/bin/env python3
"""Deterministically corroborate signal-radar items against configured primary sources.

This stage is deliberately evidence-only. It may confirm that a T1/T1B source
contains a strongly matching item, but it never turns the T2/T3 signal into a
fact, fact kernel, story, headline, or publication instruction.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import html.parser
import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import signal_radar as radar  # noqa: E402

STOPWORDS = {
    "acest", "aceasta", "aceste", "acesti", "ale", "alt", "alte", "azi", "catre",
    "care", "cand", "cele", "cel", "din", "dintre", "dupa", "este", "fost", "fosta",
    "fostul", "intr", "intre", "judet", "judetul", "la", "mai", "mult", "pentru", "prin",
    "sunt", "unei", "unui", "valcea", "valcean", "valceni", "foto", "video", "stiri",
    "anunt", "comunicat", "oficial", "privind", "asupra", "doua", "trei", "noua",
}
TITLE_PATTERNS = (
    r'<meta\b(?=[^>]*(?:property|name)=["\']og:title["\'])(?=[^>]*content=["\']([^"\']+)["\'])[^>]*>',
    r'<h1\b[^>]*>(.*?)</h1>',
    r'<title\b[^>]*>(.*?)</title>',
)


class TextExtractor(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            text = radar.clean(data)
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def repo_file(raw: str) -> Path:
    return radar.repo_file(raw)


def normalize(value: str) -> str:
    return radar.norm_text(value)


def tokens(value: str) -> set[str]:
    out: set[str] = set()
    for token in normalize(value).split():
        if token in STOPWORDS:
            continue
        if token.isdigit():
            if len(token) >= 2:
                out.add(token)
            continue
        if len(token) >= 4:
            out.add(token)
    return out


def extract_title(article: str, fallback: str) -> str:
    for pattern in TITLE_PATTERNS:
        match = re.search(pattern, article, flags=re.I | re.S)
        if match:
            value = radar.clean(html.unescape(match.group(1)))
            if 8 <= len(value) <= 300:
                return value
    return radar.clean(fallback)


def extract_text(article: str) -> str:
    parser = TextExtractor()
    parser.feed(article)
    return parser.text()[:120_000]


def target_registry(config: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    docs = [
        ("news_source_id", load(repo_file(str(config.get("news_registry_path") or "")))),
        ("manual_watch_source_id", load(repo_file(str(config.get("manual_watch_registry_path") or "")))),
    ]
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for ref_type, doc in docs:
        for row in doc.get("sources") or []:
            if not isinstance(row, dict) or not row.get("id") or not row.get("url"):
                continue
            result[(ref_type, str(row["id"]))] = {
                "ref_type": ref_type,
                "id": str(row["id"]),
                "name": str(row.get("publisher") or row["id"]),
                "url": str(row["url"]),
                "tier": str(row.get("tier") or "T1"),
                "status": row.get("status"),
                "enabled": row.get("enabled", True),
            }
    return result


def candidate_links(target: dict[str, Any], max_links: int) -> tuple[list[tuple[str, str]], str | None]:
    try:
        listing, final = radar.fetch(str(target["url"]), max_bytes=2_000_000, timeout=14)
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"[:400]
    parser = radar.AnchorParser()
    parser.feed(listing)
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()
    for href, label in parser.links:
        candidate = radar.article_like(final, href, label)
        if candidate and candidate[0] not in seen:
            seen.add(candidate[0])
            candidates.append(candidate)
        if len(candidates) >= max_links:
            break
    # Some watch targets are themselves a stable primary item/feed page. Keep
    # the root as a fallback candidate so matching can use its own text.
    candidates.append((final, target["name"]))
    return candidates, None


def fetch_primary_candidate(url: str, fallback_title: str, tz: ZoneInfo) -> dict[str, Any] | None:
    try:
        article, final = radar.fetch(url, max_bytes=1_600_000, timeout=12)
    except Exception:
        return None
    title = extract_title(article, fallback_title)
    body = extract_text(article)
    if len(body) < 80:
        return None
    published = radar.strict_published_at(article, tz)
    return {
        "url": final,
        "title": title,
        "published_at": published.isoformat(timespec="seconds") if published else None,
        "title_tokens": sorted(tokens(title)),
        "body_tokens": sorted(tokens(body)),
        "content_sha256": hashlib.sha256(article.encode("utf-8", errors="replace")).hexdigest(),
    }


def build_target_corpus(target: dict[str, Any], tz: ZoneInfo, *, max_links: int, max_fetches: int) -> dict[str, Any]:
    links, error = candidate_links(target, max_links)
    if error:
        return {"target": target, "status": "DEGRADED", "error": error, "documents": []}
    documents: list[dict[str, Any]] = []
    seen: set[str] = set()
    for url, fallback in links[:max_fetches]:
        doc = fetch_primary_candidate(url, fallback, tz)
        if doc and doc["url"] not in seen:
            seen.add(doc["url"])
            documents.append(doc)
    return {
        "target": target,
        "status": "PASS" if documents else "DEGRADED",
        "error": None if documents else "no_primary_documents_retrieved",
        "documents": documents,
    }


def match_score(signal_title: str, document: dict[str, Any], *, sensitive: bool) -> dict[str, Any]:
    signal_tokens = tokens(signal_title)
    title_tokens = set(document.get("title_tokens") or [])
    body_tokens = set(document.get("body_tokens") or [])
    title_shared = signal_tokens & title_tokens
    body_shared = signal_tokens & body_tokens
    distinctive = {t for t in signal_tokens if t.isdigit() or len(t) >= 7}
    distinctive_shared = distinctive & body_tokens
    coverage = len(body_shared) / max(1, len(signal_tokens))
    title_coverage = len(title_shared) / max(1, len(signal_tokens))
    score = min(1.0, coverage * 0.65 + title_coverage * 0.35 + min(len(distinctive_shared), 3) * 0.08)
    minimum_shared = 4 if sensitive else 3
    strong = len(body_shared) >= minimum_shared and coverage >= (0.28 if sensitive else 0.22)
    if sensitive:
        strong = strong and bool(distinctive_shared)
    return {
        "score": round(score, 4),
        "strong": bool(strong),
        "shared_terms": sorted(body_shared),
        "title_shared_terms": sorted(title_shared),
        "distinctive_shared_terms": sorted(distinctive_shared),
        "coverage": round(coverage, 4),
    }


def date_compatible(signal: dict[str, Any], document: dict[str, Any], tz: ZoneInfo) -> bool:
    signal_dt = radar.parse_time(str(signal.get("published_at") or ""), tz)
    primary_dt = radar.parse_time(str(document.get("published_at") or ""), tz)
    if signal_dt is None or primary_dt is None:
        return True
    return abs((signal_dt - primary_dt).total_seconds()) <= 72 * 3600


def verify_task(task: dict[str, Any], corpora: dict[tuple[str, str], dict[str, Any]], tz: ZoneInfo) -> dict[str, Any]:
    targets = task.get("verification_targets") or []
    if not targets:
        return {
            "signal_id": task.get("signal_id"),
            "signal_title": task.get("signal_title"),
            "signal_url": task.get("signal_url"),
            "signal_publisher": task.get("signal_publisher"),
            "signal_published_at": task.get("published_at"),
            "verification_route_id": task.get("verification_route_id"),
            "status": "UNROUTED_NEEDS_TARGET_DISCOVERY",
            "publication_authority": "NONE",
            "material_fact_ready": False,
            "fact_kernel_ready": False,
        }
    best: tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]] | None = None
    attempts: list[dict[str, Any]] = []
    sensitive = bool(task.get("signal_sensitive")) or str(task.get("verification_route_id")) == "police_public_safety"
    for ref in targets:
        key = (str(ref.get("ref_type")), str(ref.get("id")))
        corpus = corpora.get(key)
        if not corpus:
            attempts.append({"target": {"ref_type": key[0], "id": key[1]}, "status": "TARGET_NOT_RESOLVED"})
            continue
        attempts.append({
            "target": {"ref_type": key[0], "id": key[1], "name": corpus["target"]["name"], "url": corpus["target"]["url"]},
            "status": corpus.get("status"),
            "error": corpus.get("error"),
            "documents_examined": len(corpus.get("documents") or []),
        })
        for doc in corpus.get("documents") or []:
            if not date_compatible(task, doc, tz):
                continue
            score = match_score(str(task.get("signal_title") or ""), doc, sensitive=sensitive)
            if not score["strong"]:
                continue
            if best is None or score["score"] > best[0]:
                best = (float(score["score"]), corpus["target"], doc, score)
    base = {
        "signal_id": task.get("signal_id"),
        "signal_title": task.get("signal_title"),
        "signal_url": task.get("signal_url"),
        "signal_publisher": task.get("signal_publisher"),
        "signal_tier": task.get("signal_tier"),
        "signal_published_at": task.get("published_at"),
        "verification_route_id": task.get("verification_route_id"),
        "attempts": attempts,
        "publication_authority": "NONE",
        "signal_is_fact": False,
        "material_fact_ready": False,
        "fact_kernel_ready": False,
    }
    if best is None:
        return {**base, "status": "NO_PRIMARY_MATCH"}
    _, target, doc, score = best
    return {
        **base,
        "status": "PRIMARY_MATCH_FOUND",
        "primary_evidence": {
            "source_id": target["id"],
            "source_name": target["name"],
            "source_tier": target["tier"],
            "source_url": target["url"],
            "primary_item_url": doc["url"],
            "primary_item_title": doc["title"],
            "primary_published_at": doc.get("published_at"),
            "content_sha256": doc["content_sha256"],
            "match_score": score["score"],
            "matched_terms": score["shared_terms"],
            "distinctive_matched_terms": score["distinctive_shared_terms"],
        },
        "next_gate": "STRUCTURED_FACT_EXTRACTION_FROM_PRIMARY_EVIDENCE",
    }


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    config, tz = radar.load_config(instance_id)
    queue_path = ROOT / str(config["queue_path"])
    queue = load(queue_path)
    if queue.get("contract") != "LOCAL_NEWS_OS_SIGNAL_VERIFICATION_QUEUE_V1":
        raise ValueError("signal verification queue contract mismatch")
    if queue.get("publication_authority") != "NONE" or queue.get("signal_may_publish_directly") is not False:
        raise ValueError("unsafe signal verification queue authority")
    registry = target_registry(config)
    referenced: set[tuple[str, str]] = set()
    for task in queue.get("tasks") or []:
        for ref in task.get("verification_targets") or []:
            key = (str(ref.get("ref_type")), str(ref.get("id")))
            if key not in registry:
                raise ValueError(f"verification target missing from registry: {key}")
            referenced.add(key)
    max_links = int(config.get("primary_verifier_max_links_per_target") or 14)
    max_fetches = int(config.get("primary_verifier_max_fetches_per_target") or 10)
    max_workers = max(1, min(int(config.get("primary_verifier_max_workers") or 6), 10, max(1, len(referenced))))
    corpora: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=f"primary-{instance_id}") as pool:
        futures = {pool.submit(build_target_corpus, registry[key], tz, max_links=max_links, max_fetches=max_fetches): key for key in referenced}
        for future in as_completed(futures):
            corpora[futures[future]] = future.result()
    results = [verify_task(task, corpora, tz) for task in queue.get("tasks") or []]
    matches = sum(1 for row in results if row["status"] == "PRIMARY_MATCH_FOUND")
    no_match = sum(1 for row in results if row["status"] == "NO_PRIMARY_MATCH")
    unrouted = sum(1 for row in results if row["status"] == "UNROUTED_NEEDS_TARGET_DISCOVERY")
    now = datetime.now(tz)
    state = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_PRIMARY_SIGNAL_VERIFICATION_STATE_V1",
        "instance_id": instance_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "publication_authority": "NONE",
        "primary_match_is_fact_kernel": False,
        "primary_match_may_publish_directly": False,
        "required_next_gate": "STRUCTURED_FACT_EXTRACTION_FROM_PRIMARY_EVIDENCE",
        "queue_generated_at": queue.get("generated_at"),
        "task_count": len(results),
        "primary_match_count": matches,
        "no_match_count": no_match,
        "unrouted_count": unrouted,
        "target_count": len(referenced),
        "targets_ok": sum(1 for row in corpora.values() if row.get("status") == "PASS"),
        "results": results,
    }
    output_path = ROOT / str(config.get("primary_verification_state_path") or "")
    if not str(config.get("primary_verification_state_path") or "").strip():
        raise ValueError("primary_verification_state_path missing")
    if write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def validate(instance_id: str) -> dict[str, Any]:
    config, _ = radar.load_config(instance_id)
    registry = target_registry(config)
    output = str(config.get("primary_verification_state_path") or "").strip()
    if not output:
        raise ValueError("primary verification state path missing")
    if not registry:
        raise ValueError("primary verifier registry empty")
    return {"status": "PASS", "instance_id": instance_id, "registered_targets": len(registry), "publication_authority": "NONE"}


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    doc = {
        "title_tokens": sorted(tokens("Accident rutier pe DN7 în localitate")),
        "body_tokens": sorted(tokens("Polițiștii au intervenit la un accident rutier produs pe DN7 în localitate. Două persoane au fost evaluate.")),
        "published_at": "2026-08-17T15:00:00+03:00",
    }
    score = match_score("Accident pe DN7 în localitate, două persoane implicate", doc, sensitive=False)
    assert score["strong"] is True, score
    weak = match_score("Festival cultural cu artiști locali", doc, sensitive=False)
    assert weak["strong"] is False, weak
    assert date_compatible({"published_at": "2026-08-17T16:00:00+03:00"}, doc, tz)
    print("LOCAL NEWS OS primary signal verifier self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
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
    state = run(args.instance, write=not args.no_write)
    print(json.dumps({
        "status": "PASS",
        "task_count": state["task_count"],
        "primary_match_count": state["primary_match_count"],
        "no_match_count": state["no_match_count"],
        "unrouted_count": state["unrouted_count"],
        "targets_ok": state["targets_ok"],
        "target_count": state["target_count"],
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
