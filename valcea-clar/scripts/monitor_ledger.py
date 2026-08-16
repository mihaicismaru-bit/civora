#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR monitor health without turning signals into news.

The ledger is intentionally conservative:
- existing automatic news sources reuse the newsroom discovery-health ledger;
- manual-watch sources remain manual and are never auto-promoted;
- explicit monitor URLs may be probed for a bounded text fingerprint;
- a page change is only a review signal, never a factual assertion or publication event;
- recovered leads survive indefinitely until an explicit terminal state is committed.
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
REGISTRY_PATH = ROOT / "editorial" / "monitor_registry.json"
NEWS_SOURCES_PATH = ROOT / "editorial" / "news_sources.json"
MANUAL_SOURCES_PATH = ROOT / "editorial" / "manual_watch_sources.json"
DISCOVERY_STATE_PATH = ROOT / "editorial" / "news_discovery_state.json"
DEFAULT_STATE_PATH = ROOT / "editorial" / "monitor_state.json"
USER_AGENT = "VALCEA-CLAR-Monitor-Ledger/1.0 (+https://valceaclar.ro/)"
MAX_BODY = 2_000_000


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_text(raw: str) -> str:
    raw = re.sub(r"(?is)<script\b[^>]*>.*?</script>", " ", raw)
    raw = re.sub(r"(?is)<style\b[^>]*>.*?</style>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    raw = raw.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", raw).strip()


def fingerprint_scope(text: str, terms: list[str]) -> tuple[str, int]:
    folded = text.casefold()
    parts: list[str] = []
    matches = 0
    for term in terms:
        needle = str(term).strip().casefold()
        if not needle:
            continue
        start = 0
        per_term = 0
        while per_term < 8:
            idx = folded.find(needle, start)
            if idx < 0:
                break
            left = max(0, idx - 350)
            right = min(len(text), idx + len(needle) + 700)
            parts.append(text[left:right])
            matches += 1
            per_term += 1
            start = idx + max(1, len(needle))
    if terms:
        scope = " | ".join(parts) if parts else "__NO_MATCH__"
    else:
        scope = text[:250_000]
    digest = hashlib.sha256(scope.encode("utf-8", errors="replace")).hexdigest()
    return digest, matches


def fetch_probe(url: str, terms: list[str], timeout: int = 18) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
            "Cache-Control": "no-cache",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(MAX_BODY).decode("utf-8", errors="replace")
            text = normalize_text(body)
            fingerprint, matches = fingerprint_scope(text, terms)
            return {
                "reachable": True,
                "http_status": int(response.status),
                "final_url": str(response.geturl()),
                "fingerprint": fingerprint,
                "match_count": matches,
                "bytes_read": min(len(body.encode("utf-8", errors="replace")), MAX_BODY),
                "error": None,
            }
    except urllib.error.HTTPError as exc:
        return {
            "reachable": False,
            "http_status": int(exc.code),
            "final_url": url,
            "fingerprint": None,
            "match_count": 0,
            "bytes_read": 0,
            "error": f"HTTP {exc.code}",
        }
    except Exception as exc:
        return {
            "reachable": False,
            "http_status": None,
            "final_url": url,
            "fingerprint": None,
            "match_count": 0,
            "bytes_read": 0,
            "error": f"{type(exc).__name__}: {exc}",
        }


def prior_source(previous: dict[str, Any], monitor_id: str, source_id: str) -> dict[str, Any] | None:
    for monitor in previous.get("monitors") or []:
        if monitor.get("id") != monitor_id:
            continue
        for source in monitor.get("sources") or []:
            if source.get("id") == source_id:
                return source
    return None


