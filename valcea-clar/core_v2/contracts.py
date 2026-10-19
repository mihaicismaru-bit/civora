from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class StoryState(StrEnum):
    DISCOVERED = "DISCOVERED"
    VERIFIED = "VERIFIED"
    WRITTEN = "WRITTEN"
    VISUAL_READY = "VISUAL_READY"
    SITE_PUBLISHED = "SITE_PUBLISHED"
    FB_DELIVERED = "FB_DELIVERED"
    IG_DELIVERED = "IG_DELIVERED"
    AUDITED = "AUDITED"
    NO_STORY = "NO_STORY"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


TERMINAL_STATES = {
    StoryState.NO_STORY,
    StoryState.BLOCKED,
    StoryState.FAILED,
    StoryState.AUDITED,
}

REQUIRED_FACT_FIELDS = ("what", "who", "where", "when", "why_it_matters", "source")


class ContractViolation(ValueError):
    pass


@dataclass(frozen=True)
class FactKernel:
    what: str
    who: str
    where: str
    when: str
    why_it_matters: str
    source: str
    source_url: str
    claims: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        for name in REQUIRED_FACT_FIELDS:
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ContractViolation(f"fact kernel missing {name}")
        if not self.source_url.startswith(("https://", "http://")):
            raise ContractViolation("fact kernel source_url must be http(s)")
        if not self.claims:
            raise ContractViolation("fact kernel requires at least one supported claim")


@dataclass(frozen=True)
class Visual:
    kind: str
    synthetic: bool
    source_url: str
    rights_basis: str
    semantic_relevance: str
    editor_approved: bool
    contextual_archive: bool = False
    context_disclosure: str | None = None
    credit: str | None = None

    def validate_for_social(self) -> None:
        if self.kind != "photograph":
            raise ContractViolation("social visual must be a real photograph")
        if self.synthetic:
            raise ContractViolation("synthetic-as-photo is forbidden")
        if not self.source_url.startswith(("https://", "http://")):
            raise ContractViolation("visual requires source_url")
        if not self.rights_basis.strip():
            raise ContractViolation("visual requires rights_basis")
        if self.semantic_relevance not in {"exact", "direct_context", "archive_context"}:
            raise ContractViolation("visual semantic relevance is insufficient")
        if not self.editor_approved:
            raise ContractViolation("visual requires editor approval")
        if self.contextual_archive and not (self.context_disclosure or "").strip():
            raise ContractViolation("archive/context visual requires disclosure")


@dataclass(frozen=True)
class PublicationReceipt:
    channel: str
    status: str
    canonical_url: str | None = None
    remote_id: str | None = None
    receipt_id: str | None = None
    readback_ok: bool = False
    observed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def validate_delivered(self) -> None:
        if self.status != "DELIVERED":
            raise ContractViolation("receipt is not DELIVERED")
        if self.channel == "site":
            if not self.canonical_url or not self.canonical_url.startswith(("https://", "http://")):
                raise ContractViolation("site delivery requires canonical_url")
            if not self.readback_ok:
                raise ContractViolation("site delivery requires external readback")
            return
        if self.channel not in {"facebook", "instagram"}:
            raise ContractViolation(f"unsupported delivery channel: {self.channel}")
        if not self.remote_id:
            raise ContractViolation(f"{self.channel} delivery requires remote_id")
        if not self.receipt_id:
            raise ContractViolation(f"{self.channel} delivery requires receipt_id")
        if not self.readback_ok:
            raise ContractViolation(f"{self.channel} delivery requires readback")


@dataclass(frozen=True)
class AuditResult:
    status: str
    external_truth_ok: bool
    duplicates: int
    fabricated_claims: int
    manual_intervention: int
    unresolved_material_signals: int
    evidence: tuple[str, ...] = ()

    def validate_acceptance(self) -> None:
        if self.status != "PASS":
            raise ContractViolation("audit status must be PASS")
        if not self.external_truth_ok:
            raise ContractViolation("audit must be based on external truth")
        if any(
            value != 0
            for value in (
                self.duplicates,
                self.fabricated_claims,
                self.manual_intervention,
                self.unresolved_material_signals,
            )
        ):
            raise ContractViolation("acceptance counters must all be zero")
        if not self.evidence:
            raise ContractViolation("audit requires evidence")


