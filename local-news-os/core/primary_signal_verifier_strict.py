#!/usr/bin/env python3
"""Strict false-positive guard for LOCAL NEWS OS primary signal verification.

Builds on the evidence-only primary verifier, but requires trustworthy primary
publication time and substantial event-title agreement. Instance identity tokens
are ignored as non-evidence so sharing the same city/county/brand cannot create a
match. This module never grants publication or Fact Kernel authority.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
ROOT = CORE.parents[1]
import sys
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as base  # noqa: E402
import signal_radar as radar  # noqa: E402

LEGACY_MATCH_SCORE = base.match_score
IDENTITY_TOKENS: set[str] = set()


def _raw_tokens(value: str) -> set[str]:
    return base.tokens(value)


def instance_identity_tokens(instance_id: str) -> set[str]:
    cfg = base.load(ROOT / "local-news-os" / "instances" / instance_id / "instance.json")
    values: list[str] = [str(cfg.get("instance_id") or ""), str(cfg.get("canonical_domain") or "")]
    brand = cfg.get("brand") or {}
    values.extend(str(brand.get(key) or "") for key in ("name", "short_name"))
    geography = cfg.get("geography") or {}
    values.extend(str(geography.get(key) or "") for key in ("primary_name", "county"))
    for key in ("settlements", "aliases"):
        rows = geography.get(key) or []
        if isinstance(rows, list):
            values.extend(str(row) for row in rows)
    result: set[str] = set()
    for value in values:
        result.update(_raw_tokens(value))
    return result


def evidence_tokens(value: str) -> set[str]:
    return _raw_tokens(value) - IDENTITY_TOKENS


def strict_date_compatible(signal: dict[str, Any], document: dict[str, Any], tz: ZoneInfo) -> bool:
    signal_dt = radar.parse_time(str(signal.get("published_at") or ""), tz)
    primary_dt = radar.parse_time(str(document.get("published_at") or ""), tz)
    # A primary page without trustworthy article publication time is useful for
    # manual research, but cannot corroborate a fresh signal automatically.
    if signal_dt is None or primary_dt is None:
        return False
    return abs((signal_dt - primary_dt).total_seconds()) <= 36 * 3600


def strict_match_score(signal_title: str, document: dict[str, Any], *, sensitive: bool) -> dict[str, Any]:
    signal_tokens = evidence_tokens(signal_title)
    title_tokens = set(document.get("title_tokens") or []) - IDENTITY_TOKENS
    body_tokens = set(document.get("body_tokens") or []) - IDENTITY_TOKENS
    title_shared = signal_tokens & title_tokens
    body_shared = signal_tokens & body_tokens
    title_coverage = len(title_shared) / max(1, len(signal_tokens))
    body_coverage = len(body_shared) / max(1, len(signal_tokens))

    # Event evidence must be present in the primary item's own title. Body-only
    # thematic similarity (hospital care, local government, football, etc.) is
    # insufficient because it produced false positives in live Vâlcea runs.
    min_title_shared = 4 if sensitive else 3
    min_title_coverage = 0.42 if sensitive else 0.34
    min_body_shared = 4 if sensitive else 3
    strong = (
        len(signal_tokens) >= 3
        and len(title_shared) >= min_title_shared
        and title_coverage >= min_title_coverage
        and len(body_shared) >= min_body_shared
        and body_coverage >= 0.30
    )

    distinctive = {token for token in signal_tokens if len(token) >= 7 and not token.isdigit()}
    distinctive_title_shared = distinctive & title_tokens
    if sensitive:
        strong = strong and len(distinctive_title_shared) >= 2
    else:
        strong = strong and len(distinctive_title_shared) >= 1

    score = min(1.0, title_coverage * 0.65 + body_coverage * 0.25 + min(len(distinctive_title_shared), 3) * 0.08)
    return {
        "score": round(score, 4),
        "strong": bool(strong),
        "shared_terms": sorted(body_shared),
        "title_shared_terms": sorted(title_shared),
        "distinctive_shared_terms": sorted(distinctive_title_shared),
        "coverage": round(body_coverage, 4),
        "title_coverage": round(title_coverage, 4),
        "strict_false_positive_guard": True,
    }


def install_strict_guard(instance_id: str) -> None:
    global IDENTITY_TOKENS
    IDENTITY_TOKENS = instance_identity_tokens(instance_id)
    base.date_compatible = strict_date_compatible
    base.match_score = strict_match_score


def validate(instance_id: str) -> dict[str, Any]:
    install_strict_guard(instance_id)
    report = base.validate(instance_id)
    return {
        **report,
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "title_event_overlap_required": True,
        "identity_tokens_ignored": len(IDENTITY_TOKENS),
    }


def run(instance_id: str, *, write: bool) -> dict[str, Any]:
    install_strict_guard(instance_id)
    state = base.run(instance_id, write=write)
    state["verification_policy"] = {
        "strict_false_positive_guard": True,
        "primary_published_at_required": True,
        "max_publication_time_delta_hours": 36,
        "title_event_overlap_required": True,
        "instance_identity_is_not_event_evidence": True,
        "body_only_similarity_rejected": True,
    }
    if write:
        config, _ = radar.load_config(instance_id)
        output_path = ROOT / str(config["primary_verification_state_path"])
        output_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return state


def self_test() -> int:
    global IDENTITY_TOKENS
    tz = ZoneInfo("Europe/Bucharest")
    IDENTITY_TOKENS = {"testcity", "testcounty"}

    # Missing primary publication time must never auto-corroborate.
    assert strict_date_compatible(
        {"published_at": "2026-08-17T17:00:00+03:00"},
        {"published_at": None},
        tz,
    ) is False

    # Same topic/body but unrelated title: reject.
    hospital_doc = {
        "title_tokens": sorted(_raw_tokens("Condiții de internare și externare la spital")),
        "body_tokens": sorted(_raw_tokens("recuperare îngrijire la domiciliu persoane pacienți servicii medicale")),
        "published_at": "2026-08-17T16:00:00+03:00",
    }
    false_health = strict_match_score(
        "Se deschide centrul social cu recuperare, îngrijire la domiciliu și masă caldă",
        hospital_doc,
        sensitive=False,
    )
    assert false_health["strong"] is False, false_health

    # Shared generic sport identity/theme but different event: reject.
    sport_doc = {
        "title_tokens": sorted(_raw_tokens("Jucătorii intră pe teren pentru grupele Cupei naționale TestCity")),
        "body_tokens": sorted(_raw_tokens("echipa TestCity joacă în cupă și pregătește partida pentru calificare")),
        "published_at": "2026-08-17T15:00:00+03:00",
    }
    false_sport = strict_match_score(
        "Ziua comunei: aniversări de familie și Cupa locală au adus generațiile împreună",
        sport_doc,
        sensitive=False,
    )
    assert false_sport["strong"] is False, false_sport

    # Same event with strong title and body overlap: accept.
    true_doc = {
        "title_tokens": sorted(_raw_tokens("Percheziții domiciliare pentru arme și muniții în două localități")),
        "body_tokens": sorted(_raw_tokens("Polițiștii au efectuat percheziții domiciliare și au descoperit arme muniții cartușe în două localități")),
        "published_at": "2026-08-17T14:40:00+03:00",
    }
    true_match = strict_match_score(
        "Percheziții domiciliare: arme, muniții și cartușe descoperite în două localități",
        true_doc,
        sensitive=True,
    )
    assert true_match["strong"] is True, true_match
    assert strict_date_compatible(
        {"published_at": "2026-08-17T15:00:00+03:00"},
        true_doc,
        tz,
    ) is True

    print("LOCAL NEWS OS strict primary signal verifier self-test: PASS")
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
        "strict_false_positive_guard": True,
        "publication_authority": "NONE",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
