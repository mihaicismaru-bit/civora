from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


PILOT_SOURCE_IDS = {
    "ipj_valcea",
    "isu_valcea",
    "apavil",
    "primaria_ramnicu_valcea",
    "cj_valcea",
    "eta",
    "isj_valcea",
    "filarmonica_valcea",
}


@dataclass(frozen=True)
class SignalEnvelope:
    source_id: str
    signal_id: str
    source_url: str
    source_title: str
    discovered_at: str
    material_signal: bool
    terminal: str | None
    reason: str | None
    confidence: int | None
    evidence: Mapping[str, Any]


def normalize_canonical_candidate(source_id: str, row: Mapping[str, Any]) -> SignalEnvelope:
    """Normalize an existing source-adapter candidate without granting publication authority."""
    if source_id not in PILOT_SOURCE_IDS:
        raise ValueError(f"source outside bounded pilot: {source_id}")
    signal_id = str(row.get("id") or "").strip()
    if not signal_id:
        raise ValueError("signal id missing")
    sources = row.get("sources") or []
    primary = sources[0] if sources and isinstance(sources[0], Mapping) else {}
    source_url = str(primary.get("url") or "").strip()
    if not source_url.startswith(("https://", "http://")):
        raise ValueError("canonical candidate missing primary source URL")
    source_title = str(row.get("source_title") or row.get("headline") or "").strip()
    if not source_title:
        raise ValueError("canonical candidate missing source title")

    paragraphs = [str(p).strip() for p in row.get("paragraphs") or [] if str(p).strip()]
    gate = str(row.get("material_fact_gate") or "").strip().upper()
    reader_authorized = row.get("reader_facing_copy_authorized")
    material = bool(gate == "PASS" and paragraphs and reader_authorized is not False)
    reason = None
    terminal = None
    if not material:
        terminal = "NO_STORY"
        if gate and gate != "PASS":
            reason = f"material_fact_gate:{gate}"
        elif not paragraphs:
            reason = "no_material_paragraphs"
        elif reader_authorized is False:
            reason = "reader_facing_copy_not_authorized"
        else:
            reason = "material_signal_not_proven"

    confidence_raw = row.get("confidence")
    confidence = int(confidence_raw) if isinstance(confidence_raw, (int, float)) else None
    return SignalEnvelope(
        source_id=source_id,
        signal_id=signal_id,
        source_url=source_url,
        source_title=source_title,
        discovered_at=str(row.get("discovered_at") or row.get("valid_from") or ""),
        material_signal=material,
        terminal=terminal,
        reason=reason,
        confidence=confidence,
        evidence={
            "material_fact_gate": gate or None,
            "paragraph_count": len(paragraphs),
            "reader_facing_copy_authorized": reader_authorized,
            "source_tier": primary.get("tier"),
        },
    )
