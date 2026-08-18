#!/usr/bin/env python3
"""Generic routing and hygiene extension for LOCAL NEWS OS signal verification.

All geography and publisher choices stay instance-owned. CORE only supplies
boundary-safe matching, configurable source-locality filtering, and duplicate
share/print suppression. This layer has zero publication authority.
"""
from __future__ import annotations

import re
import urllib.parse
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parent
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import signal_radar as radar  # noqa: E402

ORIGINAL_CLASSIFY = radar.classify
ORIGINAL_RESOLVE_REGISTRY_TARGETS = radar.resolve_registry_targets
ORIGINAL_PROBE_SEED = radar.probe_seed
ORIGINAL_MERGE_QUEUE = radar.merge_queue


def phrase_matches(haystack: str, keyword: str) -> bool:
    """Match words/phrases; trailing ``*`` explicitly enables token prefixes."""
    raw = str(keyword or "").strip()
    prefix = raw.endswith("*")
    if prefix:
        raw = raw[:-1]
    hay = radar.norm_text(haystack)
    needle = radar.norm_text(raw)
    if not hay or not needle:
        return False
    if not prefix:
        return f" {needle} " in f" {hay} "
    parts = needle.split()
    if len(parts) == 1:
        return any(token.startswith(parts[0]) for token in hay.split())
    head = " ".join(parts[:-1])
    tail = re.escape(parts[-1])
    return re.search(rf"(?:^|\s){re.escape(head)}\s+{tail}\w*(?:\s|$)", hay) is not None


def _rule_matches(title: str, rule: dict[str, Any]) -> bool:
    keywords = [str(v) for v in rule.get("keywords") or [] if str(v).strip()]
    if not keywords or not any(phrase_matches(title, v) for v in keywords):
        return False
    required_any = [str(v) for v in rule.get("required_any_keywords") or [] if str(v).strip()]
    if required_any and not any(phrase_matches(title, v) for v in required_any):
        return False
    required_all = [str(v) for v in rule.get("required_all_keywords") or [] if str(v).strip()]
    if required_all and not all(phrase_matches(title, v) for v in required_all):
        return False
    excluded = [str(v) for v in rule.get("excluded_keywords") or [] if str(v).strip()]
    return not (excluded and any(phrase_matches(title, v) for v in excluded))


