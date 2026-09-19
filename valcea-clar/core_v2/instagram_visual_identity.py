from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from visual_readback import ALLOWED_RIGHTS_BASES, inspect_provenance_asset

ROOT = Path(__file__).resolve().parents[2]
MAX_REMOTE_BYTES = 15 * 1024 * 1024
MAX_PROVENANCE_HTML_BYTES = 1_500_000
VECTOR_SIDE = 64
# Instagram recompresses, resizes and may reframe carousel images. Absolute
# pixel thresholds therefore have to tolerate bounded transformation, while
# identity remains fail-closed through a strong uniqueness margin against all
# other externally read-back images in the same object.
CORRELATION_MIN = 0.80
MAE_MAX = 0.12
COMPOSITE_MIN = 0.70
MATCH_MARGIN_MIN = 0.20


def _load(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def _pearson(left: list[int], right: list[int]) -> float:
    if len(left) != len(right) or not left:
        raise ValueError("equal non-empty vectors required")
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    numerator = sum((a - mean_left) * (b - mean_right) for a, b in zip(left, right))
    left_energy = sum((a - mean_left) ** 2 for a in left)
    right_energy = sum((b - mean_right) ** 2 for b in right)
    denominator = math.sqrt(left_energy * right_energy)
    if denominator == 0:
        return 1.0 if left == right else 0.0
    return max(-1.0, min(1.0, numerator / denominator))


def compare_vectors(left: list[int], right: list[int]) -> dict[str, Any]:
    if len(left) != len(right) or not left:
        raise ValueError("equal non-empty vectors required")
    correlation = _pearson(left, right)
    mae = sum(abs(a - b) for a, b in zip(left, right)) / (len(left) * 255.0)
    rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left)) / 255.0
    composite = max(0.0, correlation) * (1.0 - mae)
    same_visual = bool(
        correlation >= CORRELATION_MIN
        and mae <= MAE_MAX
        and composite >= COMPOSITE_MIN
    )
    return {
        "correlation": round(correlation, 6),
        "mae_normalized": round(mae, 6),
        "rmse_normalized": round(rmse, 6),
        "composite_score": round(composite, 6),
        "same_visual": same_visual,
    }


def identity_decision(candidate_results: list[dict[str, Any]]) -> dict[str, Any]:
    passing = [row for row in candidate_results if row.get("same_visual") is True]
    ranked = sorted(
        candidate_results,
        key=lambda row: float(row.get("composite_score") or 0.0),
        reverse=True,
    )
    best = ranked[0] if ranked else None
    runner_up = ranked[1] if len(ranked) > 1 else None
    best_score = float((best or {}).get("composite_score") or 0.0)
    runner_up_score = float((runner_up or {}).get("composite_score") or 0.0)
    match_margin = max(0.0, best_score - runner_up_score)
    common = {
        "best_composite_score": round(best_score, 6) if best else None,
        "runner_up_composite_score": round(runner_up_score, 6) if runner_up else None,
        "match_margin": round(match_margin, 6) if best else None,
        "match_margin_min": MATCH_MARGIN_MIN,
        "passing_candidate_count": len(passing),
    }

    if len(passing) > 1:
        return {
            "identity_bound": False,
            "identity_state": "AMBIGUOUS_MULTIPLE_REMOTE_MATCHES",
            "matched_remote_id": None,
            "matched_remote_url": None,
            **common,
        }

    if len(passing) == 1:
        match = passing[0]
        # The passing candidate must also be the best candidate and clearly
        # separated from every other remote image. A close runner-up is an
        # unresolved ambiguity even when it narrowly misses an absolute gate.
        match_is_best = bool(best is match or (best or {}).get("remote_id") == match.get("remote_id"))
        if not match_is_best or match_margin < MATCH_MARGIN_MIN:
            return {
                "identity_bound": False,
                "identity_state": "BLOCKED_INSUFFICIENT_UNIQUENESS_MARGIN",
                "matched_remote_id": None,
                "matched_remote_url": None,
                **common,
            }
        return {
            "identity_bound": True,
            "identity_state": "APPROVED_VISUAL_MATCHED_REMOTE_IMAGE_UNIQUE",
            "matched_remote_id": match.get("remote_id"),
            "matched_remote_url": match.get("media_url"),
            **common,
        }

    return {
        "identity_bound": False,
        "identity_state": "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL",
        "matched_remote_id": None,
        "matched_remote_url": None,
        **common,
    }


def _imagemagick_binary() -> str | None:
    return shutil.which("convert") or shutil.which("magick")


