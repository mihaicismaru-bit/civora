#!/usr/bin/env python3
"""Materialize durable VÂLCEA CLAR monitor health.

Signals are review inputs only. They never bypass normal story_ready verification,
never publish directly, and never disappear because an edition or homepage turns over.
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
REPO_ROOT = ROOT.parent
REGISTRY = ROOT / "editorial" / "monitor_registry.json"
NEWS = ROOT / "editorial" / "news_sources.json"
MANUAL = ROOT / "editorial" / "manual_watch_sources.json"
DISCOVERY = ROOT / "editorial" / "news_discovery_state.json"
DEFAULT_OUTPUT = ROOT / "editorial" / "monitor_state.json"
USER_AGENT = "VALCEA-CLAR-Monitor-Ledger/1.0 (+https://valceaclar.ro/)"


def load(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def utc_now() -> str:
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
    for raw_term in terms:
        term = raw_term.strip().casefold()
        if not term:
            continue
        start = 0
        for _ in range(8):
            idx = folded.find(term, start)
            if idx < 0:
                break
            windows.append(text[max(0, idx - 350): min(len(text), idx + len(term) + 700)])
            hits += 1
            start = idx + max(1, len(term))
    scope = " | ".join(windows) if windows else ("__NO_MATCH__" if terms else text[:250_000])
    return hashlib.sha256(scope.encode("utf-8", errors="replace")).hexdigest(), hits


def probe(url: str, terms: list[str], timeout: int = 18) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(2_000_000).decode("utf-8", errors="replace")
            fingerprint, hits = scoped_fingerprint(text_only(raw), terms)
            return {
                "reachable": True,
                "http_status": int(response.status),
                "final_url": str(response.geturl()),
                "fingerprint": fingerprint,
                "match_count": hits,
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {"reachable": False, "http_status": int(exc.code), "fingerprint": None, "match_count": 0, "error": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"reachable": False, "http_status": None, "fingerprint": None, "match_count": 0, "error": f"{type(exc).__name__}: {exc}"}


def prior_source(previous: dict[str, Any], monitor_id: str, source_id: str) -> dict[str, Any] | None:
    for monitor in previous.get("monitors") or []:
        if monitor.get("id") == monitor_id:
            return next((row for row in monitor.get("sources") or [] if row.get("id") == source_id), None)
    return None


def semantic(state: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(state, ensure_ascii=False))
    clone.pop("generated_at", None)
    clone.pop("last_live_probe_at", None)
    return clone


def direct_source(binding: dict[str, Any], previous: dict[str, Any], monitor_id: str, live: bool) -> dict[str, Any]:
    sid = str(binding["id"])
    old = prior_source(previous, monitor_id, sid) or {}
    base = {
        "id": sid,
        "ref_type": "url",
        "url": binding.get("url"),
        "publisher": binding.get("publisher"),
        "tier": binding.get("tier"),
    }
    if not binding.get("probe"):
        return {**base, "health": "REGISTERED_NO_PROBE", "change": "NO_CHANGE_SIGNAL"}
    if not live:
        return {**old, **base} if old else {**base, "health": "UNPROBED_OFFLINE", "change": "NO_BASELINE", "fingerprint": None, "match_count": None}

    result = probe(str(binding.get("url")), [str(term) for term in binding.get("match_terms") or []])
    if not result["reachable"]:
        return {**base, **result, "health": "UNREACHABLE", "change": "PROBE_FAILED"}

    old_fp = old.get("fingerprint")
    new_fp = result.get("fingerprint")
    if old_fp is None:
        change = "NEW_BASELINE"
    elif old_fp != new_fp:
        change = "CHANGED_REVIEW_REQUIRED"
    elif old.get("change") == "CHANGED_REVIEW_REQUIRED":
        # A detected change remains actionable until a future explicit review/ack
        # contract clears it. Repeated identical probes must not silently erase it.
        change = "CHANGED_REVIEW_REQUIRED"
    else:
        change = "UNCHANGED"
    return {**base, **result, "health": "OK", "change": change}


def build(live: bool, previous: dict[str, Any]) -> dict[str, Any]:
    registry = load(REGISTRY, {}) or {}
    news = {str(row.get("id")): row for row in (load(NEWS, {}) or {}).get("sources") or []}
    manual = {str(row.get("id")): row for row in (load(MANUAL, {}) or {}).get("sources") or []}
    discovery_doc = load(DISCOVERY, {}) or {}
    discovery = {str(row.get("source_id")): row for row in discovery_doc.get("sources") or []}

    monitors_out: list[dict[str, Any]] = []
    for monitor in registry.get("monitors") or []:
        mid = str(monitor["id"])
        sources: list[dict[str, Any]] = []
        for binding in monitor.get("source_bindings") or []:
            sid = str(binding.get("id") or "")
            ref_type = binding.get("ref_type")
            if ref_type == "news_source_id":
                health = discovery.get(sid)
                sources.append({
                    "id": sid,
                    "ref_type": ref_type,
                    "registered": sid in news,
                    "health": "OK" if health and health.get("listing_ok") else ("DEGRADED" if health else "UNKNOWN_NO_DISCOVERY_STATE"),
                    "change": "NO_CHANGE_SIGNAL",
                    "facts": int((health or {}).get("facts") or 0),
                    "links_examined": (health or {}).get("links_examined"),
                    "article_failures": (health or {}).get("article_failures"),
                    "error": (health or {}).get("error"),
                })
            elif ref_type == "manual_watch_source_id":
                row = manual.get(sid)
                sources.append({
                    "id": sid,
                    "ref_type": ref_type,
                    "health": "MANUAL_WATCH" if row else "MISSING_SOURCE_BINDING",
                    "change": "NO_CHANGE_SIGNAL",
                    "source_status": (row or {}).get("status"),
                    "checked_at": (row or {}).get("checked_at"),
                    "url": (row or {}).get("url"),
                })
            elif ref_type == "investigation_file":
                rel = str(binding.get("path") or "")
                sources.append({
                    "id": sid,
                    "ref_type": ref_type,
                    "health": "PRESENT" if (REPO_ROOT / rel).is_file() else "MISSING",
                    "change": "NO_CHANGE_SIGNAL",
                    "path": rel,
                })
            elif ref_type == "url":
                sources.append(direct_source(binding, previous, mid, live))
            else:
                sources.append({"id": sid, "ref_type": str(ref_type), "health": "INVALID_BINDING", "change": "NO_CHANGE_SIGNAL"})

        changed = [row["id"] for row in sources if row.get("change") == "CHANGED_REVIEW_REQUIRED"]
        degraded = [row["id"] for row in sources if row.get("health") in {"DEGRADED", "UNREACHABLE", "MISSING", "MISSING_SOURCE_BINDING", "INVALID_BINDING"}]
        reverify = [lead["id"] for lead in monitor.get("recovered_leads") or [] if "REVERIFY" in str(lead.get("verification_status") or "")]
        attention = "REVIEW_REQUIRED" if changed or reverify else ("SOURCE_DEGRADED" if degraded else "NORMAL")
        monitors_out.append({
            "id": mid,
            "label": monitor.get("label"),
            "registry_status": monitor.get("status"),
            "attention": attention,
            "changed_sources": changed,
            "degraded_sources": degraded,
            "reverify_leads": reverify,
            "sources": sources,
            "lead_ids": [lead.get("id") for lead in monitor.get("recovered_leads") or []],
            "public_projection": False,
        })

    now = utc_now()
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR durable monitor state",
        "execution_owner": "CIVORA_SITE_ENGINE",
        "state_owner": "GITHUB_REPOSITORY",
        "generated_at": now,
        "last_live_probe_at": now if live else previous.get("last_live_probe_at"),
        "mode": "LIVE_SOURCE_HEALTH" if live else "OFFLINE_MATERIALIZATION",
        "discovery_observed_at": discovery_doc.get("observed_at"),
        "monitor_count": len(monitors_out),
        "monitors": monitors_out,
        "publication_contract": {
            "source_change_is_not_story": True,
            "monitor_signal_may_publish_directly": False,
            "normal_story_ready_gate_required": True,
            "edition_expiry_may_delete_monitor": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    output = Path(args.output)
    previous = load(output, {}) or {}
    state = build(args.live, previous)

    if args.check:
        if state.get("monitor_count") != 7:
            raise SystemExit(f"expected 7 recovered monitors, found {state.get('monitor_count')}")
        if any(row.get("public_projection") is not False for row in state.get("monitors") or []):
            raise SystemExit("monitor ledger attempted public projection")
        print("VÂLCEA CLAR monitor ledger offline contract: PASS")
        return 0

    if previous and semantic(previous) == semantic(state):
        print("VÂLCEA CLAR monitor ledger: NO_SEMANTIC_CHANGE")
        return 0

    output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"VÂLCEA CLAR monitor ledger: UPDATED ({state['monitor_count']} monitors; mode={state['mode']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
