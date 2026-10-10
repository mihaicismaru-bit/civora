from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class AcceptanceMetrics:
    stories_published: int
    discovery_to_publish_latency_seconds_median: float | None
    photo_coverage: float
    facebook_delivery_rate_receipt_bound: float
    instagram_delivery_rate_receipt_bound: float
    duplicates: int
    fabricated_claims: int
    unresolved_material_signals: int
    manual_intervention: int

    @property
    def acceptance_ready(self) -> bool:
        return (
            self.duplicates == 0
            and self.fabricated_claims == 0
            and self.unresolved_material_signals == 0
            and self.manual_intervention == 0
        )


def _ratio(num: int, den: int) -> float:
    return 0.0 if den == 0 else num / den


def build_metrics(rows: Iterable[Mapping[str, Any]]) -> AcceptanceMetrics:
    rows = list(rows)
    material = [r for r in rows if r.get("material_signal") is True]
    site = [r for r in material if (r.get("receipts") or {}).get("site", {}).get("readback_ok") is True]
    with_visual = [
        r for r in site
        if r.get("visual")
        and r["visual"].get("editor_approved") is True
        and r["visual"].get("synthetic") is False
    ]

    def delivered(channel: str, row: Mapping[str, Any]) -> bool:
        receipt = (row.get("receipts") or {}).get(channel) or {}
        return bool(
            receipt.get("status") == "DELIVERED"
            and receipt.get("remote_id")
            and receipt.get("receipt_id")
            and receipt.get("readback_ok") is True
        )

    fb_done = sum(1 for r in with_visual if delivered("facebook", r))
    ig_done = sum(1 for r in with_visual if delivered("instagram", r))
    latencies = [
        float(r["discovery_to_publish_latency_seconds"])
        for r in site
        if r.get("discovery_to_publish_latency_seconds") is not None
    ]

    duplicates = sum(int((r.get("audit") or {}).get("duplicates") or 0) for r in rows)
    fabricated = sum(int((r.get("audit") or {}).get("fabricated_claims") or 0) for r in rows)
    manual = sum(int((r.get("audit") or {}).get("manual_intervention") or 0) for r in rows)
    unresolved = sum(int((r.get("audit") or {}).get("unresolved_material_signals") or 0) for r in rows)

    return AcceptanceMetrics(
        stories_published=len(site),
        discovery_to_publish_latency_seconds_median=median(latencies) if latencies else None,
        photo_coverage=_ratio(len(with_visual), len(site)),
        facebook_delivery_rate_receipt_bound=_ratio(fb_done, len(with_visual)),
        instagram_delivery_rate_receipt_bound=_ratio(ig_done, len(with_visual)),
        duplicates=duplicates,
        fabricated_claims=fabricated,
        unresolved_material_signals=unresolved,
        manual_intervention=manual,
    )
