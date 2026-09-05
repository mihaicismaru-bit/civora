#!/usr/bin/env python3
"""Canonical VÂLCEA CLAR verified-fact orchestration boundary.

All production mutations of editorial/facts_registry.json are sequenced here.
Individual adapters may gather or transform evidence, but no separate workflow is
allowed to persist facts. This module performs no git operations and no public
site rendering; GitHub Actions owns persistence and Live Newsroom owns publishing.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCRIPTS = ROOT / "scripts"
EDITORIAL = ROOT / "editorial"


def run(script: str, *args: str, timeout: int = 300) -> None:
    command = [sys.executable, str(SCRIPTS / script), *args]
    subprocess.run(command, cwd=REPO, check=True, timeout=timeout)


def run_many(commands: Iterable[tuple[str, ...]]) -> None:
    for command in commands:
        run(command[0], *command[1:])


def run_scoped_nochange(
    script: str,
    *args: str,
    nochange_message: str,
    timeout: int = 300,
) -> bool:
    """Run one specialist adapter, allowing only its explicit NO_CHANGE outcome.

    A source/story-specific missing prerequisite must not abort unrelated verified
    facts in the same transaction. Every other failure remains fail-closed.
    """
    command = [sys.executable, str(SCRIPTS / script), *args]
    completed = subprocess.run(
        command,
        cwd=REPO,
        check=False,
        timeout=timeout,
        capture_output=True,
        text=True,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.returncode == 0:
        if completed.stderr:
            print(completed.stderr, end="", file=sys.stderr)
        return True

    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    if nochange_message in combined:
        print(json.dumps({
            "status": "NO_CHANGE",
            "scope": script,
            "reason": nochange_message.replace(" ", "_"),
        }, ensure_ascii=False))
        return False

    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    raise subprocess.CalledProcessError(completed.returncode, command)


def self_test() -> dict:
    commands = (
        ("council_watch_rm_valcea.py", "--self-test"),
        ("council_watch_rm_valcea_v2.py", "--self-test"),
        ("council_fact_kernel.py", "--self-test"),
        ("council_docmanager_embedded_resolver.py", "--resolver-self-test"),
        ("council_docmanager_embedded_resolver.py", "--self-test"),
        ("council_docmanager_diagnostic.py", "--self-test"),
        ("council_docmanager_document_diagnostic.py", "--self-test"),
        ("council_decision_document_resolver.py", "--self-test"),
        ("council_decision_article_engine.py", "--self-test"),
        ("council_decision_fulltext_enricher.py", "--self-test"),
        ("council_decision_fulltext_enricher_v2.py", "--self-test"),
        ("council_claim_attribution_normalizer.py", "--self-test"),
        ("compose_structured_alerts.py", "--self-test"),
        ("isu_valcea_homepage_summary_kernel.py", "--self-test"),
        ("verified_primary_fast_kernels.py", "--self-test"),
        ("promote_fact_kernels.py", "--self-test"),
        ("primary_source_admin_kernels.py", "--self-test"),
        ("primary_source_service_kernels.py", "--self-test"),
        ("promote_manual_publish_queue.py", "--self-test"),
        ("gambling_dossier_enricher_v2.py", "--self-test"),
        ("editorial_lifecycle_normalizer.py", "--self-test"),
        ("scm_program_fact_kernel.py", "--self-test"),
        ("scm_program_structure_diagnostic.py", "--self-test"),
    )
    run_many(commands)
    run("merge_supplemental_facts.py", "--check")
    result = {"status": "PASS", "mode": "self_test", "contracts": len(commands) + 1}
    print(json.dumps(result, ensure_ascii=False))
    return result


def check() -> dict:
    run("council_docmanager_embedded_resolver.py", "--check")
    run("council_decision_article_engine.py")
    run("merge_supplemental_facts.py", "--check")

    structured = EDITORIAL / "structured_alert_events.json"
    if structured.is_file() and structured.stat().st_size:
        run(
            "compose_structured_alerts.py",
            "--events", str(structured.relative_to(REPO)),
            "--facts-registry", "valcea-clar/editorial/facts_registry.json",
            "--no-write",
        )

    manual = EDITORIAL / "manual_publish_queue.json"
    if manual.is_file() and manual.stat().st_size:
        run("promote_manual_publish_queue.py")

    result = {
        "status": "PASS",
        "mode": "check",
        "structured_events_present": structured.is_file(),
        "manual_queue_present": manual.is_file(),
        "verified_primary_fast_lane_configured": True,
        "isu_homepage_summary_lane_configured": True,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def build() -> dict:
    # Council / official decisions.
    run("council_watch_rm_valcea_v2.py")
    run("council_decision_document_resolver.py", "--live", "--apply")
    run("council_docmanager_diagnostic.py")
    run("council_docmanager_embedded_resolver.py", "--live")
    run("council_docmanager_document_diagnostic.py")
    run("promote_fact_kernels.py", "--apply")
    run("council_decision_article_engine.py", "--apply")

    corpus = EDITORIAL / "council_decision_document_corpus.json"
    if corpus.is_file() and corpus.stat().st_size:
        run("council_decision_fulltext_enricher_v2.py", "--apply")
        run("council_claim_attribution_normalizer.py", "--apply")

    # Rapid primary structured events are evidence input only; composition into
    # facts happens here so the T1 ingest workflow never owns facts_registry.
    structured = EDITORIAL / "structured_alert_events.json"
    if structured.is_file() and structured.stat().st_size:
        run(
            "compose_structured_alerts.py",
            "--events", str(structured.relative_to(REPO)),
            "--facts-registry", "valcea-clar/editorial/facts_registry.json",
        )

    # The official ISU homepage also publishes a compact daily numeric tally.
    # Promote that low-risk self-reported summary only when all category counters
    # are present, reconcile exactly to the total and carry a fresh explicit date.
    # The adapter updates one continuous-story ID and remains inside this single
    # facts_registry transaction; it is not a parallel publishing lane.
    run("isu_valcea_homepage_summary_kernel.py", "--apply", timeout=60)

    # Fresh IPJ/ISU first-party detail evidence gets a bounded same-run promotion
    # path. The bridge itself fails closed per source/story, emits only attributed
    # kernels and never lets a secondary signal, allegation or title-only row
    # become publication authority. Normal Writer/Integrity/Newsroom gates remain.
    run("verified_primary_fast_kernels.py", "--apply", timeout=300)

    # Other verified official-source adapters.
    run("primary_source_service_kernels.py", "--apply")
    run("primary_source_admin_kernels.py", "--apply")

    # Verified supplemental festival / performing-arts dossiers are another
    # fact source, not a publication path. Merge them inside the same transaction.
    supplemental = EDITORIAL / "supplemental_facts_registry.json"
    if supplemental.is_file() and supplemental.stat().st_size:
        run("merge_supplemental_facts.py")

    # Human-approved intake is still only fact intake; it never renders or
    # publishes directly. Live Newsroom sees the resulting canonical facts.
    manual = EDITORIAL / "manual_publish_queue.json"
    if manual.is_file() and manual.stat().st_size:
        run("promote_manual_publish_queue.py", "--apply")

    # Durable specialist fact products and lifecycle normalization. The gambling
    # dossier is scoped to one explainer. Its explicit unavailable-target outcome
    # is NO_CHANGE for that story only; any other enrichment or temporal-contract
    # failure still aborts the fact transaction.
    gambling_enrichment_applied = run_scoped_nochange(
        "gambling_dossier_enricher_v2.py",
        nochange_message="canonical verified gambling fact unavailable",
    )
    if gambling_enrichment_applied:
        run("gambling_dossier_enricher_v2.py", "--check")

    run("editorial_lifecycle_normalizer.py", "--apply")
    run("scm_program_structure_diagnostic.py")
    run("scm_program_fact_kernel.py")

    # Persist editorial products from the final canonical fact registry before
    # validating the registry-wide contract. The writer's normal mode writes the
    # product registry; --check is intentionally read-only validation only.
    run("editorial_writer.py")
    run("editorial_writer.py", "--check")

    result = {
        "status": "PASS",
        "mode": "build",
        "facts_single_writer": True,
        "verified_primary_fast_lane": True,
        "isu_homepage_summary_lane": True,
        "structured_events_consumed": structured.is_file(),
        "supplemental_facts_consumed": supplemental.is_file(),
        "manual_queue_consumed": manual.is_file(),
        "council_document_corpus_present": corpus.is_file(),
        "gambling_enrichment_applied": gambling_enrichment_applied,
    }
    print(json.dumps(result, ensure_ascii=False))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    elif args.check:
        check()
    else:
        build()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())