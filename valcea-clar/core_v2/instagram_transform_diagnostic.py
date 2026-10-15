from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from instagram_visual_identity import (
    COMPOSITE_MIN,
    CORRELATION_MIN,
    MAE_MAX,
    MATCH_MARGIN_MIN,
    ROOT,
    _download_remote,
    _hydrate_approved_visual,
    _imagemagick_binary,
    _vector,
    compare_vectors,
)

# Diagnostic-only crop hypotheses. These are deliberately bounded and are not
# part of Core v2 identity acceptance. They exist only to explain a single
# externally observed near-match without changing truth or delivery state.
CROP_FRACTIONS = (0.90, 0.80, 0.70, 0.60)
CROP_ANCHORS = ("left", "center", "right")
VECTOR_SIDE = 64


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def bounded_crop_boxes(width: int, height: int) -> list[dict[str, Any]]:
    if width <= 0 or height <= 0:
        raise ValueError("positive image dimensions required")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int, int]] = set()
    for fraction in CROP_FRACTIONS:
        crop_width = max(1, min(width, int(round(width * fraction))))
        max_x = max(0, width - crop_width)
        offsets = {
            "left": 0,
            "center": max_x // 2,
            "right": max_x,
        }
        for anchor in CROP_ANCHORS:
            x = offsets[anchor]
            key = (x, 0, crop_width, height)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "crop_fraction": fraction,
                "anchor": anchor,
                "x": x,
                "y": 0,
                "width": crop_width,
                "height": height,
            })
    return rows


def select_near_match_targets(identity: dict[str, Any]) -> list[dict[str, Any]]:
    targets: list[dict[str, Any]] = []
    for row in identity.get("results") or []:
        if not isinstance(row, dict) or row.get("identity_bound") is True:
            continue
        diagnostic = row.get("read_only_score_diagnostics")
        if not isinstance(diagnostic, dict):
            continue
        if diagnostic.get("diagnostic_state") != "UNIQUE_BEST_BELOW_IDENTITY_THRESHOLDS":
            continue
        best_remote_id = str(diagnostic.get("best_remote_id") or "").strip()
        story_id = str(row.get("story_id") or "").strip()
        if story_id and best_remote_id:
            targets.append({
                "story_id": story_id,
                "best_remote_id": best_remote_id,
                "baseline_identity_state": row.get("identity_state"),
                "baseline_diagnostic_state": diagnostic.get("diagnostic_state"),
                "baseline_best_composite_score": diagnostic.get("best_composite_score"),
                "baseline_best_to_runner_up_margin": diagnostic.get("best_to_runner_up_margin"),
            })
    return targets


def _dimensions(path: Path, binary: str) -> tuple[int, int]:
    completed = subprocess.run(
        [binary, str(path), "-auto-orient", "-format", "%w %h", "info:"],
        capture_output=True,
        timeout=20,
        check=False,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or "ImageMagick dimension read failed")[:500])
    parts = completed.stdout.strip().split()
    if len(parts) != 2:
        raise RuntimeError(f"unexpected dimensions output: {completed.stdout[:100]!r}")
    width, height = int(parts[0]), int(parts[1])
    if width <= 0 or height <= 0:
        raise RuntimeError("non-positive image dimensions")
    return width, height


def _crop_vector(path: Path, box: dict[str, Any], binary: str) -> list[int]:
    geometry = f"{int(box['width'])}x{int(box['height'])}+{int(box['x'])}+{int(box['y'])}"
    command = [
        binary,
        str(path),
        "-auto-orient",
        "-crop",
        geometry,
        "+repage",
        "-resize",
        f"{VECTOR_SIDE}x{VECTOR_SIDE}^",
        "-gravity",
        "center",
        "-extent",
        f"{VECTOR_SIDE}x{VECTOR_SIDE}",
        "-colorspace",
        "RGB",
        "-depth",
        "8",
        "rgb:-",
    ]
    completed = subprocess.run(command, capture_output=True, timeout=20, check=False)
    expected = VECTOR_SIDE * VECTOR_SIDE * 3
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ImageMagick crop diagnostic failed: {stderr}")
    if len(completed.stdout) != expected:
        raise RuntimeError(f"unexpected crop vector byte count {len(completed.stdout)} != {expected}")
    return list(completed.stdout)