@dataclass
class StoryTransaction:
    story_id: str
    state: StoryState = StoryState.DISCOVERED
    signal_id: str | None = None
    material_signal: bool | None = None
    fact_kernel: FactKernel | None = None
    article: str | None = None
    visual: Visual | None = None
    receipts: dict[str, PublicationReceipt] = field(default_factory=dict)
    audit: AuditResult | None = None
    history: list[dict[str, Any]] = field(default_factory=list)

    def _record(self, state: StoryState, evidence: dict[str, Any] | None = None) -> None:
        self.state = state
        self.history.append(
            {
                "state": state.value,
                "at": datetime.now(timezone.utc).isoformat(),
                "evidence": evidence or {},
            }
        )

    def no_story(self, reason: str) -> None:
        if self.state != StoryState.DISCOVERED:
            raise ContractViolation("NO_STORY is only valid from DISCOVERED")
        if not reason.strip():
            raise ContractViolation("NO_STORY requires a reason")
        self.material_signal = False
        self._record(StoryState.NO_STORY, {"reason": reason})

    def verify(self, kernel: FactKernel) -> None:
        if self.state != StoryState.DISCOVERED:
            raise ContractViolation("VERIFY requires DISCOVERED")
        kernel.validate()
        self.material_signal = True
        self.fact_kernel = kernel
        self._record(StoryState.VERIFIED, {"source_url": kernel.source_url})

    def write(self, article: str) -> None:
        if self.state != StoryState.VERIFIED:
            raise ContractViolation("WRITE requires VERIFIED")
        if not article or len(article.strip()) < 180:
            raise ContractViolation("article is too short to be a full editorial story")
        self.article = article.strip()
        self._record(StoryState.WRITTEN, {"chars": len(self.article)})

    def attach_visual(self, visual: Visual) -> None:
        if self.state != StoryState.WRITTEN:
            raise ContractViolation("VISUAL_READY requires WRITTEN")
        visual.validate_for_social()
        self.visual = visual
        self._record(StoryState.VISUAL_READY, {"source_url": visual.source_url})

    def publish_site(self, receipt: PublicationReceipt) -> None:
        if self.state not in {StoryState.WRITTEN, StoryState.VISUAL_READY}:
            raise ContractViolation("SITE_PUBLISHED requires WRITTEN or VISUAL_READY")
        if receipt.channel != "site":
            raise ContractViolation("site publication requires site receipt")
        receipt.validate_delivered()
        self.receipts["site"] = receipt
        self._record(StoryState.SITE_PUBLISHED, {"canonical_url": receipt.canonical_url})

    def deliver_social(self, receipt: PublicationReceipt) -> None:
        if self.state not in {StoryState.SITE_PUBLISHED, StoryState.FB_DELIVERED, StoryState.IG_DELIVERED}:
            raise ContractViolation("social delivery requires SITE_PUBLISHED")
        if self.visual is None:
            raise ContractViolation("social delivery is fail-closed without a real approved photograph")
        self.visual.validate_for_social()
        receipt.validate_delivered()
        if receipt.channel == "facebook":
            self.receipts["facebook"] = receipt
            self._record(StoryState.FB_DELIVERED, {"remote_id": receipt.remote_id})
        elif receipt.channel == "instagram":
            self.receipts["instagram"] = receipt
            self._record(StoryState.IG_DELIVERED, {"remote_id": receipt.remote_id})
        else:
            raise ContractViolation("only facebook/instagram are part of Core v2 acceptance")

    def audit_story(self, result: AuditResult) -> None:
        if "site" not in self.receipts:
            raise ContractViolation("audit requires site delivery evidence")
        result.validate_acceptance()
        self.audit = result
        self._record(StoryState.AUDITED, {"evidence": list(result.evidence)})

    def fail_distribution(self, channel: str, reason: str) -> None:
        """Record a channel failure without rolling back a truthful site publication."""
        if "site" not in self.receipts:
            raise ContractViolation("distribution failure may only be recorded after site publication")
        self.history.append(
            {
                "state": "DISTRIBUTION_FAILED",
                "channel": channel,
                "reason": reason,
                "at": datetime.now(timezone.utc).isoformat(),
            }
        )

    def as_dict(self) -> dict[str, Any]:
        def encode(obj: Any) -> Any:
            if hasattr(obj, "__dict__"):
                return {k: encode(v) for k, v in obj.__dict__.items()}
            if isinstance(obj, tuple):
                return [encode(v) for v in obj]
            if isinstance(obj, dict):
                return {k: encode(v) for k, v in obj.items()}
            if isinstance(obj, StrEnum):
                return obj.value
            return obj

        return encode(self)
