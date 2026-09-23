from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts import FactKernel


@dataclass(frozen=True)
class IntegrityResult:
    status: str
    fabricated_claims: int
    bound_claims: int
    errors: tuple[str, ...]

    @property
    def pass_gate(self) -> bool:
        return self.status == "PASS" and self.fabricated_claims == 0


def _normalize_claim_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def validate_editorial_package(kernel: FactKernel, package: dict[str, Any]) -> IntegrityResult:
    kernel.validate()
    errors: list[str] = []
    body = str(package.get("body") or "").strip()
    if len(body) < 180:
        errors.append("article_body_too_short")

    rows = package.get("claims")
    if not isinstance(rows, list) or not rows:
        errors.append("article_claims_missing")
        rows = []

    bound = 0
    fabricated = 0
    evidence_universe = set(kernel.evidence_ids)
    normalized_kernel_claims = tuple(_normalize_claim_text(value) for value in kernel.claims)
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"claim_{idx}_not_object")
            fabricated += 1
            continue
        text = _normalize_claim_text(row.get("text"))
        source_index = row.get("kernel_claim_index")
        evidence_ids = {str(v) for v in row.get("evidence_ids") or [] if str(v)}
        invalid = False
        if not text:
            errors.append(f"claim_{idx}_missing_text")
            invalid = True
        if not isinstance(source_index, int) or not 0 <= source_index < len(kernel.claims):
            errors.append(f"claim_{idx}_unbound_kernel_claim")
            invalid = True
        elif text and text != normalized_kernel_claims[source_index]:
            errors.append(f"claim_{idx}_text_mismatch_kernel_claim")
            invalid = True
        if not evidence_ids:
            errors.append(f"claim_{idx}_missing_evidence")
            invalid = True
        elif not evidence_ids.issubset(evidence_universe):
            errors.append(f"claim_{idx}_unknown_evidence")
            invalid = True
        if invalid:
            fabricated += 1
        else:
            bound += 1

    status = "PASS" if not errors and fabricated == 0 else "FAILED"
    return IntegrityResult(
        status=status,
        fabricated_claims=fabricated,
        bound_claims=bound,
        errors=tuple(errors),
    )
