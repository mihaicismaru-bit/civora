from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

REWRITE_WORKFLOWS = {
    "valcea-clar-newsroom-live.yml",
    "valcea-clar-social-publishing.yml",
    "valcea-clar-public-health.yml",
    "valcea-clar-public-media-health.yml",
    "valcea-clar-fact-kernel.yml",
    "valcea-clar-editorial-writer.yml",
    "valcea-clar-photo-candidate-discovery.yml",
    "valcea-clar-owned-photo-ingest.yml",
}

KEEP_DATA = {
    "valcea-clar/site/story_archive.json",
    "valcea-clar/site/runtime/stiri/manifest.json",
    "valcea-clar/editorial/facts_registry.json",
    "valcea-clar/editorial/fact_kernel_registry.json",
    "valcea-clar/social/story_visuals.json",
    "valcea-clar/social/photo_atlas.json",
    "valcea-clar/social/meta_auth_state.json",
}

REWRITE_CODE = {
    "valcea-clar/social/facebook_editorial_publish.py",
    "valcea-clar/social/instagram_editorial_publish.py",
    "valcea-clar/social/instagram_fact_card_publish.py",
    "valcea-clar/social/facebook_text_fallback.py",
    "valcea-clar/scripts/newsroom_decide.py",
    "valcea-clar/scripts/council_decision_article_engine.py",
    "valcea-clar/scripts/editorial_integrity.py",
    "valcea-clar/scripts/editorial_lifecycle_normalizer.py",
    "valcea-clar/scripts/editorial_opportunity_engine.py",
    "valcea-clar/scripts/editorial_writer.py",
    "valcea-clar/scripts/editorial_writer_quality_gate.py",
    "valcea-clar/scripts/fact_kernel_orchestrator.py",
    "valcea-clar/scripts/promote_fact_kernels.py",
    "valcea-clar/scripts/promote_manual_publish_queue.py",
    "valcea-clar/scripts/premium_story_integrity.py",
}

RETIRE_SCRIPT_EXACT = {
    "compose_structured_alerts.py",
    "gambling_story_presentation.py",
    "generate_edition.py",
    "overlay_runtime_export.py",
    "premium_presentation.py",
    "repair_continuous_frontpage.py",
    "repair_continuous_frontpage_legacy.py",
}

KEEP_SCRIPT_EXACT = {
    "apavil_valcea_service_thread_state.py",
    "audit_automation_surface.py",
    "discovery_snapshot_material.py",
    "gambing_dossier_enricher.py",
    "gambling_dossier_enricher.py",
    "gambling_dossier_enricher_v2.py",
    "infrastructure_watch.py",
    "market_intelligence_watch.py",
    "merge_supplemental_facts.py",
    "monitor_ledger.py",
    "performing_arts_opportunity_adapter.py",
    "primary_source_admin_kernels.py",
    "primary_source_service_kernels.py",
    "promote_performing_arts_monitors.py",
    "promote_verified_venues.py",
    "prune_volatile_json_changes.py",
    "quarantine_venue_identity_collisions.py",
    "reconcile_ingest.py",
    "smoke_web.py",
    "source_intelligence_discover.py",
    "verified_primary_fast_kernels.py",
}

KEEP_SCRIPT_PREFIXES = (
    "discover_",
    "enrich_",
    "link_",
    "monitor_",
    "probe_",
    "test_",
    "traffic_",
    "validate_",
)

KEEP_SCRIPT_MARKERS = (
    "_diagnostic",
    "_detail_evidence",
    "_enricher",
    "_kernel",
    "_kernels",
    "_normalizer",
    "_resolver",
    "_state",
    "_thread_state",
    "_watch",
    "crossref",
    "historical_detail_reconciliation",
    "reference_context_engine",
    "reference_correlator",
    "temporal_evidence",
)

RETIRE_SCRIPT_PREFIXES = (
    "build_",
    "public_ux_",
    "render_",
)

PUBLISH_TOKENS = (
    "--apply",
    "graph.facebook.com",
    "facebook_post_id",
    "instagram_media_id",
    "git push origin HEAD:main",
    "story_publication_event",
    "site/runtime",
)


