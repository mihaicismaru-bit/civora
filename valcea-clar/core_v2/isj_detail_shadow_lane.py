from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit


ALLOWED_HOSTS = {"isjvalcea.ro", "www.isjvalcea.ro"}
MAX_DETAILS = 12


def _load_legacy_detail_module():
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    module_path = scripts_dir / "isj_valcea_education_detail_evidence.py"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    module_name = "core_v2_isj_valcea_education_detail_evidence"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("isj_detail_module_load_failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _is_first_party_https(url: str) -> bool:
    parsed = urlsplit(str(url or "").strip())
    return (
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() in ALLOWED_HOSTS
        and not parsed.username
        and not parsed.password
        and parsed.port in (None, 443)
    )


def _evidence_id(signal_id: str, detail_sha256: str) -> str:
    seed = f"{signal_id}|{detail_sha256}"
    return "isj-detail-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def verify_isj_details(
    signal_report: dict[str, Any],
    *,
    allow_network: bool = True,
    fetcher: Callable[[str], tuple[bytes, str, str]] | None = None,
    html_extractor: Callable[[bytes, str], tuple[str | None, str | None, tuple[str, ...]]] | None = None,
) -> dict[str, Any]:
    """Resolve only first-party ISJ detail targets selected by the signal gate.

    This is a second-hop evidence gate, not a FactKernel or writer. A successful fetch
    proves bounded first-party bytes and explicit visible text only. External document
    hosts remain blocked and are never fetched. Network access is explicit so fixture and
    non-live orchestration cannot accidentally read a source.
    """
    if str(signal_report.get("publication_authority") or "NONE") != "NONE":
        raise ValueError("upstream_publication_boundary_violation")
    if signal_report.get("fact_kernel_promotion_allowed") is True or signal_report.get("writer_allowed") is True:
        raise ValueError("upstream_promotion_boundary_violation")

    rows = [row for row in signal_report.get("rows") or [] if isinstance(row, dict)]
    candidates = [row for row in rows if row.get("state") == "MATERIAL_SIGNAL_SHADOW"][:MAX_DETAILS]

    details: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    loaders_ready = False

    for row in candidates:
        signal_id = str(row.get("signal_id") or "").strip()
        label = str(row.get("label") or "").strip()
        target = str(row.get("document_url") or "").strip()
        base = {
            "signal_id": signal_id,
            "label": label or None,
            "document_url": target or None,
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "sensitive_result_projection_allowed": False,
        }
        if not target:
            blocked.append({**base, "state": "BLOCKED", "reason": "official_detail_url_missing"})
            continue
        if not _is_first_party_https(target):
            blocked.append({
                **base,
                "state": "BLOCKED",
                "reason": "official_detail_not_first_party_https",
                "detail_fetch_attempted": False,
            })
            continue
        if not allow_network:
            blocked.append({
                **base,
                "state": "BLOCKED",
                "reason": "network_read_not_enabled",
                "detail_fetch_attempted": False,
            })
            continue

        if not loaders_ready and (fetcher is None or html_extractor is None):
            legacy = _load_legacy_detail_module()
            fetcher = fetcher or legacy._fetch_detail
            html_extractor = html_extractor or legacy._extract_html_evidence
            loaders_ready = True
        assert fetcher is not None
        assert html_extractor is not None

        try:
            body, final_url, content_type = fetcher(target)
            detail_sha = hashlib.sha256(body).hexdigest()
            visible_title: str | None = None
            explicit_date: str | None = None
            fragments: tuple[str, ...] = ()
            if content_type in {"text/html", "text/plain"}:
                visible_title, explicit_date, fragments = html_extractor(body, label)
            details.append({
                **base,
                "state": "DETAIL_EVIDENCE_SHADOW",
                "reason": "first_party_detail_bytes_verified_non_authorizing",
                "detail_url": final_url,
                "detail_host": (urlsplit(final_url).hostname or "").lower(),
                "content_type": content_type,
                "content_length": len(body),
                "detail_sha256": detail_sha,
                "evidence_id": _evidence_id(signal_id, detail_sha),
                "visible_title": visible_title,
                "explicit_date_text": explicit_date,
                "evidence_fragments": list(fragments)[:4],
                "detail_fetch_attempted": True,
                "detail_readback_verified": True,
            })
        except Exception as exc:
            blocked.append({
                **base,
                "state": "BLOCKED",
                "reason": "first_party_detail_fetch_failed",
                "detail_fetch_attempted": True,
                "error_type": type(exc).__name__,
                "error": str(exc)[:400],
            })

    result_rows = details + blocked
    return {
        "schema_version": "1.0",
        "mode": "ISJ_FIRST_PARTY_DETAIL_EVIDENCE_SHADOW",
        "source_kind": "isj_valcea",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "network_read_enabled": allow_network,
        "material_fact_use": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "selected_material_signal_count": len(candidates),
        "detail_evidence_shadow_count": len(details),
        "blocked_count": len(blocked),
        "rows": result_rows,
        "truth_rule": (
            "A category/label signal may cross only to bounded first-party detail evidence. "
            "Verified detail bytes are still non-authorizing: material facts, currentness, FactKernel and writer require a separate field-level adjudication. "
            "External document hosts are never fetched by this lane, and sensitive/person-level result projection remains forbidden."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve bounded first-party ISJ detail evidence in Core v2 shadow mode")
    parser.add_argument("--input", required=True)
    parser.add_argument("--live", action="store_true", help="Permit bounded read-only fetches from allow-listed first-party ISJ detail URLs")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    source = json.loads(Path(args.input).read_text(encoding="utf-8"))
    try:
        result = verify_isj_details(source, allow_network=args.live)
    except Exception as exc:
        result = {
            "schema_version": "1.0",
            "mode": "ISJ_FIRST_PARTY_DETAIL_EVIDENCE_SHADOW",
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "network_read_enabled": args.live,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "status": "BLOCKED",
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "rows": [],
        }
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": result.get("status", "PASS_SHADOW"),
        "selected_material_signal_count": result.get("selected_material_signal_count", 0),
        "detail_evidence_shadow_count": result.get("detail_evidence_shadow_count", 0),
        "blocked_count": result.get("blocked_count", 0),
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
