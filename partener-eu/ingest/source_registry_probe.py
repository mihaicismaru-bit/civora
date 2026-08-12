#!/usr/bin/env python3
import hashlib
import json
import re
import ssl
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
STATE = ROOT / "partener-eu" / "ingest" / "state" / "source_registry_health.json"
TASK_DIR = ROOT / "partener-eu" / "validation" / "resolution-tasks"
UA = "Mozilla/5.0 CIVORA-PARTENER-EU/1.0 (+production-validation)"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def semantic_bytes(raw: bytes, content_type: str) -> bytes:
    if "html" not in (content_type or "").lower():
        return raw
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove common volatile presentation fragments while retaining substantive text.
    text = re.sub(r"\b(?:[0-2]?\d:[0-5]\d(?::[0-5]\d)?|\d+\s+(?:seconds?|minutes?)\s+ago)\b", " ", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip()
    return text.encode("utf-8")


def fetch_once(url: str):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
        "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
        "Connection": "close",
    })
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=18, context=ctx) as r:
        raw = r.read(3_000_000)
        ctype = r.headers.get("content-type") or ""
        sem = semantic_bytes(raw, ctype)
        return {
            "ok": 200 <= r.status < 400,
            "http_status": r.status,
            "final_url": r.geturl(),
            "content_type": ctype,
            "bytes": len(raw),
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
            "semantic_sha256": hashlib.sha256(sem).hexdigest(),
            "semantic_bytes": len(sem),
        }


def fetch(url: str, attempts: int = 2):
    last = None
    for n in range(1, attempts + 1):
        try:
            out = fetch_once(url)
            out["attempts"] = n
            return out
        except Exception as exc:
            last = exc
            if n < attempts:
                time.sleep(1.25 * n)
    raise last


def write_resolution_task(src, old_hash, new_hash, observed_at):
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    p = TASK_DIR / f"{src['id']}.json"
    existing = {}
    if p.exists():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    task = {
        "schema_version": "1.1",
        "type": "OFFICIAL_SOURCE_HASH_RESOLUTION",
        "source_id": src["id"],
        "source_tier": src["tier"],
        "source_url": src["url"],
        "status": "OPEN",
        "first_observed_at": existing.get("first_observed_at") or observed_at,
        "last_observed_at": observed_at,
        "previous_semantic_sha256": old_hash,
        "current_semantic_sha256": new_hash,
        "material_fact_autoupdate_allowed": False,
        "blocked_fact_classes": ["deadline", "eligibility", "budget", "scoring", "beneficiaries", "material_call_status", "other_material_facts"],
        "required_resolution": "Re-establish authoritative evidence and provenance before any material fact update.",
    }
    p.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    previous = {}
    if STATE.exists():
        try:
            old = json.loads(STATE.read_text(encoding="utf-8"))
            previous = {x["id"]: x for x in old.get("sources", [])}
        except Exception:
            previous = {}

    observed_at = utc_now()
    out = {
        "schema_version": "1.2",
        "observed_at": observed_at,
        "policy": "health-and-hash-only-no-material-fact-autoupdate",
        "sources": [],
    }

    for src in registry.get("sources", []):
        old = previous.get(src["id"], {})
        row = {"id": src["id"], "tier": src["tier"], "class": src["class"], "url": src["url"], "material_fact_use": bool(src.get("material_fact_use"))}
        try:
            row.update(fetch(src["url"]))
            old_hash = old.get("semantic_sha256")
            new_hash = row.get("semantic_sha256")
            changed = bool(old_hash and old_hash != new_hash)
            row["semantic_hash_changed"] = changed
            row["resolution_task_required"] = bool(changed and src.get("material_fact_use"))
            row["publish_material_fact_update"] = False if changed else None
            row["consecutive_failures"] = 0
            row["health"] = "PASS" if row.get("ok") else "FAIL"
            if row["resolution_task_required"]:
                write_resolution_task(src, old_hash, new_hash, observed_at)
        except Exception as exc:
            failures = int(old.get("consecutive_failures") or 0) + 1
            row.update({
                "ok": False,
                "health": "DEGRADED" if failures < 3 else "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "semantic_hash_changed": False,
                "resolution_task_required": False,
                "publish_material_fact_update": False,
                "consecutive_failures": failures,
                "last_known_semantic_sha256": old.get("semantic_sha256") or old.get("last_known_semantic_sha256"),
                "quarantined": failures >= 3,
            })
        out["sources"].append(row)

    out["summary"] = {
        "total": len(out["sources"]),
        "pass": sum(1 for x in out["sources"] if x.get("health") == "PASS"),
        "degraded": sum(1 for x in out["sources"] if x.get("health") == "DEGRADED"),
        "fail": sum(1 for x in out["sources"] if x.get("health") == "FAIL"),
        "quarantined": sum(1 for x in out["sources"] if x.get("quarantined")),
        "resolution_tasks_required": sum(1 for x in out["sources"] if x.get("resolution_task_required")),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
