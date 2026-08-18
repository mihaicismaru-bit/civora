#!/usr/bin/env python3
"""Generic boundary-safe routing extension for LOCAL NEWS OS signal verification.

Keeps signal discovery evidence-only while allowing instance config to express
exact phrase boundaries and dedicated primary verification targets without
hardcoding geography or publishers into CORE.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CORE = Path(__file__).resolve().parent
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import signal_radar as radar  # noqa: E402

ORIGINAL_CLASSIFY = radar.classify
ORIGINAL_RESOLVE_REGISTRY_TARGETS = radar.resolve_registry_targets


def phrase_matches(haystack: str, keyword: str) -> bool:
    """Match normalized words/phrases, never arbitrary substrings.

    Example: ``urs`` must not match ``concurs``.
    """
    hay = radar.norm_text(haystack)
    needle = radar.norm_text(keyword)
    if not hay or not needle:
        return False
    return f" {needle} " in f" {hay} "


def _rule_matches(title: str, rule: dict[str, Any]) -> bool:
    keywords = [str(value) for value in rule.get("keywords") or [] if str(value).strip()]
    if not keywords or not any(phrase_matches(title, value) for value in keywords):
        return False

    required_any = [str(value) for value in rule.get("required_any_keywords") or [] if str(value).strip()]
    if required_any and not any(phrase_matches(title, value) for value in required_any):
        return False

    required_all = [str(value) for value in rule.get("required_all_keywords") or [] if str(value).strip()]
    if required_all and not all(phrase_matches(title, value) for value in required_all):
        return False

    excluded = [str(value) for value in rule.get("excluded_keywords") or [] if str(value).strip()]
    if excluded and any(phrase_matches(title, value) for value in excluded):
        return False
    return True


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


def install() -> None:
    radar.classify = classify
    radar.resolve_registry_targets = resolve_registry_targets


def self_test() -> int:
    assert phrase_matches("APAVIL scoate la concurs trei posturi", "urs") is False
    assert phrase_matches("Un urs a fost văzut lângă localitate", "urs") is True
    assert phrase_matches("Săptămâna Europeană a Mobilității", "saptamana europeana") is True

    cfg = {
        "rules": [
            {
                "id": "apavil_employment",
                "required_any_keywords": ["apavil"],
                "keywords": ["concurs", "posturi"],
                "verification_targets": [{"ref_type": "primary_target_id", "id": "apavil-angajari"}],
            },
            {
                "id": "fire_rescue_alert",
                "keywords": ["urs", "incendiu"],
                "verification_targets": [{"ref_type": "news_source_id", "id": "isu"}],
            },
        ]
    }
    route, targets = classify("APAVIL scoate la concurs trei posturi", cfg)
    assert route == "apavil_employment" and targets[0]["id"] == "apavil-angajari"
    route, _ = classify("Pompierii au intervenit după apariția unui urs", cfg)
    assert route == "fire_rescue_alert"
    route, targets = classify("Concurs de fotografie locală", cfg)
    assert route == "general_local_signal" and targets == []
    print("LOCAL NEWS OS boundary-safe signal routing self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
