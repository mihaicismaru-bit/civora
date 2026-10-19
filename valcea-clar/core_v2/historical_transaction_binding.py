from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from historical_article_claims_evidence import build as build_historical_article_claims
from historical_fact_evidence_preflight import build as build_historical_fact_preflight
from historical_fact_kernel_evidence import build as build_historical_fact_kernels
from materialize_shadow_transactions import materialize


def _load(path: str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_bound_transactions(
    candidates: dict[str, Any],
    receipts: dict[str, Any],
    evidence_documents: list[tuple[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    facts_document = next(
        (
            document
            for source_name, document in evidence_documents
            if Path(source_name).name == "facts_registry.json" and isinstance(document, dict)
        ),
        None,
    )
    fact_preflight = (
        build_historical_fact_preflight(candidates, facts_document)
        if isinstance(facts_document, dict)
        else None
    )

    historical_kernels = build_historical_fact_kernels(candidates)
    historical_articles = build_historical_article_claims(candidates, historical_kernels)

    bound_documents = list(evidence_documents)
    bound_documents.append(("historical_fact_kernel_evidence", historical_kernels))
    bound_documents.append(("historical_article_claims_evidence", historical_articles))

    transactions = materialize(
        candidates,
        receipts,
        bound_documents,
        fact_preflight=fact_preflight,
        historical_kernel_evidence=historical_kernels,
    )
    transactions["historical_article_claims_evidence"] = {
        "schema_version": historical_articles.get("schema_version"),
        "candidate_count": historical_articles.get("candidate_count"),
        "article_claims_evidence_ready_count": historical_articles.get("article_claims_evidence_ready_count"),
        "publication_authority": historical_articles.get("publication_authority"),
        "live_promotion_allowed": historical_articles.get("live_promotion_allowed") is True,
        "states": {
            str(row.get("story_id")): row.get("state")
            for row in historical_articles.get("rows") or []
            if isinstance(row, dict) and row.get("story_id")
        },
    }
    transactions["truth_rule"] = (
        "Historical replay requires a field/claim evidence-bound Core v2 FactKernel and a separate "
        "claim-by-claim article package whose claims resolve to verified CLAIM_EVIDENCE from that same kernel. "
        "Neither artifact grants publication authority; external delivery evidence remains an independent gate."
    )
    return transactions, historical_kernels, historical_articles


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bind historical FactKernel + article claims evidence into Core v2 shadow transactions"
    )
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--receipts", required=True)
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--output", required=True)
    parser.add_argument("--kernels-output", required=True)
    parser.add_argument("--articles-output", required=True)
    args = parser.parse_args()

    candidates = _load(args.candidates)
    receipts = _load(args.receipts)
    evidence_documents = [(path, _load(path)) for path in args.evidence]

    transactions, historical_kernels, historical_articles = build_bound_transactions(
        candidates,
        receipts,
        evidence_documents,
    )

    Path(args.output).write_text(
        json.dumps(transactions, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.kernels_output).write_text(
        json.dumps(historical_kernels, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(args.articles_output).write_text(
        json.dumps(historical_articles, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    reasons: dict[str, int] = {}
    for row in transactions.get("rows") or []:
        reason = str(row.get("terminal_reason") or "AUDIT_REPLAY_READY")
        reasons[reason] = reasons.get(reason, 0) + 1

    print(
        json.dumps(
            {
                "candidate_count": transactions.get("candidate_count"),
                "historical_fact_kernel_evidence_ready_count": historical_kernels.get(
                    "fact_kernel_evidence_ready_count"
                ),
                "historical_article_claims_evidence_ready_count": historical_articles.get(
                    "article_claims_evidence_ready_count"
                ),
                "fully_bound_replay_count": transactions.get("fully_bound_replay_count"),
                "terminal_reasons": reasons,
                "publication_authority": "NONE",
                "acceptance_ready": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
