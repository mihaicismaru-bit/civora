from __future__ import annotations
from statistics import mean
from .models import Source, Signal, FactKernel, VerificationStatus

def clamp(v: float) -> float:
    return round(max(0.0, min(100.0, v)), 2)

def source_score(source: Source) -> float:
    positive = (
        source.authority * 0.24 +
        source.accuracy * 0.26 +
        source.timeliness * 0.14 +
        source.originality * 0.14 +
        source.transparency * 0.12
    )
    return clamp((positive - source.risk * 0.10) * 100)

def opportunity_score(signal: Signal) -> float:
    value = (
        signal.public_interest * 0.28 +
        signal.impact * 0.24 +
        signal.novelty * 0.16 +
        signal.utility * 0.22 -
        signal.factual_risk * 0.10
    )
    return clamp(value * 100)

def trust_score(kernel: FactKernel, source_scores: list[float]) -> float:
    evidence_conf = mean([e.confidence for e in kernel.evidence]) if kernel.evidence else 0.0
    source_conf = mean(source_scores) / 100 if source_scores else 0.0
    status_bonus = {
        VerificationStatus.UNVERIFIED: 0.0,
        VerificationStatus.PARTIAL: 0.15,
        VerificationStatus.VERIFIED: 0.35,
        VerificationStatus.DISPUTED: -0.20,
    }[kernel.verification_status]
    penalty = min(0.30, len(kernel.uncertain_claims) * 0.05)
    return clamp((evidence_conf * 0.45 + source_conf * 0.35 + status_bonus - penalty) * 100)

def viral_score(signal: Signal, trust: float) -> float:
    value = (
        signal.public_interest * 0.26 +
        signal.impact * 0.20 +
        signal.novelty * 0.18 +
        signal.utility * 0.20 +
        (trust / 100) * 0.26 -
        signal.factual_risk * 0.10
    )
    return clamp(value * 100)