def source_from_discovery(binding: dict[str, Any], discovery_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sid = str(binding["id"])
    row = discovery_by_id.get(sid)
    if row is None:
        return {
            "id": sid,
            "ref_type": "news_source_id",
            "health": "UNKNOWN_NO_DISCOVERY_STATE",
            "change": "NO_CHANGE_SIGNAL",
            "facts": 0,
        }
    ok = bool(row.get("listing_ok"))
    return {
        "id": sid,
        "ref_type": "news_source_id",
        "health": "OK" if ok else "DEGRADED",
        "change": "NO_CHANGE_SIGNAL",
        "facts": int(row.get("facts") or 0),
        "links_examined": row.get("links_examined"),
        "article_failures": row.get("article_failures"),
        "error": row.get("error"),
    }


def source_from_manual(binding: dict[str, Any], manual_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sid = str(binding["id"])
    row = manual_by_id.get(sid)
    if row is None:
        return {
            "id": sid,
            "ref_type": "manual_watch_source_id",
            "health": "MISSING_SOURCE_BINDING",
            "change": "NO_CHANGE_SIGNAL",
        }
    return {
        "id": sid,
        "ref_type": "manual_watch_source_id",
        "health": "MANUAL_WATCH",
        "change": "NO_CHANGE_SIGNAL",
        "source_status": row.get("status"),
        "checked_at": row.get("checked_at"),
        "url": row.get("url"),
    }


def source_from_investigation(binding: dict[str, Any]) -> dict[str, Any]:
    rel = str(binding.get("path") or "")
    path = REPO_ROOT / rel
    return {
        "id": str(binding["id"]),
        "ref_type": "investigation_file",
        "health": "PRESENT" if path.is_file() else "MISSING",
        "change": "NO_CHANGE_SIGNAL",
        "path": rel,
    }


def direct_source(
    binding: dict[str, Any],
    previous: dict[str, Any],
    monitor_id: str,
    live: bool,
) -> dict[str, Any]:
    sid = str(binding["id"])
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
        old = prior_source(previous, monitor_id, sid)
        if old and old.get("fingerprint"):
            return {**old, **base, "health": old.get("health", "OFFLINE_PRESERVED"), "change": "OFFLINE_PRESERVED"}
        return {**base, "health": "UNPROBED_OFFLINE", "change": "NO_BASELINE", "fingerprint": None, "match_count": None}

    result = fetch_probe(str(binding.get("url")), [str(x) for x in binding.get("match_terms") or []])
    old = prior_source(previous, monitor_id, sid)
    old_fp = (old or {}).get("fingerprint")
    new_fp = result.get("fingerprint")
    if not result["reachable"]:
        change = "PROBE_FAILED"
        health = "UNREACHABLE"
    elif old_fp is None:
        change = "NEW_BASELINE"
        health = "OK"
    elif old_fp != new_fp:
        change = "CHANGED_REVIEW_REQUIRED"
        health = "OK"
    else:
        change = "UNCHANGED"
        health = "OK"
    return {**base, **result, "health": health, "change": change}


def semantic_state(state: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(state, ensure_ascii=False))
    clone.pop("generated_at", None)
    clone.pop("last_live_probe_at", None)
    for monitor in clone.get("monitors") or []:
        for source in monitor.get("sources") or []:
            source.pop("bytes_read", None)
    return clone


def build(live: bool, previous: dict[str, Any]) -> dict[str, Any]:
    registry = load(REGISTRY_PATH, {})
    news = load(NEWS_SOURCES_PATH, {})
    manual = load(MANUAL_SOURCES_PATH, {})
    discovery = load(DISCOVERY_STATE_PATH, {})
    news_by_id = {str(row.get("id")): row for row in news.get("sources") or []}
    manual_by_id = {str(row.get("id")): row for row in manual.get("sources") or []}
    discovery_by_id = {str(row.get("source_id")): row for row in discovery.get("sources") or []}

    monitors_out: list[dict[str, Any]] = []
    for monitor in registry.get("monitors") or []:
        mid = str(monitor["id"])
        source_rows: list[dict[str, Any]] = []
        for binding in monitor.get("source_bindings") or []:
            btype = binding.get("ref_type")
            sid = str(binding.get("id") or "")
            if btype == "news_source_id":
                # Validation guarantees the registry reference exists. Keep publisher URL out of the
                # state unless needed; discovery health is the authoritative operational signal.
                row = source_from_discovery(binding, discovery_by_id)
                row["registered"] = sid in news_by_id
            elif btype == "manual_watch_source_id":
                row = source_from_manual(binding, manual_by_id)
            elif btype == "investigation_file":
                row = source_from_investigation(binding)
            elif btype == "url":
                row = direct_source(binding, previous, mid, live)
            else:
                row = {"id": sid, "ref_type": str(btype), "health": "INVALID_BINDING", "change": "NO_CHANGE_SIGNAL"}
            source_rows.append(row)

        changed_sources = [row["id"] for row in source_rows if row.get("change") == "CHANGED_REVIEW_REQUIRED"]
        degraded_sources = [
            row["id"]
            for row in source_rows
            if row.get("health") in {"DEGRADED", "UNREACHABLE", "MISSING", "MISSING_SOURCE_BINDING", "INVALID_BINDING"}
        ]
        reverify_leads = [
            lead["id"]
            for lead in monitor.get("recovered_leads") or []
            if "REVERIFY" in str(lead.get("verification_status") or "")
        ]
        attention = "REVIEW_REQUIRED" if changed_sources or reverify_leads else ("SOURCE_DEGRADED" if degraded_sources else "NORMAL")
        monitors_out.append(
            {
                "id": mid,
                "label": monitor.get("label"),
                "registry_status": monitor.get("status"),
                "attention": attention,
                "changed_sources": changed_sources,
                "degraded_sources": degraded_sources,
                "reverify_leads": reverify_leads,
                "sources": source_rows,
                "lead_ids": [lead.get("id") for lead in monitor.get("recovered_leads") or []],
                "public_projection": False,
            }
        )

    state = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR durable monitor state",
        "execution_owner": "CIVORA_SITE_ENGINE",
        "state_owner": "GITHUB_REPOSITORY",
        "generated_at": now_iso(),
        "last_live_probe_at": now_iso() if live else previous.get("last_live_probe_at"),
        "mode": "LIVE_SOURCE_HEALTH" if live else "OFFLINE_MATERIALIZATION",
        "discovery_observed_at": discovery.get("observed_at"),
        "monitor_count": len(monitors_out),
        "monitors": monitors_out,
        "publication_contract": {
            "source_change_is_not_story": True,
            "monitor_signal_may_publish_directly": False,
            "normal_story_ready_gate_required": True,
            "edition_expiry_may_delete_monitor": False,
        },
    }
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Probe direct monitor URLs. Default is offline/fail-closed.")
    parser.add_argument("--output", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--check", action="store_true", help="Validate materialization without writing state.")
    args = parser.parse_args()

    output = Path(args.output)
    previous = load(output, {}) or {}
    state = build(args.live, previous)

    if previous and semantic_state(previous) == semantic_state(state):
        state = previous
        print("VÂLCEA CLAR monitor ledger: NO_SEMANTIC_CHANGE")
    else:
        print(
            "VÂLCEA CLAR monitor ledger: UPDATED "
            f"({state['monitor_count']} monitors; mode={state['mode']})"
        )

    if args.check:
        if state.get("monitor_count", 0) < 7:
            raise SystemExit("monitor ledger lost required recovered monitors")
        if any(row.get("public_projection") is not False for row in state.get("monitors") or []):
            raise SystemExit("monitor ledger attempted public projection")
        return 0

    output.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
