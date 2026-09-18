from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable

from contracts import ContractViolation, Visual
from visual_readback import ALLOWED_RIGHTS_BASES, _read_binary_head, _read_text


PHOTO_GATE_SCHEMA_VERSION = "1.0"


def _candidate_id(row: dict[str, Any], *, source_label: str) -> str:
    explicit = str(row.get("story_id") or row.get("article_id") or row.get("detail_id") or "").strip()
    if explicit:
        return explicit
    decision_number = row.get("decision_number")
    if decision_number is not None:
        return f"hcl-{decision_number}"
    return f"{source_label}:unknown"


def iter_written_candidates(document: dict[str, Any], *, source_label: str) -> Iterable[dict[str, Any]]:
    for row in document.get("rows") or []:
        if row.get("state") != "VERIFIED_WRITTEN_SHADOW":
            continue
        articles = row.get("articles")
        if isinstance(articles, list) and articles:
            for article in articles:
                if not isinstance(article, dict):
                    continue
                yield {
                    "candidate_id": str(article.get("article_id") or _candidate_id(row, source_label=source_label)),
                    "source_label": source_label,
                    "where": str((article.get("fact_kernel") or {}).get("where") or "").strip(),
                    "who": str((article.get("fact_kernel") or {}).get("who") or "").strip(),
                    "headline": str((article.get("article_package") or {}).get("headline") or "").strip(),
                }
            continue
        yield {
            "candidate_id": _candidate_id(row, source_label=source_label),
            "source_label": source_label,
            "where": str((row.get("fact_kernel") or {}).get("where") or "").strip(),
            "who": str((row.get("fact_kernel") or {}).get("who") or "").strip(),
            "headline": str((row.get("article_package") or {}).get("headline") or "").strip(),
        }


