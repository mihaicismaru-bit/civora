from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class TenStoryAcceptance:
    ready: bool
    evaluated: int
    failures: tuple[str, ...]


def _receipt_ok(receipt: Mapping[str, Any], *, social: bool) -> bool:
    if receipt.get("status") != "DELIVERED" or receipt.get("readback_ok") is not True:
        return False
    if social:
        return bool(receipt.get("remote_id") and receipt.get("receipt_id"))
    return bool(receipt.get("canonical_url"))


def evaluate_consecutive(rows: Iterable[Mapping[str, Any]], required: int = 10) -> TenStoryAcceptance:
    rows = list(rows)
    failures: list[str] = []
    if len(rows) < required:
        return TenStoryAcceptance(False, len(rows), (f"need_{required}_stories_have_{len(rows)}",))

    window = rows[-required:]
    ids = [str(row.get("story_id") or "") for row in window]
    if any(not sid for sid in ids):
        failures.append("missing_story_id")
    if len(set(ids)) != len(ids):
        failures.append("duplicate_story_id")

    for pos, row in enumerate(window):
        sid = ids[pos] or f"row_{pos}"
        if row.get("material_signal") is not True:
            failures.append(f"{sid}:not_material")
        if row.get("state") != "AUDITED":
            failures.append(f"{sid}:not_audited")
        if len(str(row.get("article") or "").strip()) < 180:
            failures.append(f"{sid}:article_missing_or_short")

        receipts = row.get("receipts") or {}
        if not _receipt_ok(receipts.get("site") or {}, social=False):
            failures.append(f"{sid}:site_not_delivered")
        if not _receipt_ok(receipts.get("facebook") or {}, social=True):
            failures.append(f"{sid}:facebook_not_receipt_bound")
        if not _receipt_ok(receipts.get("instagram") or {}, social=True):
            failures.append(f"{sid}:instagram_not_receipt_bound")

        visual = row.get("visual") or {}
        if (
            visual.get("kind") != "photograph"
            or visual.get("synthetic") is not False
            or visual.get("editor_approved") is not True
            or not visual.get("rights_basis")
            or visual.get("semantic_relevance") not in {"exact", "direct_context", "archive_context"}
        ):
            failures.append(f"{sid}:visual_gate_failed")

        audit = row.get("audit") or {}
        if audit.get("external_truth_ok") is not True:
            failures.append(f"{sid}:audit_not_external_truth")
        for metric in ("duplicates", "fabricated_claims", "manual_intervention", "unresolved_material_signals"):
            if int(audit.get(metric) or 0) != 0:
                failures.append(f"{sid}:{metric}_nonzero")

    return TenStoryAcceptance(not failures, required, tuple(failures))
