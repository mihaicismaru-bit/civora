from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CORE_FACT_KERNEL_KEYS = (
    "what",
    "who",
    "where",
    "when",
    "why_it_matters",
    "source",
    "source_url",
    "claims",
    "evidence_ids",
)


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _is_core_fact_kernel(value: Any) -> bool:
    return isinstance(value, dict) and all(key in value for key in CORE_FACT_KERNEL_KEYS)


def _fact_index(facts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("id") or ""): row
        for row in facts.get("facts") or []
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }


def read_source(url: str, timeout: float = 12.0, max_bytes: int = 262_144) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Fact-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = str(response.geturl() or url)
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(max_bytes + 1)
    except HTTPError as exc:
        return {
            "requested_url": url,
            "final_url": getattr(exc, "url", url),
            "http_status": int(getattr(exc, "code", 0) or 0),
            "readback_ok": False,
            "error": str(exc),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "requested_url": url,
            "final_url": None,
            "http_status": None,
            "readback_ok": False,
            "error": str(exc),
        }

    truncated = len(body) > max_bytes
    bounded = body[:max_bytes]
    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "bytes_hashed": len(bounded),
        "content_sha256": hashlib.sha256(bounded).hexdigest() if bounded else None,
        "bounded_read_truncated": truncated,
        "readback_ok": bool(200 <= status < 400 and bounded),
    }


def build(
    candidates: dict[str, Any],
    facts: dict[str, Any],
    *,
    reader: Callable[[str], dict[str, Any]] = read_source,
) -> dict[str, Any]:
    fact_by_id = _fact_index(facts)
    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]
    rows: list[dict[str, Any]] = []
    source_readback_story_count = 0
    explicit_core_kernel_story_count = 0

    for story_id in story_ids:
        record = fact_by_id.get(story_id)
        result: dict[str, Any] = {
            "story_id": story_id,
            "publication_authority": "NONE",
            "promotion_allowed": False,
            "legacy_verified_fact_record_present": False,
            "legacy_material_fact_gate": None,
            "legacy_fact_kernel_present": False,
            "explicit_core_v2_fact_kernel_present": False,
            "t1_source_count": 0,
            "t1_source_readback_passed": 0,
            "all_t1_sources_readback_ok": False,
            "source_readback": [],
            "state": "BLOCKED_VERIFIED_FACT_RECORD_MISSING",
        }
        if not isinstance(record, dict):
            rows.append(result)
            continue

        status = str(record.get("status") or "")
        material_gate = str(record.get("material_fact_gate") or "")
        result["legacy_verified_fact_record_present"] = status == "verified"
        result["legacy_material_fact_gate"] = material_gate or None
        if status != "verified":
            result["state"] = "BLOCKED_LEGACY_FACT_NOT_VERIFIED"
            rows.append(result)
            continue
        if not material_gate.startswith("PASS"):
            result["state"] = "BLOCKED_LEGACY_MATERIAL_FACT_GATE"
            rows.append(result)
            continue

        legacy_kernel = record.get("fact_kernel")
        result["legacy_fact_kernel_present"] = isinstance(legacy_kernel, dict)
        explicit_kernel = record if _is_core_fact_kernel(record) else legacy_kernel if _is_core_fact_kernel(legacy_kernel) else None
        result["explicit_core_v2_fact_kernel_present"] = explicit_kernel is not None
        if explicit_kernel is not None:
            explicit_core_kernel_story_count += 1

        t1_sources = [
            source
            for source in record.get("sources") or []
            if isinstance(source, dict)
            and str(source.get("url") or "").strip()
            and str(source.get("tier") or "").upper().startswith("T1")
        ]
        result["t1_source_count"] = len(t1_sources)
        if not t1_sources:
            result["state"] = "BLOCKED_T1_SOURCE_MISSING"
            rows.append(result)
            continue

        readbacks: list[dict[str, Any]] = []
        for source in t1_sources:
            url = str(source.get("url") or "").strip()
            evidence = reader(url)
            readbacks.append(
                {
                    "source_name": source.get("name"),
                    "source_tier": source.get("tier"),
                    **evidence,
                }
            )
        passed = sum(1 for evidence in readbacks if evidence.get("readback_ok") is True)
        all_ok = passed == len(readbacks)
        result["source_readback"] = readbacks
        result["t1_source_readback_passed"] = passed
        result["all_t1_sources_readback_ok"] = all_ok
        if passed:
            source_readback_story_count += 1

        if not all_ok:
            result["state"] = "BLOCKED_T1_SOURCE_READBACK"
        elif explicit_kernel is None:
            result["state"] = "LEGACY_VERIFIED_FACT_SOURCE_READBACK_ONLY"
        else:
            result["state"] = "CORE_FACT_KERNEL_PRESENT_SOURCE_READBACK"
        rows.append(result)

    state_counts: dict[str, int] = {}
    for row in rows:
        state = str(row.get("state") or "UNKNOWN")
        state_counts[state] = state_counts.get(state, 0) + 1

    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_HISTORICAL_FACT_PREFLIGHT",
        "publication_authority": "NONE",
        "promotion_allowed": False,
        "truth_rule": "Legacy verified facts may identify reusable evidence, but source reachability alone never creates a Core v2 FactKernel and never authorizes publication.",
        "candidate_count": len(rows),
        "source_readback_story_count": source_readback_story_count,
        "explicit_core_v2_fact_kernel_story_count": explicit_core_kernel_story_count,
        "state_counts": state_counts,
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only historical FactKernel evidence preflight for Core v2 replay candidates")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--facts", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(_load(args.candidates), _load(args.facts))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": result["candidate_count"],
                "source_readback_story_count": result["source_readback_story_count"],
                "explicit_core_v2_fact_kernel_story_count": result["explicit_core_v2_fact_kernel_story_count"],
                "state_counts": result["state_counts"],
                "publication_authority": "NONE",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
