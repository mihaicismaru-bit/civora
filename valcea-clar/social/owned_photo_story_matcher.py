#!/usr/bin/env python3
"""Match VÂLCEA CLAR-owned Drive photos to published stories as candidates only.

The matcher operates on category metadata and published story text. It never
claims that a specific photograph depicts a story, never assigns a photo, and
never grants publication authority. Every suggested asset still requires
visual subject confirmation, rights reconfirmation, crop/alt-text review and
editor approval before story_visuals.json may be changed.
"""
from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
REGISTRY = SOCIAL / "owned_photo_registry.json"
POLICY = SOCIAL / "owned_photo_match_policy.json"
ARCHIVE = ROOT / "valcea-clar" / "site" / "story_archive.json"
VISUALS = SOCIAL / "story_visuals.json"
OUTPUT = SOCIAL / "owned_photo_story_candidates.json"


class MatchError(ValueError):
    pass


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise MatchError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise MatchError(f"expected JSON object: {path}")
    return value


def dump_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def norm(value: object) -> str:
    raw = str(value or "").casefold()
    folded = unicodedata.normalize("NFKD", raw)
    return " ".join("".join(ch for ch in folded if not unicodedata.combining(ch)).split())


def story_text(story: dict[str, Any]) -> str:
    # Deliberately exclude paragraphs/sources: a source mentioning an institution
    # must not make an unrelated story look like an institutional photo match.
    return norm(" ".join([
        str(story.get("id") or ""),
        str(story.get("section") or ""),
        str(story.get("headline") or ""),
        str(story.get("dek") or ""),
    ]))


