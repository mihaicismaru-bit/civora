from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from validate_shadow_runtime import validate


RUNTIME_FILES = (
    "valcea-core-v2-apavil-shadow.json",
    "valcea-core-v2-ipj-shadow.json",
    "valcea-core-v2-isu-shadow.json",
    "valcea-core-v2-municipal-shadow.json",
    "valcea-core-v2-municipal-documents.json",
    "valcea-core-v2-municipal-materiality.json",
    "valcea-core-v2-municipal-fact-kernels.json",
    "valcea-core-v2-municipal-articles.json",
    "valcea-core-v2-cj-road-shadow.json",
    "valcea-core-v2-eta-shadow.json",
    "valcea-core-v2-isj-shadow.json",
    "valcea-core-v2-isj-detail-shadow.json",
    "valcea-core-v2-isj-materiality-shadow.json",
    "valcea-core-v2-isj-embedded-notice-shadow.json",
    "valcea-core-v2-isj-fact-kernel-shadow.json",
    "valcea-core-v2-isj-fact-kernel-integrity-shadow.json",
    "valcea-core-v2-isj-article-shadow.json",
    "valcea-core-v2-isj-article-integrity-shadow.json",
    "valcea-core-v2-photo-truth.json",
    "valcea-core-v2-shadow-site-package.json",
    "valcea-core-v2-shadow-candidates.json",
    "valcea-core-v2-site-readback.json",
    "valcea-core-v2-visual-readback.json",
    "valcea-core-v2-meta-readback.json",
    "valcea-core-v2-shadow-receipts.json",
    "valcea-core-v2-shadow-transactions.json",
    "valcea-core-v2-gate-report.json",
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, doc: dict) -> None:
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _case_base(source_base: Path, copied_file: str) -> tuple[tempfile.TemporaryDirectory, Path]:
    td = tempfile.TemporaryDirectory(prefix="valcea-core-v2-negative-")
    case_base = Path(td.name)
    for name in RUNTIME_FILES:
        source = source_base / name
        if not source.is_file():
            td.cleanup()
            raise FileNotFoundError(f"Missing runtime artifact required for negative regression: {source}")
        destination = case_base / name
        if name == copied_file:
            shutil.copy2(source, destination)
        else:
            os.symlink(source, destination)
    return td, case_base


def _expect_fail_closed(
    source_base: Path,
    repo: Path,
    target_file: str,
    mutate: Callable[[dict], None],
    label: str,
) -> None:
    td, case_base = _case_base(source_base, target_file)
    try:
        target = case_base / target_file
        doc = _load(target)
        mutate(doc)
        _write(target, doc)
        try:
            validate(case_base, repo)
        except AssertionError:
            print(f"negative runtime regression PASS (fail-closed): {label}")
            return
        raise AssertionError(f"Canonical runtime validator accepted tampered cross-artifact truth: {label}")
    finally:
        td.cleanup()


def run(base: Path, repo: Path) -> None:
    # Establish that these regressions are running against a valid natural runtime
    # corpus before mutating one artifact at a time.
    validate(base, repo)

    def mutate_article_kernel_source(doc: dict) -> None:
        doc["articles"][0]["fact_kernel"]["source_url"] = "https://invalid.example/isj-source-tamper"

    def mutate_article_claim_cardinality(doc: dict) -> None:
        claims = doc["articles"][0]["article_package"]["claims"]
        assert len(claims) >= 2
        claims.pop()

    def mutate_integrity_article_id(doc: dict) -> None:
        doc["verified_candidates"][0]["article_id"] = "tampered-isj-article-id"

    def mutate_integrity_source_binding(doc: dict) -> None:
        doc["verified_candidates"][0]["source_url"] = "https://invalid.example/isj-source-binding"

    def mutate_kernel_source_identity(doc: dict) -> None:
        doc["kernels"][0]["fact_kernel"]["source_url"] = "https://invalid.example/isj-kernel-source"

    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-shadow.json",
        mutate_article_kernel_source,
        "article embeds a fact kernel with a different source identity",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-shadow.json",
        mutate_article_claim_cardinality,
        "article claim cardinality diverges from the verified FactKernel",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-integrity-shadow.json",
        mutate_integrity_article_id,
        "article-integrity candidate points at a different article id",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-article-integrity-shadow.json",
        mutate_integrity_source_binding,
        "article-integrity candidate points at a different source URL",
    )
    _expect_fail_closed(
        base,
        repo,
        "valcea-core-v2-isj-fact-kernel-shadow.json",
        mutate_kernel_source_identity,
        "FactKernel source identity is mutated away from the verified ISJ source",
    )

    print("Core v2 late-ISJ negative runtime regressions: PASS (5/5 fail-closed)")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prove canonical Core v2 runtime validation rejects late-ISJ cross-artifact tampering"
    )
    parser.add_argument("--base", default="/tmp")
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    run(Path(args.base).resolve(), Path(args.repo).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
