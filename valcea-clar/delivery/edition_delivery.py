#!/usr/bin/env python3
"""VÂLCEA CLAR S1 — durable edition delivery ledger.

This layer does not publish content. It reconciles one canonical edition package
with the public site and channel adapters, producing:
  * manifest.json — exact article/version/channel selection for the edition
  * queue.json    — durable delivery records keyed by version
  * report.json   — current edition delivery status and explicit blockers

The key safety property is monotonic confirmation: a confirmed delivery is never
downgraded or erased merely because a later adapter run lacks that confirmation.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.1"
DELIVERY_DIR = "delivery"
PRE_S1_BLOCKER = "pre_s1_unconfirmed_requires_reconciliation"
PASS_GATES = {"PASS", "PASS_EXPLAINER_ONLY", "PASS_DATE_ONLY"}
SOCIAL_SPECS = {
    "facebook": {
        "outbox": "social/facebook_outbox.json",
        "state": "social/facebook_state.json",
        "state_prefix": "story-",
        "remote_fields": ["facebook_post_id"],
    },
    "instagram": {
        "outbox": "social/facebook_outbox.json",
        "state": "social/instagram_state.json",
        "state_prefix": "story-",
        "remote_fields": ["instagram_media_id", "container_id"],
    },
    "threads": {
        "outbox": "social/threads_outbox.json",
        "state": "social/threads_state.json",
        "state_prefix": "threads-story-",
        "remote_fields": ["root_remote_id", "remote_ids"],
    },
    "tiktok": {
        "outbox": "social/facebook_outbox.json",
        "state": "social/tiktok_state.json",
        "state_prefix": "story-",
        "remote_fields": ["publish_id", "post_id", "video_id"],
    },
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def article_version(item: dict[str, Any]) -> str:
    return stable_hash(item)[:16]


def delivery_id(edition_id: str, article_id: str, version: str, channel: str) -> str:
    return stable_hash([edition_id, article_id, version, channel])[:24]


def find_multi_outbox_item(outbox: dict[str, Any], article_id: str) -> dict[str, Any] | None:
    targets = {article_id, f"story-{article_id}"}
    for item in reversed(outbox.get("items", [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("source_story_id", "")) == article_id or str(item.get("id", "")) in targets:
            return item
    return None


def find_threads_item(outbox: dict[str, Any], article_id: str) -> dict[str, Any] | None:
    for item in reversed(outbox.get("items", [])):
        if not isinstance(item, dict):
            continue
        if str(item.get("story_id", "")) == article_id or str(item.get("id", "")) == f"threads-story-{article_id}":
            return item
    return None


def selected_channel_state(root: Path, channel: str, article_id: str) -> dict[str, Any] | None:
    spec = SOCIAL_SPECS[channel]
    outbox = read_json(root / spec["outbox"], {"items": []}) or {"items": []}
    if channel == "threads":
        item = find_threads_item(outbox, article_id)
        if item is None or item.get("status") in {"disabled", "cancelled"}:
            return None
        status = str(item.get("status", ""))
        blocker = item.get("reason") or item.get("hold_reason")
        if status in {"hold", "blocked"}:
            return {"selected": True, "queue_status": "blocked", "blocker": blocker or status}
        return {"selected": True, "queue_status": "pending", "blocker": None}

    item = find_multi_outbox_item(outbox, article_id)
    if item is None or item.get("status") in {"disabled", "cancelled"}:
        return None
    platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
    package = platforms.get(channel) if isinstance(platforms, dict) else None
    if not isinstance(package, dict):
        if channel != "facebook":
            return None
        package = {"status": item.get("status", "hold"), "reason": item.get("hold_reason")}
    status = str(package.get("status", item.get("status", "")))
    if status in {"disabled", "cancelled"}:
        return None
    blocker = package.get("reason") or item.get("hold_reason") or item.get("disabled_reason")
    if status in {"hold", "blocked"}:
        return {"selected": True, "queue_status": "blocked", "blocker": blocker or status}
    return {"selected": True, "queue_status": "pending", "blocker": None}


def build_manifest(root: Path) -> dict[str, Any]:
    current = read_json(root / "site/current_edition.json")
    if not isinstance(current, dict):
        raise RuntimeError("site/current_edition.json missing or invalid")
    source = root / str(current.get("json_source", ""))
    edition = read_json(source)
    if not isinstance(edition, dict):
        raise RuntimeError(f"edition source missing or invalid: {source}")
    edition_id = str(edition.get("edition_id") or current.get("edition_id") or "").strip()
    if not edition_id:
        raise RuntimeError("edition_id missing")
    if edition.get("publication_intent") != "publish" or edition.get("status") not in {"auto_approved", "editor_approved"}:
        raise RuntimeError(f"edition {edition_id} is not publishable")

    articles: list[dict[str, Any]] = []
    for item in edition.get("items", []):
        if not isinstance(item, dict):
            continue
        article_id = str(item.get("id", "")).strip()
        if not article_id:
            continue
        gate = str(item.get("material_fact_gate", ""))
        if gate and gate not in PASS_GATES:
            continue
        version = article_version(item)
        channels: dict[str, Any] = {
            "site": {"selected": True, "queue_status": "pending", "blocker": None}
        }
        for channel in SOCIAL_SPECS:
            selection = selected_channel_state(root, channel, article_id)
            if selection:
                channels[channel] = selection
        articles.append(
            {
                "article_id": article_id,
                "content_version": version,
                "headline": item.get("headline"),
                "section": item.get("section"),
                "material_fact_gate": item.get("material_fact_gate"),
                "canonical_url": f"https://valceaclar.ro/stiri/{article_id}/",
                "channels": channels,
            }
        )

    core = {
        "schema_version": SCHEMA_VERSION,
        "edition_id": edition_id,
        "edition_source": str(source.relative_to(root)),
        "edition_updated_local": edition.get("updated_local") or current.get("updated_local"),
        "publication_intent": edition.get("publication_intent"),
        "status": edition.get("status"),
        "articles": articles,
    }
    return {**core, "manifest_fingerprint_sha256": stable_hash(core), "generated_at": utc_now()}


def existing_records(root: Path) -> list[dict[str, Any]]:
    queue = read_json(root / DELIVERY_DIR / "queue.json", {"records": []}) or {"records": []}
    records = queue.get("records", []) if isinstance(queue, dict) else []
    return [r for r in records if isinstance(r, dict)]


def prior_terminal_record(
    records: list[dict[str, Any]], article_id: str, content_version: str, channel: str, edition_id: str
) -> dict[str, Any] | None:
    """Carry story-version delivery truth across recap editions.

    Editions are recap snapshots, not delivery identities. A new recap must not
    manufacture a fresh pending delivery for the exact same story version and
    channel. Prefer a prior delivered receipt; otherwise preserve an explicit
    blocked state. Pending records are intentionally not inherited.
    """
    candidates = [
        r for r in records
        if r.get("edition_id") != edition_id
        and r.get("article_id") == article_id
        and r.get("content_version") == content_version
        and r.get("channel") == channel
        and r.get("status") in {"delivered", "blocked"}
    ]
    delivered = [r for r in candidates if r.get("status") == "delivered"]
    if delivered:
        return delivered[-1]
    blocked = [r for r in candidates if r.get("status") == "blocked"]
    return blocked[-1] if blocked else None


def ensure_queue(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    prior = read_json(root / DELIVERY_DIR / "queue.json", {"records": [], "policy": {}}) or {"records": [], "policy": {}}
    prior_records = prior.get("records", []) if isinstance(prior, dict) else []
    records = [r for r in prior_records if isinstance(r, dict)]
    prior_policy = prior.get("policy", {}) if isinstance(prior, dict) and isinstance(prior.get("policy"), dict) else {}
    by_id = {str(r.get("delivery_id")): r for r in records if r.get("delivery_id")}
    for article in manifest.get("articles", []):
        for channel, selection in article.get("channels", {}).items():
            if not selection.get("selected"):
                continue
            did = delivery_id(
                manifest["edition_id"], article["article_id"], article["content_version"], channel
            )
            record = by_id.get(did)
            if record is None:
                inherited = prior_terminal_record(
                    records,
                    article["article_id"],
                    article["content_version"],
                    channel,
                    manifest["edition_id"],
                )
                inherited_status = inherited.get("status") if inherited else None
                inherited_blocker = inherited.get("blocker") if inherited_status == "blocked" else None
                inherited_confirmation = (
                    copy.deepcopy(inherited.get("confirmation"))
                    if inherited_status == "delivered" and inherited.get("confirmation")
                    else None
                )
                record = {
                    "delivery_id": did,
                    "edition_id": manifest["edition_id"],
                    "article_id": article["article_id"],
                    "content_version": article["content_version"],
                    "channel": channel,
                    "canonical_url": article["canonical_url"],
                    "status": inherited_status or selection.get("queue_status", "pending"),
                    "blocker": inherited_blocker if inherited_status == "blocked" else selection.get("blocker"),
                    "created_at": utc_now(),
                    "last_reconciled_at": None,
                    "confirmation": inherited_confirmation,
                    "inherited_from_delivery_id": inherited.get("delivery_id") if inherited else None,
                }
                records.append(record)
                by_id[did] = record
            else:
                record["canonical_url"] = article["canonical_url"]
                if record.get("status") != "delivered" and record.get("blocker") != PRE_S1_BLOCKER:
                    record["status"] = selection.get("queue_status", record.get("status", "pending"))
                    record["blocker"] = selection.get("blocker")

    return {
        "schema_version": SCHEMA_VERSION,
        "policy": {
            **prior_policy,
            "identity": "edition+article+content_version+channel",
            "confirmed_delivery_is_monotonic": True,
            "records_are_not_dropped_when_unselected_later": True,
        },
        "records": records,
        "updated_at": utc_now(),
    }


def site_confirmation(root: Path, article_id: str) -> dict[str, Any] | None:
    manifest = read_json(root / "site/runtime/stiri/manifest.json", {"stories": []}) or {"stories": []}
    for row in manifest.get("stories", []):
        if isinstance(row, dict) and str(row.get("id", "")) == article_id:
            page = root / "site" / "runtime" / "stiri" / article_id / "index.html"
            snapshot: dict[str, Any] = {"manifest_row": row}
            artifact_sha256 = None
            if page.is_file():
                artifact_sha256 = hashlib.sha256(page.read_bytes()).hexdigest()
                snapshot["artifact_sha256"] = artifact_sha256
            return {
                "confirmed": True,
                "source": "site/runtime/stiri/manifest.json",
                "source_snapshot_fingerprint": stable_hash(snapshot),
                "remote_id": row.get("canonical") or row.get("path"),
                "public_url": row.get("canonical") or f"https://valceaclar.ro/stiri/{article_id}/",
                "published_at": row.get("published_at"),
                "evidence": {
                    "archive_status": row.get("archive_status"),
                    "public_ux_authorized": row.get("public_ux_authorized"),
                    "artifact_sha256": artifact_sha256,
                },
            }
    return None


def social_confirmation(root: Path, channel: str, article_id: str) -> dict[str, Any] | None:
    spec = SOCIAL_SPECS[channel]
    state = read_json(root / spec["state"], {"published": {}}) or {"published": {}}
    published = state.get("published") if isinstance(state, dict) else {}
    if not isinstance(published, dict):
        return None
    key = spec["state_prefix"] + article_id
    entry = published.get(key)
    if not isinstance(entry, dict):
        return None
    evidence = {f: entry.get(f) for f in spec["remote_fields"] if entry.get(f) is not None}
    remote_id = None
    for field in spec["remote_fields"]:
        value = entry.get(field)
        if isinstance(value, list) and value:
            remote_id = str(value[0])
            break
        if value is not None:
            remote_id = str(value)
            break
    return {
        "confirmed": True,
        "source": spec["state"],
        "state_key": key,
        "source_snapshot_fingerprint": stable_hash(entry),
        "remote_id": remote_id,
        "published_at": entry.get("published_at"),
        "evidence": evidence,
    }


def merge_confirmation(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any] | None:
    if not new:
        return old
    if not old:
        return new
    merged = copy.deepcopy(old)
    for key, value in new.items():
        if value is not None:
            if key == "evidence" and isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key].update(value)
            else:
                merged[key] = value
    return merged


def reconcile(root: Path, queue: dict[str, Any]) -> dict[str, Any]:
    now = utc_now()
    records = queue.get("records", [])
    for record in records:
        channel = record.get("channel")
        article_id = str(record.get("article_id", ""))
        if channel == "site":
            found = site_confirmation(root, article_id)
        elif channel in SOCIAL_SPECS:
            found = social_confirmation(root, str(channel), article_id)
        else:
            found = None

        current = record.get("confirmation") or {}
        if found and found.get("source_snapshot_fingerprint"):
            fp = found["source_snapshot_fingerprint"]
            current_fp = current.get("source_snapshot_fingerprint")
            if current.get("confirmed") is True and current_fp and current_fp != fp:
                found = None
            else:
                used_by_other_version = any(
                    other is not record
                    and other.get("article_id") == article_id
                    and other.get("channel") == channel
                    and other.get("content_version") != record.get("content_version")
                    and other.get("status") == "delivered"
                    and (other.get("confirmation") or {}).get("source_snapshot_fingerprint") == fp
                    for other in records
                )
                if used_by_other_version:
                    found = None
                else:
                    found["bound_content_version"] = record.get("content_version")

        record["confirmation"] = merge_confirmation(record.get("confirmation"), found)
        confirmation = record.get("confirmation") or {}
        if confirmation.get("confirmed") is True:
            record["status"] = "delivered"
            record["blocker"] = None
        record["last_reconciled_at"] = now
    queue["updated_at"] = now
    return queue


def quarantine_pre_s1_pending(queue: dict[str, Any]) -> dict[str, Any]:
    policy = queue.setdefault("policy", {})
    if policy.get("pre_s1_unconfirmed_reconciliation") == "complete":
        return queue
    quarantined = 0
    now = utc_now()
    for record in queue.get("records", []):
        confirmation = record.get("confirmation") or {}
        if record.get("status") == "pending" and confirmation.get("confirmed") is not True:
            record["status"] = "blocked"
            record["blocker"] = PRE_S1_BLOCKER
            record["blocked_at"] = now
            record["blocked_by"] = "s1_bootstrap_migration"
            quarantined += 1
    policy["pre_s1_unconfirmed_reconciliation"] = "complete"
    policy["pre_s1_quarantined_count"] = quarantined
    policy["pre_s1_quarantined_at"] = now
    return queue


def build_report(manifest: dict[str, Any], queue: dict[str, Any]) -> dict[str, Any]:
    current = [r for r in queue.get("records", []) if r.get("edition_id") == manifest.get("edition_id")]
    counts = {"delivered": 0, "pending": 0, "blocked": 0, "cancelled": 0, "other": 0}
    for record in current:
        status = str(record.get("status", "other"))
        counts[status if status in counts else "other"] += 1
    blockers = [
        {
            "delivery_id": r.get("delivery_id"),
            "article_id": r.get("article_id"),
            "channel": r.get("channel"),
            "blocker": r.get("blocker") or "unconfirmed_delivery",
        }
        for r in current if r.get("status") in {"pending", "blocked"}
    ]
    delivered = [
        {
            "delivery_id": r.get("delivery_id"),
            "article_id": r.get("article_id"),
            "channel": r.get("channel"),
            "remote_id": (r.get("confirmation") or {}).get("remote_id"),
            "public_url": (r.get("confirmation") or {}).get("public_url"),
            "published_at": (r.get("confirmation") or {}).get("published_at"),
        }
        for r in current if r.get("status") == "delivered"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "edition_id": manifest.get("edition_id"),
        "manifest_fingerprint_sha256": manifest.get("manifest_fingerprint_sha256"),
        "generated_at": utc_now(),
        "counts": counts,
        "complete": counts["pending"] == 0 and counts["other"] == 0,
        "fully_delivered": counts["pending"] == 0 and counts["blocked"] == 0 and counts["other"] == 0,
        "delivered": delivered,
        "blockers": blockers,
    }


def run(root: Path) -> dict[str, Any]:
    manifest = build_manifest(root)
    queue = reconcile(root, ensure_queue(root, manifest))
    queue = quarantine_pre_s1_pending(queue)
    report = build_report(manifest, queue)
    out = root / DELIVERY_DIR
    write_json(out / "manifest.json", manifest)
    write_json(out / "queue.json", queue)
    write_json(out / "report.json", report)
    return report


def _write_fixture(root: Path) -> None:
    write_json(root / "site/current_edition.json", {
        "edition_id": "2026-09-22-morning", "json_source": "editions/2026-09-22-morning.json"
    })
    write_json(root / "editions/2026-09-22-morning.json", {
        "edition_id": "2026-09-22-morning", "status": "auto_approved", "publication_intent": "publish",
        "items": [
            {"id": "alpha", "headline": "Alpha", "section": "UTIL", "material_fact_gate": "PASS", "dek": "A"},
            {"id": "beta", "headline": "Beta", "section": "SPORT", "material_fact_gate": "PASS", "dek": "B"},
        ]
    })
    write_json(root / "site/runtime/stiri/manifest.json", {"stories": [
        {"id": "alpha", "canonical": "https://valceaclar.ro/stiri/alpha/", "published_at": "2026-09-22T06:00:00Z", "archive_status": "published_archive"}
    ]})
    write_json(root / "social/facebook_outbox.json", {"items": [
        {"id": "story-alpha", "source_story_id": "alpha", "status": "ready", "platforms": {
            "facebook": {"status": "ready"}, "instagram": {"status": "ready"},
            "tiktok": {"status": "hold", "reason": "media_required"}
        }},
        {"id": "story-beta", "source_story_id": "beta", "status": "hold", "hold_reason": "photo_required",
         "platforms": {"facebook": {"status": "hold", "reason": "photo_required"}}},
    ]})
    write_json(root / "social/facebook_state.json", {"published": {
        "story-alpha": {"facebook_post_id": "fb-1", "published_at": "2026-09-22T06:10:00Z"}
    }})
    write_json(root / "social/instagram_state.json", {"published": {}})
    write_json(root / "social/tiktok_state.json", {"published": {}})
    write_json(root / "social/threads_outbox.json", {"items": [
        {"id": "threads-story-alpha", "story_id": "alpha", "status": "outbox_ready"}
    ]})
    write_json(root / "social/threads_state.json", {"published": {}})


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_fixture(root)
        first = run(root)
        records = read_json(root / "delivery/queue.json")["records"]

        def rec(article: str, channel: str) -> dict[str, Any]:
            return next(r for r in records if r["article_id"] == article and r["channel"] == channel)

        assert rec("alpha", "site")["status"] == "delivered"
        assert rec("alpha", "facebook")["status"] == "delivered"
        assert rec("alpha", "instagram")["status"] == "blocked"
        assert rec("alpha", "instagram")["blocker"] == PRE_S1_BLOCKER
        assert rec("alpha", "tiktok")["status"] == "blocked"
        assert rec("alpha", "threads")["status"] == "blocked"
        assert rec("alpha", "threads")["blocker"] == PRE_S1_BLOCKER
        assert rec("beta", "facebook")["status"] == "blocked"
        assert first["complete"] is True
        assert first["fully_delivered"] is False

        morning_records = read_json(root / "delivery/queue.json")["records"]
        morning_versions = {
            (r["article_id"], r["channel"]): r["content_version"]
            for r in morning_records if r["edition_id"] == "2026-09-22-morning"
        }
        morning = read_json(root / "editions/2026-09-22-morning.json")
        evening = copy.deepcopy(morning)
        evening["edition_id"] = "2026-09-22-evening"
        write_json(root / "editions/2026-09-22-evening.json", evening)
        write_json(root / "site/current_edition.json", {
            "edition_id": "2026-09-22-evening", "json_source": "editions/2026-09-22-evening.json"
        })
        evening_report = run(root)
        evening_records = [
            r for r in read_json(root / "delivery/queue.json")["records"]
            if r["edition_id"] == "2026-09-22-evening"
        ]
        assert evening_report["complete"] is True
        assert not any(r["status"] == "pending" for r in evening_records)
        for r in evening_records:
            key=(r["article_id"], r["channel"])
            assert r["content_version"] == morning_versions[key]
            if key == ("alpha", "facebook"):
                assert r["status"] == "delivered"
                assert (r.get("confirmation") or {}).get("remote_id") == "fb-1"
                assert r.get("inherited_from_delivery_id")
            if key == ("alpha", "threads"):
                assert r["status"] == "blocked"
                assert r["blocker"] == PRE_S1_BLOCKER

        # Return to the morning edition for version-change isolation tests.
        write_json(root / "site/current_edition.json", {
            "edition_id": "2026-09-22-morning", "json_source": "editions/2026-09-22-morning.json"
        })

        write_json(root / "social/facebook_state.json", {"published": {}})
        run(root)
        records = read_json(root / "delivery/queue.json")["records"]
        fb = next(r for r in records if r["article_id"] == "alpha" and r["channel"] == "facebook")
        assert fb["status"] == "delivered"
        assert fb["confirmation"]["remote_id"] == "fb-1"

        write_json(root / "social/facebook_state.json", {"published": {
            "story-alpha": {"facebook_post_id": "fb-1", "published_at": "2026-09-22T06:10:00Z"}
        }})
        edition = read_json(root / "editions/2026-09-22-morning.json")
        edition["items"][0]["dek"] = "A2"
        write_json(root / "editions/2026-09-22-morning.json", edition)
        run(root)
        alpha_fb = [
            r for r in read_json(root / "delivery/queue.json")["records"]
            if r["article_id"] == "alpha" and r["channel"] == "facebook"
            and r["edition_id"] == "2026-09-22-morning"
        ]
        assert len(alpha_fb) == 2
        assert sorted(r["status"] for r in alpha_fb) == ["delivered", "pending"]
        assert sum(1 for r in alpha_fb if r["confirmation"] and r["confirmation"].get("remote_id") == "fb-1") == 1

        write_json(root / "social/facebook_state.json", {"published": {
            "story-alpha": {"facebook_post_id": "fb-2", "published_at": "2026-09-22T07:10:00Z"}
        }})
        run(root)
        alpha_fb = [
            r for r in read_json(root / "delivery/queue.json")["records"]
            if r["article_id"] == "alpha" and r["channel"] == "facebook"
        ]
        assert sorted(r["status"] for r in alpha_fb) == ["delivered", "delivered"]
        assert {r["confirmation"].get("remote_id") for r in alpha_fb} == {"fb-1", "fb-2"}

    print(json.dumps({
        "self_test": "PASS",
        "invariants": [
            "dedupe", "monotonic_confirmation", "versioned_delivery",
            "provider_snapshot_single_version_binding", "recap_delivery_truth_carryover", "legacy_pending_quarantine", "explicit_blockers"
        ],
    }))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    report = run(args.root.resolve())
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
