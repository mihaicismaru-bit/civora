from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


MODE = "CORE_V2_VERIFIED_ARTICLE_LEDGER_SHADOW"
PUBLIC_SAFETY = {"ipj", "isu"}


def _require_shadow(doc: dict[str, Any], label: str) -> None:
    if doc.get("publication_authority") != "NONE":
        raise ValueError(f"{label}: publication_authority must be NONE")
    if doc.get("acceptance_ready") is True:
        raise ValueError(f"{label}: acceptance_ready escaped shadow")
    if doc.get("site_publish_allowed") is True or doc.get("social_publish_allowed") is True:
        raise ValueError(f"{label}: publish authority escaped shadow")
    if doc.get("production_writer_ready") is True:
        raise ValueError(f"{label}: production_writer_ready escaped shadow")


def _stable_public_safety_id(source_label: str, source_url: str) -> str:
    if source_label not in PUBLIC_SAFETY or not source_url:
        raise ValueError("public-safety source label and source URL are required")
    return hashlib.sha256(f"{source_label}\n{source_url}".encode("utf-8")).hexdigest()[:24]


def _normalized_row(article_id: str, *, source_label: str, fact_kernel: dict[str, Any], article_package: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": article_id,
        "story_id": article_id,
        "source_label": source_label,
        "state": "VERIFIED_WRITTEN_SHADOW",
        "publication_authority": "NONE",
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "fact_kernel": fact_kernel,
        "article_package": article_package,
    }


def _collect_public_safety(doc: dict[str, Any], label: str) -> list[dict[str, Any]]:
    _require_shadow(doc, label)
    if str(doc.get("source_kind") or "") != label:
        raise ValueError(f"{label}: source_kind mismatch")
    rows: list[dict[str, Any]] = []
    for row in doc.get("rows") or []:
        if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
            continue
        if row.get("publication_authority") != "NONE":
            raise ValueError(f"{label}: verified row escaped shadow")
        integrity = row.get("integrity") or {}
        if integrity.get("status") != "PASS" or int(integrity.get("fabricated_claims") or 0) != 0:
            raise ValueError(f"{label}: verified row lacks passing independent integrity")
        kernel = row.get("fact_kernel") or {}
        package = row.get("article_package") or {}
        source_url = str(kernel.get("source_url") or "").strip()
        if not source_url or not package.get("headline") or not package.get("body"):
            raise ValueError(f"{label}: verified article package incomplete")
        article_id = _stable_public_safety_id(label, source_url)
        rows.append(_normalized_row(article_id, source_label=label, fact_kernel=kernel, article_package=package))
    return rows


def _collect_municipal(doc: dict[str, Any]) -> list[dict[str, Any]]:
    _require_shadow(doc, "municipal")
    rows: list[dict[str, Any]] = []
    for parent in doc.get("rows") or []:
        if parent.get("state") != "VERIFIED_WRITTEN_SHADOW":
            continue
        for article in parent.get("articles") or []:
            if not isinstance(article, dict) or article.get("state") != "VERIFIED_WRITTEN_SHADOW":
                continue
            if article.get("publication_authority") != "NONE":
                raise ValueError("municipal: article escaped shadow")
            integrity = article.get("integrity") or {}
            if integrity.get("status") != "PASS" or int(integrity.get("fabricated_claims") or 0) != 0 or integrity.get("body_fully_controlled") is not True:
                raise ValueError("municipal: article lacks passing controlled-body integrity")
            article_id = str(article.get("article_id") or "").strip()
            kernel = article.get("fact_kernel") or {}
            package = article.get("article_package") or {}
            if not article_id or not package.get("headline") or not package.get("body"):
                raise ValueError("municipal: verified article package incomplete")
            rows.append(_normalized_row(article_id, source_label="municipal", fact_kernel=kernel, article_package=package))
    return rows