def classify(path: str) -> tuple[str, str]:
    name = Path(path).name
    if path in KEEP_DATA:
        return "KEEP", "durable canonical data/evidence"
    if path in REWRITE_CODE:
        return "REWRITE", "execution/editorial side effects must obey Core v2 truth contracts"
    if path.startswith(".github/workflows/"):
        if name in REWRITE_WORKFLOWS:
            return "REWRITE", "replace orchestration role with thin Core v2 executor"
        if name.startswith(("valcea-clar-", "local-news-os-", "local-news-vnext-")):
            return "RETIRE", "legacy orchestration surface after equivalent adapter is migrated"
        return "UNKNOWN", "outside bounded VÂLCEA CLAR/Core v2 migration scope"
    if path.startswith("valcea-clar/scripts/"):
        if "signal_adapter" in name or "reference_adapter" in name:
            return "KEEP", "source adapter/parser; call from Core v2 rather than own workflow"
        if name in RETIRE_SCRIPT_EXACT or name.startswith(RETIRE_SCRIPT_PREFIXES):
            return "RETIRE", "legacy renderer/presentation/projection path superseded by Core v2"
        if name in KEEP_SCRIPT_EXACT or name.startswith(KEEP_SCRIPT_PREFIXES) or any(marker in name for marker in KEEP_SCRIPT_MARKERS):
            return "KEEP", "reusable source/evidence/verification/support component; no publication authority implied"
        return "UNKNOWN", "script role requires explicit migration review"
    if path.startswith("valcea-clar/social/") and path.endswith(".py"):
        if any(key in name for key in ("publish", "preview", "outbox", "fallback")):
            return "REWRITE", "social side-effect or preview/outbox path"
        return "KEEP", "supporting media/provenance component subject to Core v2 contract tests"
    if path.startswith("local-news-os/core/") and path.endswith(".py"):
        return "KEEP", "shared discovery/verification component"
    return "UNKNOWN", "requires explicit migration review"


def iter_scope() -> list[Path]:
    candidates: list[Path] = []
    workflows = ROOT / ".github" / "workflows"
    if workflows.exists():
        candidates.extend(
            p for p in workflows.glob("*.yml")
            if p.name.startswith(("valcea-clar-", "local-news-os-", "local-news-vnext-"))
        )
    for base in (
        ROOT / "valcea-clar" / "scripts",
        ROOT / "valcea-clar" / "social",
        ROOT / "local-news-os" / "core",
    ):
        if base.exists():
            candidates.extend(p for p in base.glob("*.py"))
    for rel in KEEP_DATA:
        p = ROOT / rel
        if p.exists():
            candidates.append(p)
    return sorted(set(candidates))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="valcea-clar/core_v2/legacy_inventory.generated.json")
    args = parser.parse_args()

    items = []
    publication_paths = []
    counts = {"KEEP": 0, "RETIRE": 0, "REWRITE": 0, "UNKNOWN": 0}
    for path in iter_scope():
        rel = path.relative_to(ROOT).as_posix()
        disposition, reason = classify(rel)
        counts[disposition] += 1
        text = ""
        if path.is_file() and path.stat().st_size < 250_000:
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass
        matched = sorted(token for token in PUBLISH_TOKENS if token in text)
        if matched:
            publication_paths.append({"path": rel, "tokens": matched})
        items.append({"path": rel, "disposition": disposition, "reason": reason, "publication_tokens": matched})

    unknown_paths = [item["path"] for item in items if item["disposition"] == "UNKNOWN"]
    doc = {
        "schema_version": "1.1",
        "architecture_status": "LEGACY_NOT_PRODUCTION_READY",
        "scope": "VÂLCEA CLAR / Local News OS",
        "classification_note": "KEEP means reusable component/data only; it does not enable the component in the bounded pilot and grants no publication authority.",
        "counts": counts,
        "unknown_paths": unknown_paths,
        "publication_capable_paths": publication_paths,
        "items": items,
    }
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "unknown_paths": unknown_paths, "publication_capable_paths": len(publication_paths)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
