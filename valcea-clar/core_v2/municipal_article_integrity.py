from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from contracts import FactKernel
from editorial_integrity import validate_editorial_package

POLICY_NOTE = (
    "Core v2 tratează hotărârea adoptată ca dovadă a deciziei consemnate în document, "
    "nu ca dovadă că măsura a fost deja implementată ulterior."
)


@dataclass(frozen=True)
class MunicipalArticleIntegrityResult:
    status: str
    fabricated_claims: int
    bound_claims: int
    errors: tuple[str, ...]

    @property
    def pass_gate(self) -> bool:
        return self.status == "PASS" and self.fabricated_claims == 0


def _norm(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _expected_controlled_segments(kernel: FactKernel) -> list[dict[str, Any]]:
    return [
        {
            "kind": "kernel_when",
            "text": f"Momentul documentat: {kernel.when}.",
            "evidence_ids": list(kernel.evidence_ids),
        },
        {
            "kind": "kernel_why_it_matters",
            "text": f"De ce contează: {kernel.why_it_matters}",
            "evidence_ids": list(kernel.evidence_ids),
        },
        {
            "kind": "kernel_source",
            "text": f"Sursa: {kernel.source} — {kernel.source_url}",
            "evidence_ids": list(kernel.evidence_ids),
        },
        {
            "kind": "policy_note",
            "text": POLICY_NOTE,
            "evidence_ids": [],
        },
    ]


def validate_municipal_article(kernel: FactKernel, package: dict[str, Any]) -> MunicipalArticleIntegrityResult:
    """Validate that municipal shadow prose contains no unbound factual text.

    The general claim gate binds every declared article claim to a FactKernel claim.
    This municipal gate additionally makes the whole body deterministic: every body
    segment must be either an exact kernel claim or one of a small set of controlled
    renderings of kernel fields/policy. That prevents a writer from hiding unsupported
    factual prose between correctly bound claims.
    """
    kernel.validate()
    general = validate_editorial_package(kernel, package)
    errors = list(general.errors)
    fabricated = int(general.fabricated_claims)

    if _norm(package.get("headline")) != _norm(kernel.what):
        errors.append("headline_not_exact_kernel_what")
        fabricated += 1
    if _norm(package.get("dek")) != _norm(kernel.why_it_matters):
        errors.append("dek_not_exact_kernel_why_it_matters")
        fabricated += 1

    segments = package.get("body_segments")
    if not isinstance(segments, list) or not segments:
        errors.append("body_segments_missing")
        segments = []

    expected: list[dict[str, Any]] = []
    for idx, claim in enumerate(kernel.claims):
        expected.append(
            {
                "kind": "kernel_claim",
                "kernel_claim_index": idx,
                "text": claim,
                "evidence_ids": list(kernel.evidence_ids),
            }
        )
    expected.extend(_expected_controlled_segments(kernel))

    if len(segments) != len(expected):
        errors.append("body_segment_count_mismatch")
        fabricated += abs(len(segments) - len(expected)) or 1

    evidence_universe = set(kernel.evidence_ids)
    for idx, exp in enumerate(expected):
        if idx >= len(segments):
            break
        row = segments[idx]
        if not isinstance(row, dict):
            errors.append(f"body_segment_{idx}_not_object")
            fabricated += 1
            continue
        if row.get("kind") != exp["kind"]:
            errors.append(f"body_segment_{idx}_kind_mismatch")
            fabricated += 1
        if _norm(row.get("text")) != _norm(exp["text"]):
            errors.append(f"body_segment_{idx}_text_mismatch")
            fabricated += 1
        if exp["kind"] == "kernel_claim" and row.get("kernel_claim_index") != exp["kernel_claim_index"]:
            errors.append(f"body_segment_{idx}_claim_index_mismatch")
            fabricated += 1
        actual_evidence = {str(v) for v in row.get("evidence_ids") or [] if str(v)}
        if exp["kind"] == "policy_note":
            if actual_evidence:
                errors.append(f"body_segment_{idx}_policy_note_has_evidence")
                fabricated += 1
        elif not actual_evidence or not actual_evidence.issubset(evidence_universe):
            errors.append(f"body_segment_{idx}_evidence_invalid")
            fabricated += 1

    expected_body = "\n\n".join(_norm(item["text"]) for item in expected)
    if _norm(package.get("body")) != _norm(expected_body):
        errors.append("body_contains_uncontrolled_or_missing_text")
        fabricated += 1

    deduped = tuple(dict.fromkeys(errors))
    status = "PASS" if not deduped and fabricated == 0 and general.pass_gate else "FAILED"
    return MunicipalArticleIntegrityResult(
        status=status,
        fabricated_claims=fabricated,
        bound_claims=general.bound_claims,
        errors=deduped,
    )
