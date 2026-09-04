#!/usr/bin/env python3
"""Promote the explicit ISU Vâlcea homepage daily intervention tally into one Fact Kernel.

The official homepage exposes a small, structured, low-risk public-safety summary
(e.g. total interventions plus category totals). Generic discovery intentionally
does not contain source-specific parsing, so this specialist adapter performs a
strict first-party readback and writes only through the canonical Fact Kernel
orchestrator. It never treats the tally as independent incident verification.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date, datetime, time, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(REPO_ROOT / "local-news-os" / "core"))
from temporal_freshness import durable_story_temporal_violations

SOURCE_URL = "https://isuvl.igsu.ro/"
SOURCE_HOST = "isuvl.igsu.ro"
FACTS = ROOT / "editorial" / "facts_registry.json"
STATE = ROOT / "editorial" / "isu_valcea_homepage_summary_kernel_state.json"
TZ = ZoneInfo("Europe/Bucharest")
MAX_AGE_DAYS = 2
STORY_ID = "isu-valcea-interventii-zilnice"
AUTO_SCOPE = "isu_valcea_homepage_daily_summary"
PROMOTION_GATE = "ISU_HOMEPAGE_NUMERIC_SUMMARY_V1"


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in {"script", "style", "noscript", "svg"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return " ".join(self.parts)


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    asciiish = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    asciiish = (
        asciiish.replace("ş", "s").replace("ș", "s")
        .replace("ţ", "t").replace("ț", "t")
    )
    return " ".join(asciiish.upper().split())


def canonical_digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_summary(visible_text: str) -> dict[str, Any] | None:
    text = fold(visible_text)
    header = re.search(
        r"\b(\d{1,4})\s+INTERVENTII\s+IN\s+DATA\s+DE\s+"
        r"((?:0?[1-9]|[12]\d|3[01])\.(?:0?[1-9]|1[0-2])\.20\d{2})\b",
        text,
    )
    if not header:
        return None

    total = int(header.group(1))
    if total <= 0:
        return None

    # Bind category reads to the same compact homepage block so unrelated page
    # counters cannot be accidentally combined into a synthetic tally.
    block = text[header.end(): header.end() + 500]
    patterns = {
        "fires": r"\b(\d{1,4})\s+INCENDII\b",
        "first_aid": r"\b(\d{1,4})\s+PRIM\s+AJUTOR\b",
        "extrication": r"\b(\d{1,4})\s+DESCARCERARE\b",
        "rescue": r"\b(\d{1,4})\s+SALVARE\b",
        "other": r"\b(\d{1,4})\s+ALTE\s+INTERVENTII\b",
    }
    counts: dict[str, int] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, block)
        if not match:
            return None
        counts[key] = int(match.group(1))

    if sum(counts.values()) != total:
        return None

    event_date = datetime.strptime(header.group(2), "%d.%m.%Y").date()
    return {
        "event_date": event_date,
        "date_text": header.group(2),
        "total": total,
        **counts,
        "evidence_block_sha256": hashlib.sha256(
            (header.group(0) + " " + block[:350]).encode("utf-8")
        ).hexdigest(),
    }


def fetch_visible_text(timeout: int = 20) -> tuple[str, str]:
    request = Request(
        SOURCE_URL,
        headers={
            "User-Agent": "VALCEA-CLAR-CIVORA/1.0 (+https://valceaclar.ro)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        final_url = response.geturl()
        if urlsplit(final_url).scheme != "https" or (urlsplit(final_url).hostname or "").casefold() != SOURCE_HOST:
            raise RuntimeError(f"unexpected ISU redirect target: {final_url}")
        payload = response.read(2_000_000)
        content_type = response.headers.get_content_type()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise RuntimeError(f"unexpected ISU content type: {content_type}")
        charset = response.headers.get_content_charset() or "utf-8"
    html = payload.decode(charset, errors="replace")
    parser = VisibleTextParser()
    parser.feed(html)
    visible = parser.text()
    if len(visible) < 200:
        raise RuntimeError("ISU homepage visible text too short")
    return visible, final_url


def month_name_ro(month: int) -> str:
    return {
        1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie",
        5: "mai", 6: "iunie", 7: "iulie", 8: "august",
        9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
    }[month]


def human_date(value: date) -> str:
    return f"{value.day} {month_name_ro(value.month)} {value.year}"


def fresh_summary(summary: dict[str, Any], *, today: date) -> tuple[bool, str]:
    event_date = summary["event_date"]
    age = (today - event_date).days
    if age < 0:
        return False, "future_summary_date"
    if age > MAX_AGE_DAYS:
        return False, "stale_summary_date"
    return True, "fresh"


def build_story(summary: dict[str, Any], *, now: datetime, source_url: str) -> dict[str, Any]:
    event_date: date = summary["event_date"]
    date_label = human_date(event_date)
    total = summary["total"]
    fires = summary["fires"]
    first_aid = summary["first_aid"]
    extrication = summary["extrication"]
    rescue = summary["rescue"]
    other = summary["other"]

    headline = f"ISU Vâlcea: {total} de intervenții pe {date_label}, dintre care {first_aid} de prim ajutor"
    dek = (
        f"ISU Vâlcea raportează pentru {date_label} un total de {total} de intervenții: "
        f"{fires} incendii, {first_aid} de prim ajutor și {other} alte intervenții."
    )
    claims = [
        {
            "id": "primary-1",
            "role": "material_change",
            "kind": "attributed_statement",
            "attribution": "ISU Vâlcea",
            "text": f"ISU Vâlcea raportează {total} de intervenții pentru data de {date_label}.",
            "source_urls": [source_url],
        },
        {
            "id": "primary-2",
            "role": "context",
            "kind": "attributed_statement",
            "attribution": "ISU Vâlcea",
            "text": (
                f"Bilanțul oficial indică {fires} incendii, {first_aid} intervenții de prim ajutor, "
                f"{extrication} descarcerări, {rescue} salvări și {other} alte intervenții."
            ),
            "source_urls": [source_url],
        },
    ]

    valid_from = datetime.combine(event_date, time(0, 0), tzinfo=TZ)
    valid_until = datetime.combine(event_date + timedelta(days=3), time(23, 59), tzinfo=TZ)
    story = {
        "id": STORY_ID,
        "status": "verified",
        "section": "URGENȚE",
        "priority": 94,
        "confidence": 98,
        "material_fact_gate": "PASS",
        "valid_from": valid_from.isoformat(timespec="seconds"),
        "valid_until": valid_until.isoformat(timespec="seconds"),
        "slots": ["morning", "evening"],
        "headline": headline,
        "dek": dek,
        "paragraphs": [],
        "sources": [{"name": "ISU Vâlcea — pagina oficială", "url": source_url, "tier": "T1"}],
        "auto_generated": True,
        "auto_scope": AUTO_SCOPE,
        "fact_kernel": {
            "format_hint": "straight_news",
            "headline": {"text": headline, "source_urls": [source_url]},
            "dek": {"text": dek, "source_urls": [source_url]},
            "claims": claims,
        },
        "primary_source_verification": {
            "verified_at": now.isoformat(timespec="seconds"),
            "promotion_gate": PROMOTION_GATE,
            "source_family": "ISU",
            "direct_first_party_homepage_numeric_readback": True,
            "fresh_explicit_date_required": True,
            "freshness_window_days": MAX_AGE_DAYS,
            "homepage_evidence_block_sha256": summary["evidence_block_sha256"],
            "category_sum_reconciled_to_total": True,
            "secondary_signal_used_as_fact": False,
            "individual_incidents_independently_verified": False,
            "source_statement_presented_as_independent_verification": False,
            "continuous_story_first": True,
        },
    }
    violations = durable_story_temporal_violations(story, "ro-RO")
    if violations:
        raise ValueError(f"durable temporal language violation: {violations}")
    story["primary_source_verification"]["promotion_fingerprint_sha256"] = canonical_digest(
        {
            "id": STORY_ID,
            "event_date": event_date.isoformat(),
            "source_url": source_url,
            "summary": {key: summary[key] for key in ("total", "fires", "first_aid", "extrication", "rescue", "other")},
            "evidence": summary["evidence_block_sha256"],
        }
    )
    return story


def upsert_fact(document: dict[str, Any], story: dict[str, Any]) -> tuple[dict[str, Any], bool, str | None]:
    out = copy.deepcopy(document)
    facts = list(out.get("facts") or [])
    existing_index: int | None = None
    for index, row in enumerate(facts):
        if isinstance(row, dict) and row.get("id") == story["id"]:
            existing_index = index
            break

    source_url = story["sources"][0]["url"]
    if existing_index is None:
        for row in facts:
            if not isinstance(row, dict):
                continue
            for source in row.get("sources") or []:
                if isinstance(source, dict) and source.get("url") == source_url:
                    return out, False, str(row.get("id") or "unknown")

    if existing_index is None:
        facts.append(story)
        changed = True
    else:
        changed = facts[existing_index] != story
        if changed:
            facts[existing_index] = story
    out["facts"] = facts
    return out, changed, None


def self_test() -> None:
    fixture = """
    Informații de interes
    30 INTERVENȚII ÎN DATA DE 03.09.2026
    5 INCENDII
    22 PRIM AJUTOR
    0 DESCARCERARE
    0 SALVARE
    3 ALTE INTERVENȚII
    """
    parsed = parse_summary(fixture)
    assert parsed is not None
    assert parsed["total"] == 30 and parsed["fires"] == 5 and parsed["first_aid"] == 22 and parsed["other"] == 3
    assert fresh_summary(parsed, today=date(2026, 9, 4)) == (True, "fresh")

    mismatch = fixture.replace("3 ALTE INTERVENȚII", "4 ALTE INTERVENȚII")
    assert parse_summary(mismatch) is None

    future = parse_summary(fixture.replace("03.09.2026", "05.09.2026"))
    assert future is not None
    assert fresh_summary(future, today=date(2026, 9, 4))[1] == "future_summary_date"

    stale = parse_summary(fixture.replace("03.09.2026", "31.08.2026"))
    assert stale is not None
    assert fresh_summary(stale, today=date(2026, 9, 4))[1] == "stale_summary_date"

    now = datetime(2026, 9, 4, 15, 40, tzinfo=TZ)
    story = build_story(parsed, now=now, source_url=SOURCE_URL)
    assert story["id"] == STORY_ID
    assert story["section"] == "URGENȚE"
    assert story["fact_kernel"]["claims"][0]["kind"] == "attributed_statement"
    assert "3 septembrie 2026" in story["headline"]
    doc, changed, duplicate = upsert_fact({"facts": []}, story)
    assert changed and duplicate is None and len(doc["facts"]) == 1
    doc2, changed2, duplicate2 = upsert_fact(doc, story)
    assert not changed2 and duplicate2 is None and doc2 == doc
    print("VÂLCEA CLAR ISU homepage daily-summary kernel self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Promote strict ISU Vâlcea homepage daily intervention summary into Fact Kernel")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    now = datetime.now(TZ).replace(microsecond=0)
    state: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": now.isoformat(timespec="seconds"),
        "source_url": SOURCE_URL,
        "promotion_gate": PROMOTION_GATE,
        "publication_authority": "FACT_KERNEL_INPUT_ONLY_NORMAL_NEWSROOM_GATE_REQUIRED",
        "policy": {
            "single_first_party_source_sufficient_for_low_risk_self_reported_tally": True,
            "category_sum_must_equal_total": True,
            "individual_incidents_independently_verified": False,
            "continuous_story_first": True,
            "source_failure_blocks_unrelated_newsroom": False,
        },
    }
    try:
        visible, final_url = fetch_visible_text()
        summary = parse_summary(visible)
        if summary is None:
            state.update({"status": "HOLD", "reason": "explicit_numeric_summary_not_found"})
        else:
            fresh, reason = fresh_summary(summary, today=now.date())
            state["summary"] = {
                "event_date": summary["event_date"].isoformat(),
                **{key: summary[key] for key in ("total", "fires", "first_aid", "extrication", "rescue", "other")},
            }
            if not fresh:
                state.update({"status": "NO_CHANGE", "reason": reason})
            else:
                story = build_story(summary, now=now, source_url=final_url)
                document = json.loads(FACTS.read_text(encoding="utf-8"))
                updated, changed, duplicate_story_id = upsert_fact(document, story)
                if duplicate_story_id:
                    state.update({
                        "status": "HOLD",
                        "reason": "source_url_already_bound_to_other_story",
                        "duplicate_story_id": duplicate_story_id,
                    })
                elif args.apply and changed:
                    FACTS.write_text(
                        json.dumps(updated, ensure_ascii=False, separators=(",", ":")) + "\n",
                        encoding="utf-8",
                    )
                    state.update({"status": "UPDATED", "changed_story_ids": [STORY_ID]})
                elif changed:
                    state.update({"status": "DRY_RUN", "changed_story_ids": [STORY_ID]})
                else:
                    state.update({"status": "UNCHANGED", "changed_story_ids": []})
    except Exception as exc:
        state.update({"status": "HOLD", "reason": f"source_fetch_or_parse_hold:{type(exc).__name__}:{exc}"})

    if args.apply:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
