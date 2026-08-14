from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

from common import fetch, focused_text_from_html, rss_entries, sha256_text, utcnow, USER_AGENT


def inspect_source(source: dict[str, Any], timeout: float, offline: bool) -> dict[str, Any]:
    observed = utcnow()
    base = {"id": source["id"], "label": source["label"], "tier": source["tier"], "url": source["url"], "observed_at": observed}
    if offline:
        return {**base, "health": "SKIPPED_OFFLINE"}
    try:
        body, headers, final_url, status = fetch(source["url"], timeout)
        content_type = headers.get("content-type", "")
        if status >= 400:
            raise RuntimeError(f"HTTP {status}")
        if source["mode"] == "rss" or "xml" in content_type or body.lstrip().startswith(b"<?xml"):
            extracted = rss_entries(body, source.get("focus_terms", []))
        else:
            extracted = focused_text_from_html(body, source.get("focus_terms", []))
        focused_text = extracted.pop("focused_text")
        return {
            **base,
            "final_url": final_url,
            "health": "OK",
            "http_status": status,
            "content_type": content_type,
            "semantic_sha256": sha256_text(focused_text),
            "focused_text_empty": not bool(focused_text),
            **extracted,
        }
    except Exception as exc:
        return {**base, "health": "FAILED", "error": f"{type(exc).__name__}: {exc}"}


def compare_source(source: dict[str, Any], current: dict[str, Any], previous: dict[str, Any] | None, failure_threshold: int, baseline: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    events: list[dict[str, Any]] = []
    merged = {**current, "materiality": source.get("materiality", "medium"), "mode": source["mode"]}
    previous_failures = int((previous or {}).get("consecutive_failures", 0))
    if current["health"] == "OK":
        merged["consecutive_failures"] = 0
        merged["last_successful_at"] = current["observed_at"]
        if previous and previous.get("health") == "FAILED" and previous_failures >= failure_threshold and not baseline:
            events.append(_event("SOURCE_RECOVERED", source, f"Sursa a revenit după {previous_failures} eșecuri consecutive."))
        previous_hash = (previous or {}).get("semantic_sha256")
        current_hash = current.get("semantic_sha256")
        if previous_hash and current_hash and previous_hash != current_hash and not baseline:
            old_entries = {item.get("fingerprint") for item in (previous or {}).get("entries", [])}
            new_entries = [item for item in current.get("entries", []) if item.get("fingerprint") not in old_entries]
            if source["mode"] != "rss" or new_entries:
                event = _event(
                    "MATERIAL_CHANGE",
                    source,
                    f"Au apărut {len(new_entries)} elemente noi în radar." if new_entries else "Fragmentul relevant al sursei s-a modificat.",
                )
                event["new_entries"] = new_entries[:8]
                event["excerpt"] = current.get("focused_excerpt", [])[:8]
                events.append(event)
    elif current["health"] == "FAILED":
        failures = previous_failures + 1
        merged["consecutive_failures"] = failures
        if previous:
            for key in ("semantic_sha256", "last_successful_at", "focused_excerpt", "entries", "match_count", "link_hits", "final_url", "content_type", "http_status"):
                if key in previous:
                    merged[key] = previous[key]
        if failures == failure_threshold and not baseline:
            event = _event("SOURCE_FAILURE_THRESHOLD", source, f"Sursa nu a putut fi verificată în {failures} rulări consecutive.")
            event["error"] = current.get("error")
            events.append(event)
    else:
        merged["consecutive_failures"] = previous_failures
        if previous:
            for key, value in previous.items():
                merged.setdefault(key, value)
    return merged, events


def _event(event_type: str, source: dict[str, Any], summary: str) -> dict[str, Any]:
    return {
        "type": event_type,
        "source_id": source["id"],
        "label": source["label"],
        "url": source["url"],
        "materiality": source.get("materiality", "medium"),
        "summary": summary,
    }


def event_fingerprint(events: list[dict[str, Any]]) -> str:
    compact = [{
        "type": event.get("type"),
        "source_id": event.get("source_id"),
        "summary": event.get("summary"),
        "new_entries": [item.get("fingerprint") for item in event.get("new_entries", [])],
    } for event in events]
    return sha256_text(json.dumps(compact, sort_keys=True, ensure_ascii=False))


def render_comment(watchlist: dict[str, Any], events: list[dict[str, Any]], observed_at: str) -> str:
    limit = int(watchlist["alert_policy"].get("maximum_comment_items", 12))
    lines = [
        f"## Monitor automat — {watchlist['case_id']}", "",
        f"**Rutare:** {watchlist['editorial_route']['primary_section']} → {watchlist['editorial_route']['desk']}",
        f"**Verificare:** {observed_at}",
        "**Statut:** `NEEDS_EDITORIAL_REVIEW — NO AUTO-PUBLICATION`", "",
    ]
    icons = {"MATERIAL_CHANGE": "🔎", "SOURCE_FAILURE_THRESHOLD": "⚠️", "SOURCE_RECOVERED": "✅"}
    for event in events[:limit]:
        lines += [f"### {icons.get(event['type'], '•')} {event['label']}", event["summary"], f"Sursă: {event['url']}"]
        for item in event.get("new_entries", [])[:5]:
            title = item.get("title") or "Element nou"
            link = item.get("link") or event["url"]
            published = f" — {item['published']}" if item.get("published") else ""
            lines.append(f"- [{title}]({link}){published}")
        if not event.get("new_entries") and event.get("excerpt"):
            lines.append("Fragmente relevante detectate:")
            lines += [f"- {excerpt[:350]}" for excerpt in event["excerpt"][:5]]
        if event.get("error"):
            lines.append(f"Eroare tehnică: `{event['error'][:500]}`")
        lines.append("")
    lines += [
        "### Gate editorial",
        "Schimbarea este doar un semnal. Verificarea umană trebuie să stabilească dacă privește contractul, executantul efectiv, avizele, calendarul, plățile sau calitatea lucrărilor. Sursele T3 nu pot susține singure o afirmație factuală.",
    ]
    return "\n".join(lines)


def post_issue_comment(issue_number: int, body: str) -> None:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN/GITHUB_REPOSITORY lipsesc")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/issues/{issue_number}/comments",
        data=json.dumps({"body": body}, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=25) as response:
        if int(getattr(response, "status", 201)) >= 300:
            raise RuntimeError(f"GitHub comment failed: {response.status}")