def normalized_terms(raw: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for term, weight in raw.items():
        key = norm(term)
        if not key:
            continue
        out[key] = max(out.get(key, 0), int(weight))
    return out


def category_score(text: str, rule: dict[str, Any]) -> tuple[int, list[str], list[str]]:
    positive: list[str] = []
    negative: list[str] = []
    score = 0
    for term, weight in normalized_terms(rule.get("terms") or {}).items():
        if term in text:
            score += weight
            positive.append(term)
    penalty = int(rule.get("negative_penalty") or 0)
    for term in {norm(value) for value in (rule.get("negative_terms") or []) if norm(value)}:
        if term in text:
            score -= penalty
            negative.append(term)
    return max(score, 0), sorted(positive), sorted(negative)


def validate_policy(policy: dict[str, Any]) -> None:
    if policy.get("publication_authority") != "NONE":
        raise MatchError("matching policy must have publication_authority NONE")
    if policy.get("candidate_only") is not True:
        raise MatchError("matching policy must be candidate-only")
    if policy.get("automatic_story_assignment_allowed") is not False:
        raise MatchError("automatic story assignment must remain false")
    if policy.get("asset_subject_match_inherited_from_category") is not False:
        raise MatchError("category placement may not establish subject match")
    if policy.get("visual_confirmation_required") is not True:
        raise MatchError("visual confirmation must be required")
    if policy.get("rights_reconfirmation_required") is not True:
        raise MatchError("rights reconfirmation must be required")
    if int(policy.get("minimum_category_score") or 0) < 1:
        raise MatchError("minimum category score must be positive")
    if int(policy.get("max_candidates_per_story") or 0) < 1:
        raise MatchError("max candidate count must be positive")
    if not isinstance(policy.get("categories"), dict) or not policy["categories"]:
        raise MatchError("matching policy categories are required")


def validate_registry(registry: dict[str, Any]) -> None:
    if registry.get("publication_authority") != "NONE" or registry.get("candidate_only") is not True:
        raise MatchError("owned photo registry is not candidate-only")
    if registry.get("automatic_story_assignment_forbidden") is not True:
        raise MatchError("owned registry must forbid automatic story assignment")
    for asset in registry.get("assets") or []:
        if not isinstance(asset, dict):
            raise MatchError("owned registry contains non-object asset")
        if asset.get("kind") != "photograph" or asset.get("synthetic") is not False:
            raise MatchError("owned registry contains non-real-photo asset")
        if asset.get("subject_match") is not False or asset.get("editor_approved") is not False:
            raise MatchError("owned candidate already carries approval")
        if asset.get("publication_eligible") is not False or asset.get("publication_authority") != "NONE":
            raise MatchError("owned candidate gained publication authority")


def build_queue(
    archive: dict[str, Any],
    registry: dict[str, Any],
    visuals: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    validate_policy(policy)
    validate_registry(registry)

    stories = archive.get("stories") or []
    if not isinstance(stories, list):
        raise MatchError("story archive stories must be an array")
    visual_rows = visuals.get("stories") or {}
    if not isinstance(visual_rows, dict):
        raise MatchError("story_visuals stories must be an object")

    by_category: dict[str, list[dict[str, Any]]] = {}
    for asset in registry.get("assets") or []:
        category = str(asset.get("category") or "")
        if category:
            by_category.setdefault(category, []).append(asset)
    for assets in by_category.values():
        assets.sort(key=lambda row: (str(row.get("filename") or ""), str(row.get("asset_id") or "")))

    threshold = int(policy["minimum_category_score"])
    limit = int(policy["max_candidates_per_story"])
    category_rules = policy["categories"]
    rows: dict[str, Any] = {}

    for story in stories:
        if not isinstance(story, dict) or not story.get("id"):
            continue
        sid = str(story["id"])
        text = story_text(story)
        category_matches: list[dict[str, Any]] = []
        for category, rule in category_rules.items():
            if category not in by_category or not isinstance(rule, dict):
                continue
            score, positive, negative = category_score(text, rule)
            if score < threshold:
                continue
            category_matches.append({
                "category": category,
                "score": score,
                "positive_terms": positive,
                "negative_terms": negative,
            })
        category_matches.sort(key=lambda row: (-int(row["score"]), str(row["category"])))
        if not category_matches:
            continue

        candidates: list[dict[str, Any]] = []
        for match in category_matches:
            for asset in by_category[match["category"]]:
                candidates.append({
                    "asset_id": asset["asset_id"],
                    "drive_file_id": asset["drive_file_id"],
                    "filename": asset["filename"],
                    "source_url": asset["source_url"],
                    "category": asset["category"],
                    "category_relevance_score": match["score"],
                    "category_match_terms": match["positive_terms"],
                    "category_negative_terms": match["negative_terms"],
                    "captured_at_hint": asset.get("captured_at_hint", ""),
                    "creator_or_owner": asset.get("creator_or_owner", "VÂLCEA CLAR"),
                    "rights_basis": asset.get("rights_basis", "owned_pending_story_assignment"),
                    "rights_reconfirmation_required": True,
                    "requires_visual_confirmation": True,
                    "subject_match": False,
                    "editor_approved": False,
                    "publication_eligible": False,
                    "publication_authority": "NONE",
                    "blockers": [
                        "visual_subject_confirmation_required",
                        "rights_reconfirmation_required",
                        "editor_approval_required",
                    ],
                })
                if len(candidates) >= limit:
                    break
            if len(candidates) >= limit:
                break

        archive_visual_present = story.get("visual") not in (None, {}, "")
        explicit_visual_present = sid in visual_rows
        rows[sid] = {
            "story_id": sid,
            "headline": str(story.get("headline") or ""),
            "section": str(story.get("section") or ""),
            "canonical_url": str(story.get("canonical_url") or ""),
            "existing_visual": archive_visual_present or explicit_visual_present,
            "existing_story_visual_assignment": explicit_visual_present,
            "candidate_use_mode": "replacement_candidate" if (archive_visual_present or explicit_visual_present) else "missing_visual_candidate",
            "status": "OWNED_CANDIDATES_READY",
            "category_matches": category_matches,
            "candidate_count": len(candidates),
            "candidates": candidates,
            "automatic_story_assignment": False,
            "publication_authority": "NONE",
            "next_gate": "visual_subject_confirmation_plus_rights_reconfirmation_plus_editor_approval",
        }

    missing_visual = sum(1 for row in rows.values() if row["candidate_use_mode"] == "missing_visual_candidate")
    replacements = len(rows) - missing_visual
    candidate_links = sum(int(row.get("candidate_count") or 0) for row in rows.values())
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR OWNED PHOTO STORY CANDIDATES",
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_story_assignment_forbidden": True,
        "category_match_is_not_subject_match": True,
        "visual_confirmation_required": True,
        "rights_reconfirmation_required": True,
        "editor_approval_required": True,
        "source_registry": "valcea-clar/social/owned_photo_registry.json",
        "story_source": "valcea-clar/site/story_archive.json",
        "summary": {
            "published_story_count": sum(1 for row in stories if isinstance(row, dict) and row.get("id")),
            "owned_asset_count": int((registry.get("summary") or {}).get("asset_count") or len(registry.get("assets") or [])),
            "stories_with_owned_candidates": len(rows),
            "missing_visual_story_candidates": missing_visual,
            "replacement_story_candidates": replacements,
            "candidate_link_count": candidate_links,
        },
        "stories": dict(sorted(rows.items())),
    }


def enforce_queue_contract(queue: dict[str, Any]) -> None:
    if queue.get("publication_authority") != "NONE" or queue.get("candidate_only") is not True:
        raise MatchError("match queue gained publication authority")
    if queue.get("automatic_story_assignment_forbidden") is not True:
        raise MatchError("match queue permits automatic assignment")
    if queue.get("category_match_is_not_subject_match") is not True:
        raise MatchError("category match must not be treated as subject match")
    for sid, row in (queue.get("stories") or {}).items():
        if not isinstance(row, dict):
            raise MatchError(f"{sid}: invalid story row")
        if row.get("automatic_story_assignment") is not False or row.get("publication_authority") != "NONE":
            raise MatchError(f"{sid}: story row gained authority")
        for candidate in row.get("candidates") or []:
            if candidate.get("subject_match") is not False:
                raise MatchError(f"{sid}: category candidate inherited subject match")
            if candidate.get("editor_approved") is not False:
                raise MatchError(f"{sid}: candidate inherited editor approval")
            if candidate.get("publication_eligible") is not False or candidate.get("publication_authority") != "NONE":
                raise MatchError(f"{sid}: candidate gained publication eligibility")
            if candidate.get("requires_visual_confirmation") is not True or candidate.get("rights_reconfirmation_required") is not True:
                raise MatchError(f"{sid}: candidate missing mandatory gates")


def self_test() -> None:
    policy = {
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_story_assignment_allowed": False,
        "asset_subject_match_inherited_from_category": False,
        "visual_confirmation_required": True,
        "rights_reconfirmation_required": True,
        "max_candidates_per_story": 4,
        "minimum_category_score": 4,
        "categories": {
            "RIVER": {
                "terms": {"raul olanesti": 8, "olanesti": 1},
                "negative_terms": ["buila", "baile olanesti"],
                "negative_penalty": 8,
            },
            "ADMIN": {
                "terms": {"primaria": 5, "hcl": 4},
                "negative_terms": [],
                "negative_penalty": 0,
            },
        },
    }
    registry = {
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_story_assignment_forbidden": True,
        "summary": {"asset_count": 2},
        "assets": [
            {
                "asset_id": "river-1", "kind": "photograph", "synthetic": False,
                "drive_file_id": "a", "filename": "river.jpg", "category": "RIVER",
                "source_url": "https://drive.test/a", "creator_or_owner": "VÂLCEA CLAR",
                "rights_basis": "owned_pending_story_assignment", "captured_at_hint": "",
                "subject_match": False, "editor_approved": False,
                "publication_eligible": False, "publication_authority": "NONE",
            },
            {
                "asset_id": "admin-1", "kind": "photograph", "synthetic": False,
                "drive_file_id": "b", "filename": "admin.jpg", "category": "ADMIN",
                "source_url": "https://drive.test/b", "creator_or_owner": "VÂLCEA CLAR",
                "rights_basis": "owned_pending_story_assignment", "captured_at_hint": "",
                "subject_match": False, "editor_approved": False,
                "publication_eligible": False, "publication_authority": "NONE",
            },
        ],
    }
    archive = {
        "stories": [
            {"id": "olanesti-pod", "headline": "Lucrări la râul Olănești", "section": "ACTUALITATE", "dek": ""},
            {"id": "buila-accident", "headline": "Accident în Buila, acces din Băile Olănești", "section": "ACTUALITATE", "dek": ""},
            {"id": "hcl-310", "headline": "Primăria: HCL 310 intră în aplicare", "section": "ADMINISTRAȚIE", "dek": ""},
        ]
    }
    queue = build_queue(archive, registry, {"stories": {}}, policy)
    enforce_queue_contract(queue)
    assert "olanesti-pod" in queue["stories"]
    assert queue["stories"]["olanesti-pod"]["candidates"][0]["asset_id"] == "river-1"
    assert "buila-accident" not in queue["stories"]
    assert queue["stories"]["hcl-310"]["candidates"][0]["asset_id"] == "admin-1"
    print({"status": "PASS", "stories_with_candidates": len(queue["stories"])})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if args.validate_only:
        queue = load_json(args.output)
        enforce_queue_contract(queue)
        print({"status": "PASS", "summary": queue.get("summary")})
        return 0

    queue = build_queue(
        load_json(ARCHIVE),
        load_json(REGISTRY),
        load_json(VISUALS, {"stories": {}}),
        load_json(POLICY),
    )
    enforce_queue_contract(queue)
    dump_json(args.output, queue)
    print({"status": "PASS", "summary": queue["summary"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