def _vector(path: Path, mode: str, binary: str) -> list[int]:
    if mode not in {"stretch", "center_crop"}:
        raise ValueError(f"unsupported mode: {mode}")
    command = [binary, str(path), "-auto-orient"]
    if mode == "stretch":
        command += ["-resize", f"{VECTOR_SIDE}x{VECTOR_SIDE}!"]
    else:
        command += [
            "-resize", f"{VECTOR_SIDE}x{VECTOR_SIDE}^",
            "-gravity", "center",
            "-extent", f"{VECTOR_SIDE}x{VECTOR_SIDE}",
        ]
    command += ["-colorspace", "RGB", "-depth", "8", "rgb:-"]
    completed = subprocess.run(command, capture_output=True, timeout=20, check=False)
    expected = VECTOR_SIDE * VECTOR_SIDE * 3
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"ImageMagick failed: {stderr}")
    if len(completed.stdout) != expected:
        raise RuntimeError(f"unexpected normalized byte count {len(completed.stdout)} != {expected}")
    return list(completed.stdout)


def _download_remote(url: str, target: Path, timeout: float = 20.0) -> dict[str, Any]:
    if not str(url or "").startswith("https://"):
        return {"download_ok": False, "reason": "missing_or_non_https_remote_media_url"}
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            content_type = str(response.headers.get("Content-Type") or "")
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > MAX_REMOTE_BYTES:
                return {
                    "download_ok": False,
                    "http_status": status,
                    "content_type": content_type,
                    "reason": "remote_image_exceeds_bounded_size",
                }
            body = response.read(MAX_REMOTE_BYTES + 1)
            final_url = response.geturl()
    except HTTPError as exc:
        return {"download_ok": False, "http_status": exc.code, "reason": "http_error", "error": str(exc)}
    except (URLError, TimeoutError, ValueError) as exc:
        return {"download_ok": False, "reason": "readback_error", "error": str(exc)}
    if status not in {200, 206} or not content_type.lower().startswith("image/"):
        return {
            "download_ok": False,
            "http_status": status,
            "content_type": content_type,
            "reason": "remote_payload_not_http_image",
        }
    if len(body) > MAX_REMOTE_BYTES:
        return {
            "download_ok": False,
            "http_status": status,
            "content_type": content_type,
            "reason": "remote_image_exceeds_bounded_size",
        }
    target.write_bytes(body)
    return {
        "download_ok": True,
        "http_status": status,
        "content_type": content_type,
        "bytes_downloaded": len(body),
        "final_url": final_url,
    }


def _fetch_text(url: str, timeout: float = 20.0) -> dict[str, Any]:
    if not str(url or "").startswith("https://"):
        return {"readback_ok": False, "reason": "missing_or_non_https_provenance_url"}
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Auditor/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(MAX_PROVENANCE_HTML_BYTES + 1)
            final_url = response.geturl()
    except HTTPError as exc:
        return {"readback_ok": False, "http_status": exc.code, "reason": "http_error", "error": str(exc)}
    except (URLError, TimeoutError, ValueError) as exc:
        return {"readback_ok": False, "reason": "readback_error", "error": str(exc)}
    if status != 200 or len(body) > MAX_PROVENANCE_HTML_BYTES:
        return {
            "readback_ok": False,
            "http_status": status,
            "content_type": content_type,
            "reason": "provenance_page_not_bounded_http_200",
        }
    return {
        "readback_ok": True,
        "http_status": status,
        "content_type": content_type,
        "final_url": final_url,
        "body": body.decode("utf-8", errors="replace"),
    }


def _download_approved_source(url: str, target: Path, timeout: float = 20.0) -> dict[str, Any]:
    last: dict[str, Any] = {"download_ok": False, "reason": "not_attempted"}
    for attempt in range(1, 4):
        last = _download_remote(url, target, timeout)
        last["attempts"] = attempt
        if last.get("download_ok") is True:
            return last
        if last.get("http_status") != 429 or attempt >= 3:
            break
        time.sleep(min(0.25 * attempt, 0.5))
    return last