def _collect_isj(article_doc: dict[str, Any], integrity_doc: dict[str, Any]) -> list[dict[str, Any]]:
    _require_shadow(article_doc, "isj_article")
    _require_shadow(integrity_doc, "isj_integrity")
    if article_doc.get("state") != "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY":
        raise ValueError("isj: writer state is not pending independent integrity")
    if integrity_doc.get("status") != "PASS_SHADOW" or integrity_doc.get("article_truth_state") != "VERIFIED_WRITTEN_SHADOW" or integrity_doc.get("article_integrity_verified") is not True:
        raise ValueError("isj: independent article integrity did not pass")
    if int(integrity_doc.get("fabricated_claim_count") or 0) != 0:
        raise ValueError("isj: fabricated claims detected")
    verified = {
        str(row.get("article_id") or ""): row
        for row in integrity_doc.get("verified_candidates") or []
        if isinstance(row, dict) and row.get("article_id")
    }
    rows: list[dict[str, Any]] = []
    for article in article_doc.get("articles") or []:
        if not isinstance(article, dict):
            continue
        article_id = str(article.get("article_id") or "").strip()
        candidate = verified.get(article_id)
        if not article_id or not isinstance(candidate, dict):
            continue
        kernel = article.get("fact_kernel") or {}
        package = article.get("article_package") or {}
        if str(candidate.get("source_url") or "").strip() != str(kernel.get("source_url") or "").strip():
            raise ValueError("isj: integrity candidate/source identity mismatch")
        if str(candidate.get("headline") or "").strip() != str(package.get("headline") or "").strip():
            raise ValueError("isj: integrity candidate/headline mismatch")
        if not package.get("body"):
            raise ValueError("isj: verified article package incomplete")
        rows.append(_normalized_row(article_id, source_label="isj", fact_kernel=kernel, article_package=package))
    if len(rows) != int(integrity_doc.get("verified_article_count") or 0):
        raise ValueError("isj: verified article cardinality mismatch")
    return rows


def build_ledger(*, ipj: dict[str, Any], isu: dict[str, Any], municipal: dict[str, Any], isj_article: dict[str, Any], isj_integrity: dict[str, Any]) -> dict[str, Any]:
    collected = (
        _collect_public_safety(ipj, "ipj")
        + _collect_public_safety(isu, "isu")
        + _collect_municipal(municipal)
        + _collect_isj(isj_article, isj_integrity)
    )
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_identical_count = 0
    for row in collected:
        article_id = str(row.get("article_id") or "")
        previous = by_id.get(article_id)
        if previous is None:
            by_id[article_id] = row
            continue
        if previous != row:
            raise ValueError(f"conflicting verified article identity: {article_id}")
        duplicate_identical_count += 1
    rows = list(by_id.values())
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get("source_label") or "unknown")
        counts[label] = counts.get(label, 0) + 1
    return {
        "schema_version": "1.0",
        "mode": MODE,
        "status": "PASS_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "article_count": len(rows),
        "source_article_counts": counts,
        "duplicate_identical_count": duplicate_identical_count,
        "rows": rows,
        "truth_rule": "Only independently verified shadow article outputs enter this normalized site-input ledger. Stable story IDs must match the photo-truth candidate identity. The ledger is non-public, non-authorizing and cannot itself prove SITE_PUBLISHED or delivery.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize verified Core v2 shadow articles for the site packaging stage")
    parser.add_argument("--ipj", required=True)
    parser.add_argument("--isu", required=True)
    parser.add_argument("--municipal", required=True)
    parser.add_argument("--isj-article", required=True)
    parser.add_argument("--isj-integrity", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        report = build_ledger(
            ipj=json.loads(Path(args.ipj).read_text(encoding="utf-8")),
            isu=json.loads(Path(args.isu).read_text(encoding="utf-8")),
            municipal=json.loads(Path(args.municipal).read_text(encoding="utf-8")),
            isj_article=json.loads(Path(args.isj_article).read_text(encoding="utf-8")),
            isj_integrity=json.loads(Path(args.isj_integrity).read_text(encoding="utf-8")),
        )
    except Exception as exc:
        report = {
            "schema_version": "1.0", "mode": MODE, "status": "BLOCKED", "publication_authority": "NONE",
            "acceptance_ready": False, "production_writer_ready": False, "site_publish_allowed": False, "social_publish_allowed": False,
            "article_count": 0, "rows": [], "reason": str(exc),
        }
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "reason": str(exc), "publication_authority": "NONE"}, ensure_ascii=False, sort_keys=True))
        return 1
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "article_count": report["article_count"], "source_article_counts": report["source_article_counts"], "publication_authority": "NONE", "acceptance_ready": False}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