def classify(title: str, config: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    for rule in config.get("rules") or []:
        if _rule_matches(title, rule):
            return str(rule["id"]), [dict(row) for row in rule.get("verification_targets") or []]
    return "general_local_signal", []


def load_primary_targets(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw_path = str(config.get("primary_target_registry_path") or "").strip()
    if not raw_path:
        return {}
    doc = radar.load(radar.repo_file(raw_path))
    if doc.get("publication_authority") != "NONE":
        raise ValueError("primary target registry must have zero publication authority")
    result: dict[str, dict[str, Any]] = {}
    for row in doc.get("sources") or []:
        if not isinstance(row, dict) or not row.get("id") or not row.get("url"):
            raise ValueError("invalid primary target registry row")
        sid = str(row["id"])
        if sid in result:
            raise ValueError(f"duplicate primary target id: {sid}")
        result[sid] = row
    return result


def resolve_registry_targets(config: dict[str, Any]) -> None:
    news = radar.load(radar.repo_file(str(config.get("news_registry_path") or "")))
    manual = radar.load(radar.repo_file(str(config.get("manual_watch_registry_path") or "")))
    news_ids = {str(row.get("id")) for row in news.get("sources") or []}
    manual_ids = {str(row.get("id")) for row in manual.get("sources") or []}
    primary_ids = set(load_primary_targets(config))
    for rule in config.get("rules") or []:
        for target in rule.get("verification_targets") or []:
            ref_type, sid = str(target.get("ref_type")), str(target.get("id"))
            if ref_type == "news_source_id" and sid not in news_ids:
                raise ValueError(f"unknown news verification target: {sid}")
            elif ref_type == "manual_watch_source_id" and sid not in manual_ids:
                raise ValueError(f"unknown manual verification target: {sid}")
            elif ref_type == "primary_target_id" and sid not in primary_ids:
                raise ValueError(f"unknown primary verification target: {sid}")
            elif ref_type not in {"news_source_id", "manual_watch_source_id", "primary_target_id"}:
                raise ValueError(f"unsupported verification target type: {ref_type}")


def _query_is_distribution_variant(url: str, config: dict[str, Any]) -> bool:
    keys = {str(v).casefold() for v in config.get("drop_query_keys") or []}
    if not keys:
        return False
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    return bool(keys.intersection(str(key).casefold() for key in query))


def _generic_signal_title(title: str, config: dict[str, Any]) -> bool:
    normalized = radar.norm_text(title)
    return any(normalized == radar.norm_text(str(value)) for value in config.get("drop_signal_titles") or [])


def signal_scope_allowed(signal: dict[str, Any], config: dict[str, Any], seed_id: str | None = None) -> bool:
    if _query_is_distribution_variant(str(signal.get("signal_url") or ""), config):
        return False
    if _generic_signal_title(str(signal.get("signal_title") or ""), config):
        return False
    strict_ids = {str(v) for v in config.get("strict_locality_seed_ids") or []}
    if seed_id and seed_id in strict_ids:
        title = str(signal.get("signal_title") or "")
        anchors = [str(v) for v in config.get("locality_title_anchors") or [] if str(v).strip()]
        if anchors and not any(phrase_matches(title, anchor) for anchor in anchors):
            return False
    return True


def scoped_probe_seed(seed: dict[str, Any], config: dict[str, Any], tz, now) -> dict[str, Any]:
    row = ORIGINAL_PROBE_SEED(seed, config, tz, now)
    kept, dropped = [], []
    for signal in row.get("signals") or []:
        signal = dict(signal)
        signal["signal_seed_id"] = seed["id"]
        if signal_scope_allowed(signal, config, seed["id"]):
            kept.append(signal)
        else:
            dropped.append({"title": signal.get("signal_title"), "url": signal.get("signal_url")})
    row["signals"] = kept
    row["hygiene_dropped_count"] = len(dropped)
    row["hygiene_dropped"] = dropped[:10]
    return row


def scoped_merge_queue(current_signals, previous, config, tz, now):
    seeds = radar.seed_rows(config)
    publisher_to_seed = {str(row.get("publisher")): str(row.get("id")) for row in seeds}
    cleaned_previous = dict(previous)
    cleaned_tasks = []
    for task in previous.get("tasks") or []:
        seed_id = str(task.get("signal_seed_id") or publisher_to_seed.get(str(task.get("signal_publisher"))) or "")
        if signal_scope_allowed(task, config, seed_id or None):
            cleaned_tasks.append(task)
    cleaned_previous["tasks"] = cleaned_tasks
    return ORIGINAL_MERGE_QUEUE(current_signals, cleaned_previous, config, tz, now)


def install() -> None:
    radar.classify = classify
    radar.resolve_registry_targets = resolve_registry_targets
    radar.probe_seed = scoped_probe_seed
    radar.merge_queue = scoped_merge_queue


def self_test() -> int:
    assert phrase_matches("Job scos la concurs", "urs") is False
    assert phrase_matches("Un urs a fost văzut", "urs") is True
    assert phrase_matches("Polițiștii fac percheziții", "politi*") is True
    cfg = {
        "drop_query_keys": ["share"],
        "drop_signal_titles": ["Imprimare"],
        "strict_locality_seed_ids": ["syndicated-local"],
        "locality_title_anchors": ["Exampleville", "Local Utility"],
    }
    assert not signal_scope_allowed({"signal_title": "Imprimare", "signal_url": "https://x.test/a?share=print"}, cfg, "syndicated-local")
    assert not signal_scope_allowed({"signal_title": "National market report", "signal_url": "https://x.test/a"}, cfg, "syndicated-local")
    assert signal_scope_allowed({"signal_title": "Local Utility opens jobs", "signal_url": "https://x.test/a"}, cfg, "syndicated-local")
    print("LOCAL NEWS OS signal routing/hygiene self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