def summarize_hypotheses(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ranked = sorted(
        [row for row in rows if isinstance(row, dict) and "composite_score" in row],
        key=lambda row: float(row.get("composite_score") or 0.0),
        reverse=True,
    )
    for index, row in enumerate(ranked, start=1):
        row["rank"] = index
    best = ranked[0] if ranked else None
    clears = bool(
        best
        and float(best.get("correlation") or -1.0) >= CORRELATION_MIN
        and float(best.get("mae_normalized") or 1.0) <= MAE_MAX
        and float(best.get("composite_score") or 0.0) >= COMPOSITE_MIN
    )
    if not best:
        state = "NO_BOUNDED_TRANSFORM_RESULT"
    elif clears:
        state = "BOUNDED_TRANSFORM_EXPLAINS_NEAR_MATCH_DIAGNOSTIC_ONLY"
    else:
        state = "BOUNDED_TRANSFORM_DID_NOT_EXPLAIN_NEAR_MATCH"
    return {
        "diagnostic_state": state,
        "diagnostic_authority": "NONE",
        "acceptance_effect": False,
        "identity_promotion_allowed": False,
        "thresholds_changed": False,
        "hypothesis_clears_current_pixel_thresholds": clears,
        "best_hypothesis": best,
        "tested_hypothesis_count": len(ranked),
        "thresholds": {
            "correlation_min": CORRELATION_MIN,
            "mae_max": MAE_MAX,
            "composite_min": COMPOSITE_MIN,
            "identity_match_margin_min": MATCH_MARGIN_MIN,
        },
        "ranked_hypotheses": ranked,
    }


def _run_hypotheses(approved_path: Path, remote_path: Path, binary: str) -> dict[str, Any]:
    width, height = _dimensions(approved_path, binary)
    remote_views = {
        "stretch": _vector(remote_path, "stretch", binary),
        "center_crop": _vector(remote_path, "center_crop", binary),
    }
    rows: list[dict[str, Any]] = []
    for box in bounded_crop_boxes(width, height):
        approved_vector = _crop_vector(approved_path, box, binary)
        for remote_mode, remote_vector in remote_views.items():
            score = compare_vectors(approved_vector, remote_vector)
            rows.append({
                "hypothesis_id": f"horizontal_{box['crop_fraction']:.2f}_{box['anchor']}_to_{remote_mode}",
                "approved_transform": {
                    "kind": "horizontal_bounded_crop",
                    **box,
                },
                "remote_normalization": remote_mode,
                **score,
            })
    return {
        "approved_dimensions": {"width": width, "height": height},
        **summarize_hypotheses(rows),
    }


def audit(
    candidates: dict[str, Any],
    meta: dict[str, Any],
    identity: dict[str, Any],
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    target_rows = select_near_match_targets(identity)
    candidate_rows = {
        str(row.get("story_id") or ""): row
        for row in candidates.get("rows") or []
        if isinstance(row, dict) and row.get("story_id")
    }
    instagram_rows = {
        str(row.get("story_id") or ""): row
        for row in meta.get("results") or []
        if isinstance(row, dict) and row.get("channel") == "instagram" and row.get("story_id")
    }
    identity_rows = {
        str(row.get("story_id") or ""): row
        for row in identity.get("results") or []
        if isinstance(row, dict) and row.get("story_id")
    }
    binary = _imagemagick_binary()
    results: list[dict[str, Any]] = []

    for target in target_rows:
        story_id = target["story_id"]
        candidate = candidate_rows.get(story_id) or {}
        meta_row = instagram_rows.get(story_id) or {}
        identity_row = identity_rows.get(story_id) or {}
        base = {
            **target,
            "publication_authority": "NONE",
            "acceptance_effect": False,
            "identity_promotion_allowed": False,
            "thresholds_changed": False,
        }
        if not binary:
            results.append({**base, "diagnostic_state": "BLOCKED_IMAGEMAGICK_UNAVAILABLE"})
            continue

        best_remote = None
        for remote in meta_row.get("remote_media_results") or []:
            if not isinstance(remote, dict):
                continue
            if str(remote.get("remote_id") or "") != target["best_remote_id"]:
                continue
            if remote.get("readback_ok") is not True or not str(remote.get("media_url") or "").startswith("https://"):
                continue
            best_remote = remote
            break
        if not best_remote:
            results.append({**base, "diagnostic_state": "BLOCKED_BEST_REMOTE_NOT_IN_CURRENT_READBACK"})
            continue

        image_path = str(candidate.get("visual_image_path") or "").strip()
        repo_local_path = (repo_root / image_path).resolve() if image_path else None
        hydration: dict[str, Any] | None = None
        with tempfile.TemporaryDirectory(prefix="civora-instagram-transform-diagnostic-") as temp_dir:
            temp_root = Path(temp_dir)
            if repo_local_path and repo_local_path.is_file():
                approved_path = repo_local_path
                approved_origin = "repository"
            else:
                approved_path = temp_root / "approved.img"
                hydration = _hydrate_approved_visual(candidate, approved_path)
                if hydration.get("hydration_ok") is not True:
                    results.append({
                        **base,
                        "approved_asset_origin": "provenance_hydration_failed",
                        "approved_visual_hydration": hydration,
                        "diagnostic_state": "BLOCKED_APPROVED_VISUAL_HYDRATION_FAILED",
                    })
                    continue
                approved_origin = "verified_provenance_hydration"

            remote_path = temp_root / "near-match-remote.img"
            remote_download = _download_remote(str(best_remote.get("media_url") or ""), remote_path)
            if remote_download.get("download_ok") is not True:
                results.append({
                    **base,
                    "approved_asset_origin": approved_origin,
                    "approved_visual_hydration": hydration,
                    "remote_download": remote_download,
                    "diagnostic_state": "BLOCKED_REMOTE_DOWNLOAD_FAILED",
                })
                continue
            try:
                bounded = _run_hypotheses(approved_path, remote_path, binary)
            except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as exc:
                results.append({
                    **base,
                    "approved_asset_origin": approved_origin,
                    "approved_visual_hydration": hydration,
                    "remote_download": remote_download,
                    "diagnostic_state": "BLOCKED_TRANSFORM_DIAGNOSTIC_ERROR",
                    "error": str(exc)[:500],
                })
                continue

        baseline_candidate = next(
            (
                row for row in identity_row.get("candidate_results") or []
                if isinstance(row, dict) and str(row.get("remote_id") or "") == target["best_remote_id"]
            ),
            None,
        )
        results.append({
            **base,
            "approved_asset_origin": approved_origin,
            "approved_visual_hydration": hydration,
            "remote_download": remote_download,
            "baseline_candidate": baseline_candidate,
            **bounded,
        })

    explained = [
        row for row in results
        if row.get("diagnostic_state") == "BOUNDED_TRANSFORM_EXPLAINS_NEAR_MATCH_DIAGNOSTIC_ONLY"
    ]
    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_INSTAGRAM_BOUNDED_TRANSFORM_DIAGNOSTIC",
        "publication_authority": "NONE",
        "acceptance_effect": False,
        "identity_promotion_allowed": False,
        "thresholds_changed": False,
        "truth_rule": "This diagnostic may test only bounded horizontal crop/reframing hypotheses for an already unique below-threshold near-match. It cannot change identity thresholds, receipts, delivery state, publication authority, or acceptance readiness. A passing crop hypothesis is explanatory evidence only and requires a separately reviewed identity-contract change before it could ever affect delivery truth.",
        "target_count": len(target_rows),
        "result_count": len(results),
        "explained_near_match_count": len(explained),
        "explained_story_ids": [str(row.get("story_id")) for row in explained],
        "acceptance_ready": False,
        "results": results,
    }


def validate_output(result: dict[str, Any]) -> None:
    if result.get("publication_authority") != "NONE":
        raise ValueError("transform diagnostic must never gain publication authority")
    if result.get("acceptance_effect") is not False:
        raise ValueError("transform diagnostic must be acceptance-neutral")
    if result.get("identity_promotion_allowed") is not False:
        raise ValueError("transform diagnostic must not promote identity")
    if result.get("thresholds_changed") is not False:
        raise ValueError("transform diagnostic must not change thresholds")
    if result.get("acceptance_ready") is not False:
        raise ValueError("transform diagnostic cannot make acceptance ready")
    for row in result.get("results") or []:
        if not isinstance(row, dict):
            raise ValueError("diagnostic result rows must be objects")
        if row.get("publication_authority") != "NONE":
            raise ValueError("diagnostic row publication authority drifted")
        if row.get("acceptance_effect") is not False or row.get("identity_promotion_allowed") is not False:
            raise ValueError("diagnostic row gained acceptance effect")


def main() -> int:
    parser = argparse.ArgumentParser(description="Acceptance-neutral bounded Instagram crop/reframing diagnostic")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--identity", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(
        _load(args.candidates),
        _load(args.meta_readback),
        _load(args.identity),
        Path(args.repo_root).resolve(),
    )
    validate_output(result)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "target_count": result["target_count"],
        "result_count": result["result_count"],
        "explained_near_match_count": result["explained_near_match_count"],
        "explained_story_ids": result["explained_story_ids"],
        "publication_authority": result["publication_authority"],
        "acceptance_ready": result["acceptance_ready"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
