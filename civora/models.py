from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()

class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    PARTIAL = "partial"
    VERIFIED = "verified"
    DISPUTED = "disputed"

class StoryState(str, Enum):
    SIGNAL = "signal"
    VERIFYING = "verifying"
    READY = "ready"
    DRAFTED = "drafted"
    PACKAGED = "packaged"
    BLOCKED = "blocked"

class EvidencePolarity(str, Enum):
    SUPPORT = "support"
    CONTRADICT = "contradict"

@dataclass
class Evidence:
    source_id: str
    claim: str
    url: Optional[str] = None
    captured_at: str = field(default_factory=utc_now)
    confidence: float = 0.5

@dataclass(frozen=True)
class EvidenceRelation:
    """Explicit relation between one evidence item and a target statement.

    Relations are deliberately supplied explicitly rather than inferred from
    negation words or fuzzy semantic similarity. ``source_id`` +
    ``evidence_claim`` identifies the evidence record; ``target_statement``
    identifies a confirmed fact or uncertain claim in the same Fact Kernel.
    """
    target_statement: str
    source_id: str
    evidence_claim: str
    polarity: EvidencePolarity = EvidencePolarity.SUPPORT

@dataclass
class Source:
    name: str
    source_type: str
    geography: List[str]
    authority: float
    accuracy: float
    timeliness: float
    originality: float
    transparency: float
    risk: float
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

@dataclass
class Signal:
    title: str
    summary: str
    geography: List[str]
    source_ids: List[str]
    public_interest: float
    impact: float
    novelty: float
    utility: float
    factual_risk: float
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: str = field(default_factory=utc_now)

@dataclass
class FactKernel:
    confirmed_facts: List[str]
    uncertain_claims: List[str]
    affected_groups: List[str]
    next_expected_event: Optional[str]
    evidence: List[Evidence]
    verification_status: VerificationStatus = VerificationStatus.UNVERIFIED
    evidence_relations: List[EvidenceRelation] = field(default_factory=list)

@dataclass
class StoryObject:
    signal: Signal
    fact_kernel: FactKernel
    state: StoryState = StoryState.SIGNAL
    source_score: float = 0.0
    opportunity_score: float = 0.0
    trust_score: float = 0.0
    viral_score: float = 0.0
    article: Optional[Dict[str, Any]] = None
    content_pack: Optional[Dict[str, Any]] = None
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: int = 1
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["state"] = self.state.value
        data["fact_kernel"]["verification_status"] = self.fact_kernel.verification_status.value
        for relation in data["fact_kernel"].get("evidence_relations", []):
            polarity = relation.get("polarity")
            if isinstance(polarity, EvidencePolarity):
                relation["polarity"] = polarity.value
        return data
