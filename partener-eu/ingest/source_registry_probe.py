#!/usr/bin/env python3
import hashlib
import json
import re
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
STATE = ROOT / "partener-eu" / "ingest" / "state" / "source_registry_health.json"
UA = "Mozilla/5.0 CIVORA-PARTENER-EU/1.0 (+production-validation)"


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def semantic_bytes(raw: bytes, content_type: str) -> bytes:
    if "html" not in (content_type or "").lower():
        return raw
    text = raw.decode("utf-8", errors="ignore")
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text.encode("utf-8")


def fetch(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
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


def main():
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    previous = {}
    if STATE.exists():
        try:
            old = json.loads(STATE.read_text(encoding="utf-8"))
            previous = {x["id"]: x for x in old.get("sources", [])}
        except Exception:
            previous = {}

    out = {
        "schema_version": "1.0",
        "observed_at": utc_now(),
        "policy": "health-and-hash-only-no-material-fact-autoupdate",
        "sources": [],
    }

    for src in registry.get("sources", []):
        row = {
            "id": src["id"],
            "tier": src["tier"],
            "class": src["class"],
            "url": src["url"],
            "material_fact_use": bool(src.get("material_fact_use")),
        }
        try:
            row.update(fetch(src["url"]))
            old = previous.get(src["id"], {})
            old_hash = old.get("semantic_sha256")
            changed = bool(old_hash and old_hash != row.get("semantic_sha256"))
            row["semantic_hash_changed"] = changed
            row["resolution_task_required"] = bool(changed and src.get("material_fact_use"))
            row["publish_material_fact_update"] = False if changed else None
            row["health"] = "PASS" if row.get("ok") else "FAIL"
        except Exception as exc:
            row.update({
                "ok": False,
                "health": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "semantic_hash_changed": False,
                "resolution_task_required": False,
                "publish_material_fact_update": False,
            })
        out["sources"].append(row)

    out["summary"] = {
        "total": len(out["sources"]),
        "pass": sum(1 for x in out["sources"] if x.get("health") == "PASS"),
        "fail": sum(1 for x in out["sources"] if x.get("health") == "FAIL"),
        "resolution_tasks_required": sum(1 for x in out["sources"] if x.get("resolution_task_required")),
    }
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
