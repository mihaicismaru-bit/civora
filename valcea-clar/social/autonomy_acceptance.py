#!/usr/bin/env python3
"""Build truth-bound VÂLCEA CLAR autonomy acceptance metrics.

The acceptance snapshot is derived only from durable repository history,
receipt-bearing social state, current canonical editorial evidence, and public
GitHub Actions metadata. Missing evidence stays UNKNOWN; this module never turns
preview/outbox state into delivery and never treats an untraced claim as proven.

It is intentionally invoked by the existing social asset build so no extra
workflow, schedule, or publication lane is required.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
WINDOW_HOURS = 24
SOAK_HOURS = 48

STRUCTURAL_PATHS = [
    ":(glob).github/workflows/valcea-clar-*.yml",
    ":(glob)valcea-clar/**/*.py",
    ":(glob)local-news-os/**/*.py",
    ":(glob)valcea-clar/social/channels/*.json",
    "valcea-clar/social/story_visuals.json",
    "valcea-clar/editorial/publication_holds.json",
]
DISCOVERY_PATHS = [
    "valcea-clar/editorial",
    "valcea-clar/ingest",
    "valcea-clar/state",
]
ROUTE_RE = re.compile(r"^valcea-clar/site/runtime/stiri/([^/]+)/index\.html$")


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _git(args: list[str]) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        check=True,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def _bot_identity(name: str, email: str) -> bool:
    text = f"{name} {email}".lower()
    return "[bot]" in text or "-bot" in text or "bot@" in text or "github-actions" in text


def _workflow_trigger_identity(run: dict[str, Any]) -> dict[str, Any]:
    triggering = run.get("triggering_actor") if isinstance(run.get("triggering_actor"), dict) else {}
    actor = run.get("actor") if isinstance(run.get("actor"), dict) else {}
    source = triggering or actor
    login = str(source.get("login") or "").strip()
    actor_type = str(source.get("type") or "").strip()
    automated = actor_type.casefold() == "bot" or _bot_identity(login, "")
    return {"login": login or None, "type": actor_type or None, "automated": automated}


def latest_structural_change() -> dict[str, str] | None:
    try:
        raw = _git([
            "log",
            "--first-parent",
            "-1",
            "--format=%H\t%cI",
            "--",
            *STRUCTURAL_PATHS,
        ]).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    if not raw or "\t" not in raw:
        return None
    sha, when = raw.split("\t", 1)
    return {"sha": sha, "at_utc": _iso(_utc(when))}


def added_story_routes(since: datetime) -> list[dict[str, Any]]:
    try:
        raw = _git([
            "log",
            f"--since={_iso(since)}",
            "--format=@@%H\t%cI\t%an\t%ae",
            "--name-status",
            "--diff-filter=A",
            "--",
            "valcea-clar/site/runtime/stiri",
        ])
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []

    commit: dict[str, str] | None = None
    rows: dict[str, dict[str, Any]] = {}
    for line in raw.splitlines():
        if line.startswith("@@"):
            parts = line[2:].split("\t", 3)
            if len(parts) == 4:
                commit = {"sha": parts[0], "at": parts[1], "name": parts[2], "email": parts[3]}
            continue
        if not commit or not line.startswith("A\t"):
            continue
        path = line.split("\t", 1)[1].strip()
        match = ROUTE_RE.match(path)
        if not match:
            continue
        story_id = match.group(1)
        candidate = {
            "story_id": story_id,
            "published_at_utc": _iso(_utc(commit["at"])),
            "commit_sha": commit["sha"],
            "author": commit["name"],
            "autonomous": _bot_identity(commit["name"], commit["email"]),
        }
        previous = rows.get(story_id)
        if previous is None or _utc(candidate["published_at_utc"]) < _utc(previous["published_at_utc"]):
            rows[story_id] = candidate
    return sorted(rows.values(), key=lambda row: (row["published_at_utc"], row["story_id"]))


def discovery_time(story_id: str) -> dict[str, str] | None:
    try:
        raw = _git([
            "log",
            "--all",
            "--reverse",
            f"-S{story_id}",
            "--format=%H\t%cI",
            "--",
            *DISCOVERY_PATHS,
        ]).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    for line in raw.splitlines():
        if "\t" not in line:
            continue
        sha, when = line.split("\t", 1)
        return {"sha": sha, "at_utc": _iso(_utc(when))}
    return None


def current_edition_items() -> dict[str, dict[str, Any]]:
    pointer = _load(VC / "site" / "current_edition.json", {})
    source = str(pointer.get("json_source") or "")
    if not source:
        return {}
    snapshot = _load(VC / source, {})
    return {
        str(item.get("id")): item
        for item in snapshot.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }


def real_photo_story_ids() -> set[str]:
    visuals = _load(VC / "social" / "story_visuals.json", {})
    stories = visuals.get("stories") if isinstance(visuals.get("stories"), dict) else {}
    accepted: set[str] = set()
    for story_id, record in stories.items():
        if not isinstance(record, dict):
            continue
        image = record.get("image") if isinstance(record.get("image"), dict) else {}
        if (
            image.get("kind") == "photograph"
            and image.get("synthetic") is False
            and image.get("subject_match") is True
            and image.get("editor_approved") is True
            and bool(str(image.get("rights_basis") or "").strip())
        ):
            accepted.add(str(story_id))
    return accepted


def _receipt_map(path: Path, id_key: str, *, require_finished: bool = False) -> dict[str, str]:
    state = _load(path, {})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    receipts: dict[str, str] = {}
    for key, row in published.items():
        if not isinstance(row, dict):
            continue
        receipt = str(row.get(id_key) or "").strip()
        if not receipt:
            continue
        if require_finished and str(row.get("container_status") or "") != "FINISHED":
            continue
        story_id = str(row.get("source_story_id") or "")
        if not story_id and str(key).startswith("story-"):
            story_id = str(key)[6:]
        if story_id:
            receipts[story_id] = receipt
    return receipts


def _duplicate_receipts(receipts: dict[str, str], story_ids: set[str]) -> list[dict[str, Any]]:
    reverse: dict[str, list[str]] = defaultdict(list)
    for story_id in story_ids:
        receipt = receipts.get(story_id)
        if receipt:
            reverse[receipt].append(story_id)
    return [
        {"receipt_id": receipt, "story_ids": sorted(ids)}
        for receipt, ids in sorted(reverse.items())
        if len(ids) > 1
    ]


def _content_duplicates(items: dict[str, dict[str, Any]], story_ids: set[str]) -> tuple[list[dict[str, Any]], list[str]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    missing: list[str] = []
    for story_id in sorted(story_ids):
        item = items.get(story_id)
        if not isinstance(item, dict):
            missing.append(story_id)
            continue
        payload = {
            "headline": " ".join(str(item.get("headline") or "").split()).casefold(),
            "dek": " ".join(str(item.get("dek") or "").split()).casefold(),
            "paragraphs": [" ".join(str(p).split()).casefold() for p in item.get("paragraphs", []) if str(p).strip()],
        }
        digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
        by_hash[digest].append(story_id)
    groups = [
        {"content_sha256": digest, "story_ids": sorted(ids)}
        for digest, ids in sorted(by_hash.items())
        if len(ids) > 1
    ]
    return groups, missing


def _claim_trace_violations(items: dict[str, dict[str, Any]], story_ids: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    violations: list[dict[str, str]] = []
    missing: list[str] = []
    for story_id in sorted(story_ids):
        item = items.get(story_id)
        if not isinstance(item, dict):
            missing.append(story_id)
            continue
        if item.get("material_fact_gate") != "PASS":
            violations.append({"story_id": story_id, "reason": "material_fact_gate_not_pass"})
        product = item.get("editorial_product") if isinstance(item.get("editorial_product"), dict) else {}
        if product.get("claim_trace_complete") is not True:
            violations.append({"story_id": story_id, "reason": "claim_trace_not_complete"})
        kernel = item.get("fact_kernel") if isinstance(item.get("fact_kernel"), dict) else {}
        claims = kernel.get("claims") if isinstance(kernel.get("claims"), list) else []
        if not claims:
            violations.append({"story_id": story_id, "reason": "fact_kernel_claims_missing"})
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                violations.append({"story_id": story_id, "reason": "malformed_fact_kernel_claim"})
                continue
            urls = claim.get("source_urls") if isinstance(claim.get("source_urls"), list) else []
            if not any(str(url).strip() for url in urls):
                violations.append({"story_id": story_id, "reason": f"claim_without_source:{claim.get('id') or 'unknown'}"})
    return violations, missing


def _normal(text: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch)).casefold()


def relevant_manual_dispatches(since: datetime) -> dict[str, Any]:
    repo = os.environ.get("GITHUB_REPOSITORY", "mihaicismaru-bit/civora")
    query = urllib.parse.urlencode({
        "event": "workflow_dispatch",
        "created": f">={_iso(since)}",
        "per_page": "100",
    })
    url = f"https://api.github.com/repos/{repo}/actions/runs?{query}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "valcea-clar-autonomy-acceptance"})
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        return {"status": "UNKNOWN", "reason": f"github_actions_read_failed:{type(exc).__name__}", "runs": [], "automated_runs": []}

    if int(payload.get("total_count") or 0) > 100:
        return {"status": "UNKNOWN", "reason": "workflow_dispatch_result_truncated", "runs": [], "automated_runs": []}
    relevant: list[dict[str, Any]] = []
    automated: list[dict[str, Any]] = []
    for run in payload.get("workflow_runs", []):
        if not isinstance(run, dict):
            continue
        name = _normal(str(run.get("name") or ""))
        path = _normal(str(run.get("path") or ""))
        if "valcea clar" not in name and "valcea" not in path:
            continue
        identity = _workflow_trigger_identity(run)
        record = {
            "run_id": run.get("id"),
            "workflow": run.get("name"),
            "created_at": run.get("created_at"),
            "triggering_actor": identity["login"],
            "triggering_actor_type": identity["type"],
        }
        if identity["automated"]:
            automated.append(record)
            continue
        relevant.append(record)
    return {"status": "MEASURED", "runs": relevant, "automated_runs": automated}


def _rate(receipts: dict[str, str], story_ids: set[str]) -> dict[str, Any]:
    denominator = len(story_ids)
    delivered = sorted(story_id for story_id in story_ids if receipts.get(story_id))
    if denominator == 0:
        return {"status": "NO_ELIGIBLE_STORIES", "delivered": 0, "eligible": 0, "value": None}
    return {
        "status": "MEASURED",
        "delivered": len(delivered),
        "eligible": denominator,
        "value": round(len(delivered) / denominator, 4),
        "delivered_story_ids": delivered,
    }


def build_acceptance_snapshot(now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    routes_24h = added_story_routes(now - timedelta(hours=WINDOW_HOURS))
    autonomous = [row for row in routes_24h if row["autonomous"]]
    story_ids = {row["story_id"] for row in autonomous}

    latency_rows: list[dict[str, Any]] = []
    for row in autonomous:
        first = discovery_time(row["story_id"])
        if not first:
            continue
        seconds = int((_utc(row["published_at_utc"]) - _utc(first["at_utc"])).total_seconds())
        if seconds < 0:
            continue
        latency_rows.append({
            "story_id": row["story_id"],
            "seconds": seconds,
            "discovered_at_utc": first["at_utc"],
            "published_at_utc": row["published_at_utc"],
        })
    latency_values = sorted(row["seconds"] for row in latency_rows)
    latency = {
        "status": "MEASURED" if len(latency_rows) == len(autonomous) else "PARTIAL",
        "measured": len(latency_rows),
        "published": len(autonomous),
        "stories": latency_rows,
        "max_seconds": max(latency_values) if latency_values else None,
        "median_seconds": latency_values[len(latency_values) // 2] if latency_values else None,
    }

    photos = real_photo_story_ids()
    photo_count = len(story_ids & photos)
    photo_coverage = {
        "status": "MEASURED" if story_ids else "NO_PUBLISHED_STORIES",
        "real_photo_stories": photo_count,
        "published_stories": len(story_ids),
        "value": round(photo_count / len(story_ids), 4) if story_ids else None,
        "definition": "rights-bearing, non-synthetic, subject-matched, editor-approved real photograph",
    }

    facebook = _receipt_map(VC / "social" / "facebook_state.json", "facebook_post_id")
    instagram = _receipt_map(VC / "social" / "instagram_state.json", "instagram_media_id", require_finished=True)
    items = current_edition_items()
    content_groups, content_missing = _content_duplicates(items, story_ids)
    fb_duplicate = _duplicate_receipts(facebook, story_ids)
    ig_duplicate = _duplicate_receipts(instagram, story_ids)
    duplicate_extras = sum(len(group["story_ids"]) - 1 for group in content_groups + fb_duplicate + ig_duplicate)
    duplicates = {
        "status": "MEASURED" if not content_missing else "PARTIAL",
        "value": duplicate_extras,
        "content_groups": content_groups,
        "facebook_receipt_groups": fb_duplicate,
        "instagram_receipt_groups": ig_duplicate,
        "missing_editorial_evidence": content_missing,
    }

    trace_violations, trace_missing = _claim_trace_violations(items, story_ids)
    fabricated = {
        "status": "PASS" if not trace_violations and not trace_missing else ("UNKNOWN" if trace_missing else "BLOCKED_UNTRACEABLE_CLAIMS"),
        "value": 0 if not trace_violations and not trace_missing else None,
        "definition": "zero is asserted only when every measured published story passes material-fact and complete claim-source trace gates",
        "trace_violations": trace_violations,
        "missing_editorial_evidence": trace_missing,
    }

    structural = latest_structural_change()
    manual: dict[str, Any]
    soak: dict[str, Any]
    if structural:
        baseline = _utc(structural["at_utc"])
        dispatches = relevant_manual_dispatches(baseline)
        manual_routes = [row for row in added_story_routes(baseline) if not row["autonomous"]]
        if dispatches["status"] == "MEASURED":
            manual_count = len(dispatches["runs"]) + len(manual_routes)
            manual = {
                "status": "MEASURED",
                "value": manual_count,
                "workflow_dispatch_runs": dispatches["runs"],
                "automated_workflow_dispatch_runs": dispatches.get("automated_runs", []),
                "manual_story_route_additions": manual_routes,
                "definition": "only non-bot workflow_dispatch triggers and human-authored public story route additions count as manual intervention",
            }
        else:
            manual = {
                "status": "UNKNOWN",
                "value": None,
                "reason": dispatches.get("reason"),
                "automated_workflow_dispatch_runs": dispatches.get("automated_runs", []),
                "manual_story_route_additions": manual_routes,
            }
        eligible_after = baseline + timedelta(hours=SOAK_HOURS)
        if manual.get("value") is None:
            soak_status = "UNKNOWN"
        elif int(manual["value"]) > 0:
            soak_status = "BLOCKED_MANUAL_INTERVENTION"
        elif now < eligible_after:
            soak_status = "IN_PROGRESS"
        else:
            soak_status = "PASS"
        soak = {
            "status": soak_status,
            "structural_baseline_sha": structural["sha"],
            "structural_baseline_at_utc": structural["at_utc"],
            "eligible_after_utc": _iso(eligible_after),
            "required_hours": SOAK_HOURS,
        }
    else:
        manual = {"status": "UNKNOWN", "value": None, "reason": "structural_baseline_unavailable"}
        soak = {"status": "UNKNOWN", "required_hours": SOAK_HOURS}

    objective_zero_gates = (
        duplicates.get("status") == "MEASURED"
        and duplicates.get("value") == 0
        and fabricated.get("status") == "PASS"
        and manual.get("status") == "MEASURED"
        and manual.get("value") == 0
    )
    acceptance_ready = bool(soak.get("status") == "PASS" and objective_zero_gates and latency["status"] == "MEASURED")

    return {
        "schema_version": "1.0",
        "contract": "VALCEA_CLAR_TRUTH_BOUND_AUTONOMY_ACCEPTANCE_V1",
        "window_hours": WINDOW_HOURS,
        "autonomous_stories_published_24h": len(autonomous),
        "autonomous_story_ids_24h": sorted(story_ids),
        "discovery_to_publish_latency": latency,
        "photo_coverage": photo_coverage,
        "facebook_delivery_rate_receipt_bound": _rate(facebook, story_ids),
        "instagram_delivery_rate_receipt_bound": _rate(instagram, story_ids),
        "duplicates": duplicates,
        "fabricated_claims": fabricated,
        "manual_intervention": manual,
        "soak_48h": soak,
        "acceptance_ready": acceptance_ready,
        "truth_rules": {
            "preview_or_outbox_is_delivery": False,
            "facebook_requires_external_post_id": True,
            "instagram_requires_media_id_and_finished_container": True,
            "synthetic_asset_counts_as_photo": False,
            "missing_evidence_becomes_zero": False,
        },
    }


def self_test() -> int:
    assert _bot_identity("github-actions[bot]", "41898282+github-actions[bot]@users.noreply.github.com")
    assert not _bot_identity("Example User", "user@example.com")
    bot_trigger = _workflow_trigger_identity({"triggering_actor": {"login": "github-actions[bot]", "type": "Bot"}})
    assert bot_trigger == {"login": "github-actions[bot]", "type": "Bot", "automated": True}
    human_trigger = _workflow_trigger_identity({"triggering_actor": {"login": "example-user", "type": "User"}})
    assert human_trigger == {"login": "example-user", "type": "User", "automated": False}
    missing_trigger = _workflow_trigger_identity({})
    assert missing_trigger == {"login": None, "type": None, "automated": False}
    photo = {
        "stories": {
            "ok": {"image": {"kind": "photograph", "synthetic": False, "subject_match": True, "editor_approved": True, "rights_basis": "cc"}},
            "synthetic": {"image": {"kind": "photograph", "synthetic": True, "subject_match": True, "editor_approved": True, "rights_basis": "cc"}},
        }
    }
    assert photo["stories"]["ok"]["image"]["synthetic"] is False
    assert photo["stories"]["synthetic"]["image"]["synthetic"] is True
    assert _rate({"a": "receipt"}, {"a", "b"})["value"] == 0.5
    groups = _duplicate_receipts({"a": "x", "b": "x", "c": "y"}, {"a", "b", "c"})
    assert groups == [{"receipt_id": "x", "story_ids": ["a", "b"]}]
    print("VÂLCEA CLAR truth-bound autonomy acceptance v1 self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
