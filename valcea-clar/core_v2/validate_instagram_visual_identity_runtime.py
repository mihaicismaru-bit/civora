from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def validate(
    candidates: dict[str, Any],
    meta: dict[str, Any],
    identity: dict[str, Any],
    receipts: dict[str, Any],
) -> None:
    assert identity.get("publication_authority") == "NONE"
    assert identity.get("acceptance_ready") is False
    assert str(identity.get("schema_version") or "").startswith("1.")

    wanted = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]
    candidate_index = {
        str(row.get("story_id") or ""): row
        for row in candidates.get("rows") or []
        if isinstance(row, dict) and row.get("story_id")
    }
    meta_index = {
        str(row.get("story_id") or ""): row
        for row in meta.get("results") or []
        if isinstance(row, dict)
        and row.get("channel") == "instagram"
        and row.get("story_id")
    }
    identity_index = {
        str(row.get("story_id") or ""): row
        for row in identity.get("results") or []
        if isinstance(row, dict) and row.get("story_id")
    }
    receipt_index = {
        str(row.get("story_id") or ""): row
        for row in receipts.get("rows") or []
        if isinstance(row, dict) and row.get("story_id")
    }

    assert set(identity_index) == set(wanted), "identity ledger story set drifted from replay candidates"
    assert int(identity.get("candidate_count") or 0) == len(wanted)

    bound_ids: list[str] = []
    for story_id in wanted:
        candidate = candidate_index[story_id]
        meta_row = meta_index.get(story_id) or {}
        row = identity_index[story_id]
        receipt = ((receipt_index.get(story_id) or {}).get("receipts") or {}).get("instagram") or {}

        assert row.get("publication_authority") == "NONE"
        assert row.get("approved_visual_path") == candidate.get("visual_image_path")
        assert row.get("approved_visual_filename") == candidate.get("visual_filename")
        assert row.get("comparison_method") == "imagemagick_rgb64_unique_match_v2"

        thresholds = row.get("thresholds") or {}
        assert float(thresholds.get("correlation_min") or 0.0) >= 0.80
        assert float(thresholds.get("mae_max") or 1.0) <= 0.12
        assert float(thresholds.get("composite_min") or 0.0) >= 0.70
        assert float(thresholds.get("match_margin_min") or 0.0) >= 0.20

        external_remote_ids = {
            str(item.get("remote_id") or "")
            for item in meta_row.get("remote_media_results") or []
            if isinstance(item, dict) and item.get("readback_ok") is True and item.get("remote_id")
        }
        compared_remote_ids = {
            str(item.get("remote_id") or "")
            for item in row.get("candidate_results") or []
            if isinstance(item, dict) and item.get("remote_id")
        }
        assert compared_remote_ids <= external_remote_ids, "identity compared a remote image not externally read back"

        bound = row.get("identity_bound") is True
        assert receipt.get("remote_visual_identity_bound") is bound, "receipt identity truth drifted from independent identity ledger"
        assert receipt.get("remote_visual_identity_state") == row.get("identity_state")
        assert receipt.get("remote_visual_identity_method") == row.get("comparison_method")

        passing = [item for item in row.get("candidate_results") or [] if isinstance(item, dict) and item.get("same_visual") is True]
        if bound:
            assert candidate.get("real_visual_internal_evidence") is True
            assert row.get("identity_state") == "APPROVED_VISUAL_MATCHED_REMOTE_IMAGE_UNIQUE"
            assert len(passing) == 1
            assert int(row.get("passing_candidate_count") or 0) == 1
            assert row.get("matched_remote_id") == passing[0].get("remote_id")
            assert str(row.get("matched_remote_id") or "") in external_remote_ids
            assert float(row.get("match_margin") or 0.0) >= float(row.get("match_margin_min") or 0.20)
            assert receipt.get("remote_visual_identity_matched_remote_id") == row.get("matched_remote_id")
            bound_ids.append(story_id)
        else:
            assert receipt.get("remote_visual_identity_bound") is not True
            assert row.get("identity_state") in {
                "BLOCKED_IMAGEMAGICK_UNAVAILABLE",
                "BLOCKED_APPROVED_VISUAL_NOT_READY",
                "BLOCKED_NO_REMOTE_IMAGE_READBACK",
                "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL",
                "AMBIGUOUS_MULTIPLE_REMOTE_MATCHES",
                "BLOCKED_INSUFFICIENT_UNIQUENESS_MARGIN",
            }

    assert int(identity.get("identity_bound_count") or 0) == len(bound_ids)
    assert set(identity.get("identity_bound_story_ids") or []) == set(bound_ids)
    assert int(receipts.get("instagram_visual_identity_bound_count") or 0) == len(bound_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Instagram visual identity cross-artifact runtime truth")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--receipts", required=True)
    args = parser.parse_args()
    validate(
        _load(args.candidates),
        _load(args.meta_readback),
        _load(args.identity),
        _load(args.receipts),
    )
    print("Instagram visual identity cross-artifact runtime truth: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
