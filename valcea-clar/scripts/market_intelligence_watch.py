#!/usr/bin/env python3
"""VÂLCEA CLAR market-intelligence monitor runner.

Covers three recovered newsroom capabilities:
- construction permits and active real-estate projects;
- public/private/seasonal jobs and labour-market signals;
- Topul Firmelor / ONRC / public-money business signals.

This is a review ledger, not a publisher. A page change, job-board count or company
ranking is never a publishable material fact by itself.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "market_intelligence_registry.json"
OUTPUT = ROOT / "editorial" / "market_intelligence_state.json"
USER_AGENT = "VALCEA-CLAR-Market-Intelligence/1.0 (+https://valceaclar.ro/)"
EXPECTED_MONITORS = {
    "construction-permits-active-projects-watch",
    "jobs-market-valcea-watch",
    "top-firms-onrc-watch",
}


def load(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw).replace("\u00a0", " ")).strip()


def fingerprint_scope(text: str, terms: list[str]) -> tuple[str, int, list[str]]:
    folded = text.casefold()
    windows: list[str] = []
    matched_terms: list[str] = []
    hits = 0
    for raw_term in terms:
        term = str(raw_term).strip()
        key = term.casefold()
        if not key:
            continue
        start = 0
        local_hits = 0
        for _ in range(8):
            idx = folded.find(key, start)
            if idx < 0:
                break
            windows.append(text[max(0, idx - 400): min(len(text), idx + len(term) + 800)])
            hits += 1
            local_hits += 1
            start = idx + max(1, len(key))
        if local_hits:
            matched_terms.append(term)
    scope = " | ".join(windows) if windows else ("__NO_MATCH__" if terms else text[:250_000])
    digest = hashlib.sha256(scope.encode("utf-8", errors="replace")).hexdigest()
    return digest, hits, matched_terms


def numeric_signals(text: str) -> list[dict[str, str]]:
    patterns = [
        ("jobs", r"(?i)\b([0-9][0-9 .]{0,8})\s+(?:joburi|locuri de munc[aă])\b"),
        ("companies", r"(?i)\b([0-9][0-9 .]{0,8})\s+(?:companii|firme|agen[tț]i economici)\b"),
        ("employees", r"(?i)\b([0-9][0-9 .]{0,8})\s+angaja[tț]i\b"),
    ]
    out: list[dict[str, str]] = []
    for kind, pattern in patterns:
        for match in re.finditer(pattern, text[:400_000]):
            value = re.sub(r"\s+", "", match.group(1)).strip(".")
            row = {"kind": kind, "value_text": value}
            if row not in out:
                out.append(row)
            if len(out) >= 12:
                return out
    return out


def probe(binding: dict[str, Any], timeout: int = 14) -> dict[str, Any]:
    base = {
        "id": str(binding.get("id") or ""),
        "publisher": binding.get("publisher"),
        "url": binding.get("url"),
        "source_class": binding.get("source_class"),
        "publication_authority": str(binding.get("source_class") or "").startswith("T1"),
    }
    if binding.get("probe") is not True:
        return {**base, "health": "REGISTERED_NO_PROBE", "change": "NO_CHANGE_SIGNAL", "fingerprint": None, "match_count": None, "matched_terms": [], "numeric_signals": []}
    request = urllib.request.Request(
        str(binding.get("url") or ""),
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,text/plain;q=0.8,*/*;q=0.4",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(1_600_000).decode("utf-8", errors="replace")
            text = clean_text(raw)
            fp, hits, matched = fingerprint_scope(text, [str(x) for x in binding.get("match_terms") or []])
            return {
                **base,
                "reachable": True,
                "http_status": int(response.status),
                "final_url": str(response.geturl()),
                "fingerprint": fp,
                "match_count": hits,
                "matched_terms": matched,
                "numeric_signals": numeric_signals(text),
                "health": "OK",
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {**base, "reachable": False, "http_status": int(exc.code), "fingerprint": None, "match_count": 0, "matched_terms": [], "numeric_signals": [], "health": "UNREACHABLE", "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {**base, "reachable": False, "http_status": None, "fingerprint": None, "match_count": 0, "matched_terms": [], "numeric_signals": [], "health": "UNREACHABLE", "error": f"{type(exc).__name__}: {exc}"}


def previous_source(previous: dict[str, Any], monitor_id: str, source_id: str) -> dict[str, Any]:
    for monitor in previous.get("monitors") or []:
        if monitor.get("id") == monitor_id:
            return next((row for row in monitor.get("sources") or [] if row.get("id") == source_id), {})
    return {}


def add_change(result: dict[str, Any], old: dict[str, Any], live: bool) -> dict[str, Any]:
    if not live:
        if old:
            keep = dict(old)
            keep.update({key: result.get(key) for key in ("id", "publisher", "url", "source_class", "publication_authority")})
            return keep
        result["health"] = "UNPROBED_OFFLINE" if result.get("health") != "REGISTERED_NO_PROBE" else result["health"]
        result["change"] = "NO_BASELINE" if result.get("health") == "UNPROBED_OFFLINE" else result.get("change")
        return result
    if result.get("health") != "OK":
        result["change"] = "PROBE_FAILED" if result.get("health") == "UNREACHABLE" else result.get("change", "NO_CHANGE_SIGNAL")
        return result
    old_fp = old.get("fingerprint")
    new_fp = result.get("fingerprint")
    if old_fp is None:
        change = "NEW_BASELINE"
    elif old_fp != new_fp:
        change = "CHANGED_REVIEW_REQUIRED"
    elif old.get("change") == "CHANGED_REVIEW_REQUIRED":
        change = "CHANGED_REVIEW_REQUIRED"
    else:
        change = "UNCHANGED"
    result["change"] = change
    return result


def validate_registry(doc: dict[str, Any]) -> None:
    assert doc.get("schema_version") == "1.0"
    assert doc.get("instance_id") == "valcea"
    assert doc.get("execution_owner") == "CIVORA_SITE_ENGINE"
    assert doc.get("state_owner") == "GITHUB_REPOSITORY"
    policy = doc.get("policy") or {}
    assert policy.get("monitor_is_not_story") is True
    assert policy.get("public_projection") is False
    assert policy.get("commercial_sources_are_discovery_only") is True
    assert policy.get("paid_dependency_required") is False
    monitors = doc.get("monitors") or []
    ids = {str(row.get("id") or "") for row in monitors}
    assert ids == EXPECTED_MONITORS
    for monitor in monitors:
        assert monitor.get("purpose") and monitor.get("source_bindings")
        source_ids = [str(x.get("id") or "") for x in monitor.get("source_bindings") or []]
        assert len(source_ids) == len(set(source_ids))
        for source in monitor.get("source_bindings") or []:
            assert str(source.get("url") or "").startswith("https://")
            cls = str(source.get("source_class") or "")
            assert cls.startswith("T1") or cls.startswith("T2") or cls.startswith("T3")
        for lead in monitor.get("recovered_leads") or []:
            assert lead.get("public_projection") is False
            assert lead.get("verification_status") and lead.get("recovery_note")
    jobs = next(x for x in monitors if x.get("id") == "jobs-market-valcea-watch")
    job_scope = jobs.get("scope") or {}
    assert job_scope.get("public_sector") is True and job_scope.get("private_sector") is True and job_scope.get("seasonal") is True
    firms = next(x for x in monitors if x.get("id") == "top-firms-onrc-watch")
    assert (firms.get("scope") or {}).get("all_valcea_companies") is True
    assert len(firms.get("priority_entities") or []) >= 10
    construction = next(x for x in monitors if x.get("id") == "construction-permits-active-projects-watch")
    lead_ids = {str(x.get("id")) for x in construction.get("recovered_leads") or []}
    for required in {"ferdinand-19", "doru-popian-2-5-4a", "intrarea-crizantemei-1", "dealul-malului-11g"}:
        assert required in lead_ids


def build(live: bool, previous: dict[str, Any]) -> dict[str, Any]:
    doc = load(REGISTRY, {}) or {}
    validate_registry(doc)
    monitors = doc.get("monitors") or []
    source_jobs: dict[tuple[str, str], dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        future_map = {}
        for monitor in monitors:
            mid = str(monitor.get("id"))
            for binding in monitor.get("source_bindings") or []:
                sid = str(binding.get("id"))
                if live and binding.get("probe") is True:
                    future_map[pool.submit(probe, binding)] = (mid, sid, binding)
                else:
                    source_jobs[(mid, sid)] = add_change(probe({**binding, "probe": False}) if not live else probe(binding), previous_source(previous, mid, sid), live)
        for future in as_completed(future_map):
            mid, sid, _ = future_map[future]
            source_jobs[(mid, sid)] = add_change(future.result(), previous_source(previous, mid, sid), live)

    monitors_out = []
    for monitor in monitors:
        mid = str(monitor.get("id"))
        rows = [source_jobs[(mid, str(binding.get("id")))] for binding in monitor.get("source_bindings") or []]
        changed = [row["id"] for row in rows if row.get("change") == "CHANGED_REVIEW_REQUIRED"]
        degraded = [row["id"] for row in rows if row.get("health") in {"UNREACHABLE", "DEGRADED"}]
        authority_changed = [row["id"] for row in rows if row.get("change") == "CHANGED_REVIEW_REQUIRED" and row.get("publication_authority") is True]
        attention = "REVIEW_REQUIRED" if changed else ("SOURCE_DEGRADED" if degraded else "NORMAL")
        monitors_out.append({
            "id": mid,
            "label": monitor.get("label"),
            "registry_status": monitor.get("status"),
            "attention": attention,
            "changed_sources": changed,
            "official_changed_sources": authority_changed,
            "degraded_sources": degraded,
            "sources": rows,
            "lead_ids": [lead.get("id") for lead in monitor.get("recovered_leads") or []],
            "priority_entities": monitor.get("priority_entities") or [],
            "scope": monitor.get("scope") or {},
            "public_projection": False,
        })

    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR market intelligence state",
        "execution_owner": "CIVORA_SITE_ENGINE",
        "state_owner": "GITHUB_REPOSITORY",
        "generated_at": utc_now(),
        "mode": "LIVE_SOURCE_HEALTH" if live else "OFFLINE_MATERIALIZATION",
        "monitor_count": len(monitors_out),
        "monitors": monitors_out,
        "publication_contract": {
            "monitor_signal_may_publish_directly": False,
            "commercial_source_may_confirm_material_fact_alone": False,
            "normal_story_ready_gate_required": True,
            "public_projection": False,
        },
    }


def semantic(state: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(state, ensure_ascii=False))
    clone.pop("generated_at", None)
    return clone


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    previous = load(OUTPUT, {}) or {}
    state = build(args.live, previous)
    if args.check:
        assert state.get("monitor_count") == 3
        assert all(row.get("public_projection") is False for row in state.get("monitors") or [])
        assert (state.get("publication_contract") or {}).get("commercial_source_may_confirm_material_fact_alone") is False
        print("VÂLCEA CLAR market intelligence: PASS (construction + jobs + firms; fail-closed)")
        return 0
    if previous and semantic(previous) == semantic(state):
        print("VÂLCEA CLAR market intelligence: NO_SEMANTIC_CHANGE")
        return 0
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"VÂLCEA CLAR market intelligence: UPDATED ({state['monitor_count']} monitors; {state['mode']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
