#!/usr/bin/env python3
"""Autonomous VÂLCEA CLAR infrastructure watch for A1 connectivity.

The monitor observes official-source change signals for the road projects that
control Vâlcea's connection to A1. It is deliberately fail-closed: a source
change is a review signal only and never a publishable fact.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "infrastructure_monitor_registry.json"
OUTPUT = ROOT / "editorial" / "infrastructure_monitor_state.json"
USER_AGENT = "VALCEA-CLAR-Infrastructure-Watch/1.0 (+https://valceaclar.ro/)"


def load(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def text_only(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw).replace("\u00a0", " ")).strip()


def scoped_fingerprint(text: str, terms: list[str]) -> tuple[str, int]:
    folded = text.casefold()
    windows: list[str] = []
    hits = 0
    for raw in terms:
        term = str(raw).strip().casefold()
        if not term:
            continue
        start = 0
        for _ in range(10):
            idx = folded.find(term, start)
            if idx < 0:
                break
            windows.append(text[max(0, idx - 500): min(len(text), idx + len(term) + 1000)])
            hits += 1
            start = idx + max(1, len(term))
    scope = " | ".join(windows) if windows else "__NO_MATCH__"
    return hashlib.sha256(scope.encode("utf-8", errors="replace")).hexdigest(), hits


def fetch(url: str, terms: list[str], timeout: int = 20) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
        "Cache-Control": "no-cache",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            fp, hits = scoped_fingerprint(text_only(raw), terms)
            return {
                "reachable": True,
                "http_status": int(response.status),
                "final_url": str(response.geturl()),
                "fingerprint": fp,
                "match_count": hits,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {"reachable": False, "http_status": int(exc.code), "fingerprint": None, "match_count": 0, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"reachable": False, "http_status": None, "fingerprint": None, "match_count": 0, "error": f"{type(exc).__name__}: {exc}"}


def prior_source(previous: dict[str, Any], sid: str) -> dict[str, Any]:
    return next((row for row in previous.get("sources") or [] if row.get("id") == sid), {})


def build(live: bool, previous: dict[str, Any]) -> dict[str, Any]:
    doc = load(REGISTRY, {}) or {}
    monitors = doc.get("monitors") or []
    if len(monitors) != 1 or monitors[0].get("id") != "a1-valcea-connectivity-watch":
        raise SystemExit("invalid infrastructure monitor registry")
    monitor = monitors[0]
    sources = []
    for binding in monitor.get("source_bindings") or []:
        sid = str(binding.get("id") or "")
        base = {
            "id": sid,
            "publisher": binding.get("publisher"),
            "url": binding.get("url"),
            "tier": binding.get("tier"),
        }
        if not binding.get("probe"):
            sources.append({**base, "health": "REGISTERED_NO_PROBE", "change": "NO_CHANGE_SIGNAL"})
            continue
        old = prior_source(previous, sid)
        if not live:
            sources.append({**old, **base} if old else {**base, "health": "UNPROBED_OFFLINE", "change": "NO_BASELINE", "fingerprint": None, "match_count": None})
            continue
        result = fetch(str(binding.get("url")), [str(x) for x in binding.get("match_terms") or []])
        if not result["reachable"]:
            sources.append({**base, **result, "health": "UNREACHABLE", "change": "PROBE_FAILED"})
            continue
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
        sources.append({**base, **result, "health": "OK", "change": change})

    changed = [row["id"] for row in sources if row.get("change") == "CHANGED_REVIEW_REQUIRED"]
    degraded = [row["id"] for row in sources if row.get("health") in {"UNREACHABLE", "DEGRADED"}]
    leads = monitor.get("recovered_leads") or []
    state = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "monitor_id": monitor.get("id"),
        "label": monitor.get("label"),
        "generated_at": now_iso(),
        "mode": "LIVE_SOURCE_HEALTH" if live else "OFFLINE_MATERIALIZATION",
        "registry_status": monitor.get("status"),
        "attention": "REVIEW_REQUIRED" if changed else ("SOURCE_DEGRADED" if degraded else "NORMAL"),
        "changed_sources": changed,
        "degraded_sources": degraded,
        "sources": sources,
        "subprojects": [
            {
                "id": lead.get("id"),
                "label": lead.get("label"),
                "verification_status": lead.get("verification_status"),
                "public_projection": False,
            }
            for lead in leads
        ],
        "publication_contract": {
            "monitor_is_not_story": True,
            "source_change_is_not_material_fact": True,
            "public_projection": False,
            "normal_story_ready_gate_required": True,
        },
    }
    return state


def semantic(state: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(state, ensure_ascii=False))
    clone.pop("generated_at", None)
    return clone


def validate_registry() -> None:
    doc = load(REGISTRY, {}) or {}
    assert doc.get("instance_id") == "valcea"
    assert doc.get("execution_owner") == "CIVORA_SITE_ENGINE"
    assert doc.get("state_owner") == "GITHUB_REPOSITORY"
    assert (doc.get("policy") or {}).get("public_projection") is False
    monitors = doc.get("monitors") or []
    assert len(monitors) == 1
    monitor = monitors[0]
    assert monitor.get("id") == "a1-valcea-connectivity-watch"
    ids = {str(x.get("id")) for x in monitor.get("recovered_leads") or []}
    expected = {
        "a1-section-2-boita-cornetu",
        "a1-section-3-cornetu-tigveni",
        "a1-section-4-tigveni-curtea-de-arges",
        "dn73c-tigveni-ramnicu-valcea",
        "ganesa-ramnicu-valcea-tigveni-corridor",
    }
    assert ids == expected
    assert all(x.get("public_projection") is False for x in monitor.get("recovered_leads") or [])
    assert monitor.get("source_bindings")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    validate_registry()
    previous = load(OUTPUT, {}) or {}
    state = build(args.live, previous)
    if args.check:
        assert len(state.get("subprojects") or []) == 5
        assert (state.get("publication_contract") or {}).get("public_projection") is False
        print("VÂLCEA CLAR A1 connectivity watch: PASS (5 subprojects; fail-closed)")
        return 0
    if previous and semantic(previous) == semantic(state):
        print("VÂLCEA CLAR A1 connectivity watch: NO_SEMANTIC_CHANGE")
        return 0
    OUTPUT.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"VÂLCEA CLAR A1 connectivity watch: UPDATED ({state['attention']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
