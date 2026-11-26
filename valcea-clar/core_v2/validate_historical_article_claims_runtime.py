from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _index(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("story_id") or ""): row
        for row in document.get("rows") or []
        if isinstance(row, dict) and str(row.get("story_id") or "").strip()
    }


def validate(
    candidates: dict[str, Any],
    kernels: dict[str, Any],
    articles: dict[str, Any],
    transactions: dict[str, Any],
) -> None:
    assert kernels.get("publication_authority") == "NONE"
    assert articles.get("publication_authority") == "NONE"
    assert transactions.get("publication_authority") == "NONE"
    assert articles.get("live_promotion_allowed") is False
    assert articles.get("site_publish_allowed") is False
    assert articles.get("social_publish_allowed") is False
    assert transactions.get("acceptance_ready") is False

    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]
    kernel_rows = _index(kernels)
    article_rows = _index(articles)
    transaction_rows = _index(transactions)

    assert int(kernels.get("fact_kernel_evidence_ready_count") or 0) == len(story_ids)
    assert int(articles.get("article_claims_evidence_ready_count") or 0) == len(story_ids)

    for story_id in story_ids:
        kernel_row = kernel_rows.get(story_id)
        article_row = article_rows.get(story_id)
        transaction = transaction_rows.get(story_id)
        assert isinstance(kernel_row, dict), f"{story_id}: missing historical kernel row"
        assert isinstance(article_row, dict), f"{story_id}: missing historical article row"
        assert isinstance(transaction, dict), f"{story_id}: missing transaction row"

        assert kernel_row.get("state") == "FACT_KERNEL_EVIDENCE_READY_SHADOW"
        assert kernel_row.get("fact_kernel_evidence_ready") is True
        kernel = kernel_row.get("fact_kernel")
        assert isinstance(kernel, dict)
        kernel_claims = [str(value) for value in kernel.get("claims") or []]
        kernel_evidence_ids = {str(value) for value in kernel.get("evidence_ids") or []}
        assert kernel_claims
        assert kernel_evidence_ids

        assert article_row.get("state") == "ARTICLE_CLAIMS_EVIDENCE_READY_SHADOW"
        assert article_row.get("article_claims_evidence_ready") is True
        package = article_row.get("article_package")
        assert isinstance(package, dict)
        assert package.get("publication_authority") == "NONE"
        assert package.get("site_publish_allowed") is False
        assert package.get("social_publish_allowed") is False
        assert package.get("kernel_fingerprint_sha256") == _canonical_hash(kernel)

        package_claims = package.get("claims") or []
        assert len(package_claims) == len(kernel_claims)
        for index, claim in enumerate(package_claims):
            assert claim.get("kernel_claim_index") == index
            assert str(claim.get("text") or "") == kernel_claims[index]
            evidence_ids = {str(value) for value in claim.get("evidence_ids") or []}
            assert evidence_ids
            assert evidence_ids <= kernel_evidence_ids
            fingerprints = claim.get("evidence_fingerprints") or []
            assert len(fingerprints) == len(evidence_ids)
            for fingerprint in fingerprints:
                assert fingerprint.get("evidence_id") in evidence_ids
                assert fingerprint.get("source_url")
                assert len(str(fingerprint.get("source_content_sha256") or "")) == 64

        integrity = transaction.get("integrity")
        assert isinstance(integrity, dict), f"{story_id}: transaction did not reach editorial integrity"
        assert integrity.get("status") == "PASS"
        assert int(integrity.get("fabricated_claims") or 0) == 0
        assert int(integrity.get("bound_claims") or 0) == len(kernel_claims)
        assert transaction.get("terminal_reason") != "BLOCKED_EXPLICIT_ARTICLE_CLAIMS_EVIDENCE"
        assert transaction.get("article_claim_count") == len(kernel_claims)
        assert int(transaction.get("article_body_chars") or 0) >= 180

    summary = transactions.get("historical_article_claims_evidence") or {}
    assert int(summary.get("article_claims_evidence_ready_count") or 0) == len(story_ids)
    assert summary.get("publication_authority") == "NONE"
    assert summary.get("live_promotion_allowed") is False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate historical FactKernel -> article claims -> transaction binding")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--kernels", required=True)
    parser.add_argument("--articles", required=True)
    parser.add_argument("--transactions", required=True)
    args = parser.parse_args()

    candidates = _load(args.candidates)
    kernels = _load(args.kernels)
    articles = _load(args.articles)
    transactions = _load(args.transactions)
    validate(candidates, kernels, articles, transactions)

    print(
        json.dumps(
            {
                "candidate_count": len(candidates.get("first_ten_candidate_ids") or []),
                "historical_fact_kernel_evidence_ready_count": kernels.get("fact_kernel_evidence_ready_count"),
                "historical_article_claims_evidence_ready_count": articles.get("article_claims_evidence_ready_count"),
                "fully_bound_replay_count": transactions.get("fully_bound_replay_count"),
                "publication_authority": "NONE",
                "acceptance_ready": False,
                "status": "PASS_SHADOW",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