def _hydrate_approved_visual(candidate: dict[str, Any], target: Path) -> dict[str, Any]:
    source_url = str(candidate.get("visual_source_url") or "").strip()
    direct_source_url = str(candidate.get("visual_direct_source_url") or "").strip()
    rights_basis = str(candidate.get("visual_rights_basis") or "").strip()
    approved_path = str(candidate.get("visual_image_path") or "").strip()

    base = {
        "hydration_attempted": True,
        "approved_visual_path": approved_path or None,
        "source_url": source_url or None,
        "direct_source_url": direct_source_url or None,
        "rights_basis": rights_basis or None,
        "publication_authority": "NONE",
    }
    if candidate.get("real_visual_internal_evidence") is not True:
        return {**base, "hydration_ok": False, "hydration_state": "BLOCKED_INTERNAL_VISUAL_APPROVAL_MISSING"}
    if rights_basis not in ALLOWED_RIGHTS_BASES:
        return {**base, "hydration_ok": False, "hydration_state": "BLOCKED_RIGHTS_BASIS_NOT_ALLOWED"}
    if not source_url.startswith("https://") or not direct_source_url.startswith("https://"):
        return {**base, "hydration_ok": False, "hydration_state": "BLOCKED_PROVENANCE_URL_MISSING"}

    provenance = _fetch_text(source_url)
    if provenance.get("readback_ok") is not True:
        provenance.pop("body", None)
        return {
            **base,
            "hydration_ok": False,
            "hydration_state": "BLOCKED_PROVENANCE_PAGE_READBACK",
            "provenance_source": provenance,
        }

    provenance_asset = inspect_provenance_asset(
        str(provenance.get("body") or ""),
        expected_direct_url=direct_source_url,
    )
    provenance.pop("body", None)
    if provenance_asset.get("asset_identity_ok") is not True or provenance_asset.get("license_present") is not True:
        return {
            **base,
            "hydration_ok": False,
            "hydration_state": "BLOCKED_PROVENANCE_ASSET_IDENTITY",
            "provenance_source": provenance,
            "provenance_asset": provenance_asset,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    download = _download_approved_source(direct_source_url, target)
    if download.get("download_ok") is not True or not target.is_file():
        return {
            **base,
            "hydration_ok": False,
            "hydration_state": "BLOCKED_APPROVED_SOURCE_DOWNLOAD",
            "provenance_source": provenance,
            "provenance_asset": provenance_asset,
            "direct_source_download": download,
        }

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    return {
        **base,
        "hydration_ok": True,
        "hydration_state": "VERIFIED_PROVENANCE_HYDRATED_SHADOW",
        "provenance_source": provenance,
        "provenance_asset": provenance_asset,
        "direct_source_download": download,
        "hydrated_path": str(target),
        "hydrated_sha256": digest,
        "hydrated_bytes": target.stat().st_size,
    }


def _compare_files(local_path: Path, remote_path: Path, binary: str) -> dict[str, Any]:
    views = {}
    for mode in ("stretch", "center_crop"):
        views[mode] = compare_vectors(
            _vector(local_path, mode, binary),
            _vector(remote_path, mode, binary),
        )
    best_mode, best = max(views.items(), key=lambda item: float(item[1]["composite_score"]))
    return {
        "comparison_method": "imagemagick_rgb64_unique_match_v2",
        "best_mode": best_mode,
        "views": views,
        **best,
    }


def audit(
    candidates: dict[str, Any],
    meta: dict[str, Any],
    repo_root: Path = ROOT,
) -> dict[str, Any]:
    candidate_ids = set(candidates.get("first_ten_candidate_ids") or [])
    candidate_rows = {
        str(row.get("story_id") or ""): row
        for row in candidates.get("rows") or []
        if isinstance(row, dict) and str(row.get("story_id") or "") in candidate_ids
    }
    instagram_rows = {
        str(row.get("story_id") or ""): row
        for row in meta.get("results") or []
        if isinstance(row, dict) and row.get("channel") == "instagram" and row.get("story_id")
    }
    binary = _imagemagick_binary()
    results: list[dict[str, Any]] = []

    for story_id in candidates.get("first_ten_candidate_ids") or []:
        candidate = candidate_rows.get(str(story_id)) or {}
        meta_row = instagram_rows.get(str(story_id)) or {}
        image_path = str(candidate.get("visual_image_path") or "").strip()
        repo_local_path = (repo_root / image_path).resolve() if image_path else None
        base = {
            "story_id": story_id,
            "approved_visual_path": image_path or None,
            "approved_visual_filename": candidate.get("visual_filename"),
            "publication_authority": "NONE",
            "comparison_method": "imagemagick_rgb64_unique_match_v2",
            "thresholds": {
                "correlation_min": CORRELATION_MIN,
                "mae_max": MAE_MAX,
                "composite_min": COMPOSITE_MIN,
                "match_margin_min": MATCH_MARGIN_MIN,
            },
        }
        if not binary:
            results.append({
                **base,
                "approved_asset_origin": None,
                "identity_bound": False,
                "identity_state": "BLOCKED_IMAGEMAGICK_UNAVAILABLE",
                "candidate_results": [],
            })
            continue
        if candidate.get("real_visual_internal_evidence") is not True or not image_path:
            results.append({
                **base,
                "approved_asset_origin": None,
                "identity_bound": False,
                "identity_state": "BLOCKED_APPROVED_VISUAL_NOT_READY",
                "candidate_results": [],
            })
            continue

        remote_rows = [
            row for row in (meta_row.get("remote_media_results") or [])
            if isinstance(row, dict)
            and row.get("readback_ok") is True
            and str(row.get("media_url") or "").startswith("https://")
        ]
        if not remote_rows:
            results.append({
                **base,
                "approved_asset_origin": None,
                "identity_bound": False,
                "identity_state": "BLOCKED_NO_REMOTE_IMAGE_READBACK",
                "candidate_results": [],
            })
            continue

        compared: list[dict[str, Any]] = []
        hydration: dict[str, Any] | None = None
        with tempfile.TemporaryDirectory(prefix="civora-instagram-identity-") as temp_dir:
            temp_root = Path(temp_dir)
            if repo_local_path and repo_local_path.is_file():
                approved_path = repo_local_path
                approved_asset_origin = "repository"
            else:
                approved_path = temp_root / "approved-from-provenance.img"
                hydration = _hydrate_approved_visual(candidate, approved_path)
                if hydration.get("hydration_ok") is not True:
                    results.append({
                        **base,
                        "approved_asset_origin": "provenance_hydration_failed",
                        "approved_visual_hydration": hydration,
                        "identity_bound": False,
                        "identity_state": "BLOCKED_APPROVED_VISUAL_HYDRATION_FAILED",
                        "candidate_results": [],
                    })
                    continue
                approved_asset_origin = "verified_provenance_hydration"

            for index, remote in enumerate(remote_rows):
                remote_path = temp_root / f"remote-{index}.img"
                download = _download_remote(str(remote.get("media_url") or ""), remote_path)
                row = {
                    "remote_id": remote.get("remote_id"),
                    "media_url": remote.get("media_url"),
                    "location": remote.get("location"),
                    "download": download,
                    "same_visual": False,
                }
                if download.get("download_ok") is not True:
                    compared.append(row)
                    continue
                try:
                    comparison = _compare_files(approved_path, remote_path, binary)
                except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                    compared.append({**row, "comparison_error": str(exc)[:500]})
                    continue
                compared.append({**row, **comparison})

        decision = identity_decision(compared)
        results.append({
            **base,
            "approved_asset_origin": approved_asset_origin,
            "approved_visual_hydration": hydration,
            **decision,
            "candidate_results": compared,
        })

    bound = [row for row in results if row.get("identity_bound") is True]
    hydrated = [row for row in results if row.get("approved_asset_origin") == "verified_provenance_hydration"]
    return {
        "schema_version": "1.2",
        "mode": "READ_ONLY_INSTAGRAM_VISUAL_IDENTITY",
        "publication_authority": "NONE",
        "truth_rule": "Instagram object/image presence is not approved-visual identity. Identity is bound only when exactly one externally downloaded remote IMAGE clears transform-tolerant normalized-pixel thresholds and exceeds every other remote image by the required uniqueness margin. A missing repository copy may be hydrated only from the exact already-approved HTTPS direct source after independent provenance-page ImageObject identity plus license verification; hydration is ephemeral shadow evidence and grants no publication authority.",
        "candidate_count": len(results),
        "identity_bound_count": len(bound),
        "identity_bound_story_ids": [str(row.get("story_id")) for row in bound],
        "verified_provenance_hydration_count": len(hydrated),
        "verified_provenance_hydration_story_ids": [str(row.get("story_id")) for row in hydrated],
        "acceptance_ready": False,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Instagram approved-visual identity auditor")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--meta-readback", required=True)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = audit(_load(args.candidates), _load(args.meta_readback), Path(args.repo_root).resolve())
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_count": result["candidate_count"],
        "identity_bound_count": result["identity_bound_count"],
        "identity_bound_story_ids": result["identity_bound_story_ids"],
        "verified_provenance_hydration_count": result["verified_provenance_hydration_count"],
        "verified_provenance_hydration_story_ids": result["verified_provenance_hydration_story_ids"],
        "acceptance_ready": result["acceptance_ready"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