def _atlas_assets_for_story(atlas: dict[str, Any], story_id: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for asset in atlas.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        if story_id in {str(value) for value in asset.get("source_story_ids") or []}:
            matches.append(asset)
    return matches


def _external_provenance_probe(image: dict[str, Any], *, timeout: float) -> dict[str, Any]:
    source_url = str(image.get("source_url") or "").strip()
    direct_source_url = str(image.get("direct_source_url") or "").strip()
    source = _read_text(source_url, timeout=timeout) if source_url else {
        "status": "FAILED",
        "readback_ok": False,
        "reason": "missing_source_url",
    }
    direct = _read_binary_head(direct_source_url, timeout=timeout) if direct_source_url else {
        "status": "FAILED",
        "readback_ok": False,
        "reason": "missing_direct_source_url",
    }
    return {
        "source": {key: value for key, value in source.items() if key != "body"},
        "direct_source": direct,
        "readback_ok": bool(source.get("readback_ok") and direct.get("readback_ok")),
    }


def assess_story_visual(
    story_id: str,
    *,
    visual_registry: dict[str, Any],
    atlas: dict[str, Any] | None = None,
    external_probe: bool = False,
    timeout: float = 12.0,
) -> dict[str, Any]:
    stories = visual_registry.get("stories") or {}
    assigned = stories.get(story_id)
    if not isinstance(assigned, dict):
        atlas_matches = _atlas_assets_for_story(atlas or {}, story_id)
        if atlas_matches:
            return {
                "story_id": story_id,
                "status": "BLOCKED",
                "reason": "atlas_asset_does_not_inherit_story_approval",
                "atlas_asset_ids": [str(item.get("asset_id") or "") for item in atlas_matches],
                "publication_authority": "NONE",
                "social_publish_allowed": False,
            }
        return {
            "story_id": story_id,
            "status": "BLOCKED",
            "reason": "no_story_specific_approved_visual",
            "publication_authority": "NONE",
            "social_publish_allowed": False,
        }

    image = assigned.get("image") or {}
    if not isinstance(image, dict):
        return {
            "story_id": story_id,
            "status": "BLOCKED",
            "reason": "story_visual_missing_image_contract",
            "publication_authority": "NONE",
            "social_publish_allowed": False,
        }

    problems: list[str] = []
    kind = str(image.get("kind") or "")
    synthetic = bool(image.get("synthetic"))
    subject_match = image.get("subject_match") is True
    editor_approved = image.get("editor_approved") is True
    rights_basis = str(image.get("rights_basis") or "").strip()
    source_url = str(image.get("source_url") or "").strip()
    direct_source_url = str(image.get("direct_source_url") or "").strip()
    contextual_archive = image.get("contextual_archive") is True
    disclosure = str(image.get("editorial_note") or "").strip()

    if kind != "photograph":
        problems.append("not_real_photograph")
    if synthetic:
        problems.append("synthetic_as_photo_forbidden")
    if not subject_match:
        problems.append("subject_match_not_proven")
    if not editor_approved:
        problems.append("editor_approval_missing")
    if rights_basis not in ALLOWED_RIGHTS_BASES:
        problems.append("rights_basis_not_allowed")
    if not source_url.startswith("https://"):
        problems.append("provenance_source_url_missing_or_insecure")
    if not direct_source_url.startswith("https://"):
        problems.append("direct_image_url_missing_or_insecure")
    if contextual_archive and not disclosure:
        problems.append("archive_context_disclosure_missing")

    semantic_relevance = "archive_context" if contextual_archive else "exact"
    if not problems:
        try:
            Visual(
                kind=kind,
                synthetic=synthetic,
                source_url=source_url,
                rights_basis=rights_basis,
                semantic_relevance=semantic_relevance,
                editor_approved=editor_approved,
                contextual_archive=contextual_archive,
                context_disclosure=disclosure or None,
                credit=str(image.get("credit") or "").strip() or None,
            ).validate_for_social()
        except ContractViolation as exc:
            problems.append(f"visual_contract:{exc}")

    external = {"status": "NOT_PROBED", "readback_ok": False}
    if not problems and external_probe:
        external = _external_provenance_probe(image, timeout=timeout)
        if not external.get("readback_ok"):
            problems.append("external_provenance_or_image_readback_failed")

    passed = not problems
    return {
        "story_id": story_id,
        "status": "VISUAL_CANDIDATE_VERIFIED_SHADOW" if passed else "BLOCKED",
        "reason": None if passed else problems[0],
        "problems": problems,
        "publication_authority": "NONE",
        "social_publish_allowed": False,
        "visual_ready_for_future_site_binding": passed,
        "article_binding_verified": False,
        "semantic_relevance": semantic_relevance,
        "rights_basis": rights_basis,
        "image_path": str(assigned.get("image_path") or "").strip(),
        "source_url": source_url,
        "direct_source_url": direct_source_url,
        "context_disclosure": disclosure or None,
        "external_readback": external,
    }


def build_photo_truth_report(
    inputs: list[tuple[str, dict[str, Any]]],
    *,
    visual_registry: dict[str, Any],
    atlas: dict[str, Any],
    external_probe: bool = False,
    timeout: float = 12.0,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for source_label, document in inputs:
        candidates.extend(iter_written_candidates(document, source_label=source_label))

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        story_id = str(candidate["candidate_id"])
        if story_id in seen:
            continue
        seen.add(story_id)
        decision = assess_story_visual(
            story_id,
            visual_registry=visual_registry,
            atlas=atlas,
            external_probe=external_probe,
            timeout=timeout,
        )
        decision["source_label"] = candidate["source_label"]
        decision["headline"] = candidate["headline"]
        decision["where"] = candidate["where"]
        decision["who"] = candidate["who"]
        rows.append(decision)

    ready = sum(row.get("status") == "VISUAL_CANDIDATE_VERIFIED_SHADOW" for row in rows)
    blocked = sum(row.get("status") == "BLOCKED" for row in rows)
    return {
        "schema_version": PHOTO_GATE_SCHEMA_VERSION,
        "mode": "PHOTO_TRUTH_GATE_SHADOW",
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "external_probe_enabled": external_probe,
        "candidate_count": len(rows),
        "visual_candidate_verified_shadow_count": ready,
        "blocked_count": blocked,
        "rows": rows,
        "truth_rule": (
            "Only a story-specific approved real photograph with proven subject relevance, allowed rights metadata, "
            "archive disclosure when applicable, and successful external provenance/image readback when probing is enabled "
            "may become a Core v2 visual candidate. Atlas membership or text-card output never implies story approval. "
            "Public article binding remains a later independent readback gate."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate Core v2 story visuals fail-closed in shadow mode")
    parser.add_argument("--input", action="append", default=[], help="LABEL=path-to-shadow-json")
    parser.add_argument("--visual-registry", default="valcea-clar/social/story_visuals.json")
    parser.add_argument("--atlas", default="valcea-clar/social/photo_atlas.json")
    parser.add_argument("--external-probe", action="store_true")
    parser.add_argument("--timeout", type=float, default=12.0)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    inputs: list[tuple[str, dict[str, Any]]] = []
    for item in args.input:
        if "=" not in item:
            raise SystemExit("--input must be LABEL=PATH")
        label, path = item.split("=", 1)
        inputs.append((label.strip(), json.loads(Path(path).read_text(encoding="utf-8"))))

    report = build_photo_truth_report(
        inputs,
        visual_registry=json.loads(Path(args.visual_registry).read_text(encoding="utf-8")),
        atlas=json.loads(Path(args.atlas).read_text(encoding="utf-8")),
        external_probe=args.external_probe,
        timeout=args.timeout,
    )
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS_SHADOW",
        "candidate_count": report["candidate_count"],
        "visual_candidate_verified_shadow_count": report["visual_candidate_verified_shadow_count"],
        "blocked_count": report["blocked_count"],
        "external_probe_enabled": report["external_probe_enabled"],
        "publication_authority": "NONE",
        "acceptance_ready": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
