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
}

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
        return "REWRITE", "publication/distribution logic must obey Core v2 receipt contracts"
    if path.startswith(".github/workflows/"):
        if name in REWRITE_WORKFLOWS:
            return "REWRITE", "replace orchestration role with thin Core v2 executor"
        if name.startswith(("valcea-clar-", "local-news-os-", "local-news-vnext-")):
            return "RETIRE", "legacy orchestration surface after equivalent adapter is migrated"
        return "UNKNOWN", "outside bounded VÂLCEA CLAR/Core v2 migration scope"
    if path.startswith("valcea-clar/scripts/") and ("signal_adapter" in name or "reference_adapter" in name):
        return "KEEP", "source adapter/parser; call from Core v2 rather than own workflow"
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

    doc = {
        "schema_version": "1.0",
        "architecture_status": "LEGACY_NOT_PRODUCTION_READY",
        "scope": "VÂLCEA CLAR / Local News OS",
        "counts": counts,
        "publication_capable_paths": publication_paths,
        "items": items,
    }
    out = ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"counts": counts, "publication_capable_paths": len(publication_paths)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
