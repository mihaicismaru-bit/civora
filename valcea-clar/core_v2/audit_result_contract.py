from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class AuditResultContractViolation(ValueError):
    """Fail-closed violation of the Core v2 external AuditResult contract."""


_EVIDENCE_BASIS = (
    "public_site_http_route_canonical_newsarticle",
    "public_approved_photo_and_provenance",
    "remote_meta_object_readback",
    "independent_instagram_visual_identity",
    "transaction_claim_integrity",
)


@dataclass(frozen=True)
class AuditResult:
    """Canonical source-neutral Core v2 shadow AuditResult.

    This contract is a projection of independently recomputed external evidence.
    It deliberately carries no publication, cutover, acceptance, or retirement
    authority. Green CI, outbox state, exit codes, or self-declared receipts are
    not evidence for this contract.
    """

    schema_version: str
    mode: str
    status: str
    external_truth_ok: bool
    external_truth_complete: bool
    external_blocked_story_count: int
    candidate_count: int
    stories_published: int
    discovery_to_publish_latency_seconds_median: float | None
    discovery_to_publish_latency_observed_count: int
    discovery_to_publish_latency_missing_evidence_count: int
    photo_verified_count: int
    photo_coverage: float
    facebook_delivered_receipt_bound: int
    facebook_delivery_rate_receipt_bound: float
    instagram_delivered_receipt_bound: int
    instagram_delivery_rate_receipt_bound: float
    duplicates: int
    fabricated_claims: int
    unresolved_material_signals: int
    manual_intervention: int
    truth_complete_transactions: int
    rows: tuple[dict[str, Any], ...]
    evidence_basis: tuple[str, ...] = _EVIDENCE_BASIS
    publication_authority: str = "NONE"
    acceptance_ready: bool = False
    cutover_authority: str = "NONE"
    retirement_authority: str = "NONE"

    @classmethod
    def from_external_auditor_document(cls, document: dict[str, Any]) -> "AuditResult":
        if not isinstance(document, dict):
            raise AuditResultContractViolation("external auditor document must be an object")
        if document.get("schema_version") != "core-v2-independent-auditor-shadow.v1":
            raise AuditResultContractViolation("unexpected external auditor schema")
        if document.get("mode") != "SHADOW_EXTERNAL_TRUTH_AUDITOR":
            raise AuditResultContractViolation("unexpected external auditor mode")
        if document.get("status") not in {"PASS_SHADOW", "BLOCKED_NO_CANDIDATES"}:
            raise AuditResultContractViolation("unexpected external auditor status")
        if document.get("publication_authority") != "NONE":
            raise AuditResultContractViolation("publication authority must remain NONE")
        if document.get("acceptance_ready") is not False:
            raise AuditResultContractViolation("acceptance_ready must remain false")
        if document.get("cutover_authority") != "NONE":
            raise AuditResultContractViolation("cutover authority must remain NONE")
        if document.get("retirement_authority") != "NONE":
            raise AuditResultContractViolation("retirement authority must remain NONE")

        metrics = document.get("metrics")
        rows_value = document.get("rows")
        if not isinstance(metrics, dict) or not isinstance(rows_value, list):
            raise AuditResultContractViolation("external auditor metrics/rows missing")
        if any(not isinstance(row, dict) for row in rows_value):
            raise AuditResultContractViolation("external auditor rows must be objects")
        rows = tuple(rows_value)

        def integer(name: str) -> int:
            value = metrics.get(name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise AuditResultContractViolation(f"{name} must be a non-negative integer")
            return value

        def rate(name: str) -> float:
            value = metrics.get(name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise AuditResultContractViolation(f"{name} must be numeric")
            value = float(value)
            if value < 0.0 or value > 1.0:
                raise AuditResultContractViolation(f"{name} must be in [0,1]")
            return value

        candidate_count = integer("candidate_count")
        stories_published = integer("stories_published")
        latency_observed = integer("discovery_to_publish_latency_observed_count")
        latency_missing = integer("discovery_to_publish_latency_missing_evidence_count")
        photo_verified = integer("photo_verified_count")
        facebook_delivered = integer("facebook_delivered_receipt_bound")
        instagram_delivered = integer("instagram_delivered_receipt_bound")
        duplicates = integer("duplicates")
        fabricated = integer("fabricated_claims")
        unresolved = integer("unresolved_material_signals")
        manual = integer("manual_intervention")
        truth_complete = integer("truth_complete_transactions")
        photo_coverage = rate("photo_coverage")
        facebook_rate = rate("facebook_delivery_rate_receipt_bound")
        instagram_rate = rate("instagram_delivery_rate_receipt_bound")

        latency_median = metrics.get("discovery_to_publish_latency_seconds_median")
        if latency_median is not None:
            if isinstance(latency_median, bool) or not isinstance(latency_median, (int, float)) or float(latency_median) < 0:
                raise AuditResultContractViolation("latency median must be null or non-negative numeric")
            latency_median = float(latency_median)

        external_blocked = document.get("external_blocked_story_count")
        if isinstance(external_blocked, bool) or not isinstance(external_blocked, int) or external_blocked < 0:
            raise AuditResultContractViolation("external_blocked_story_count must be a non-negative integer")
        external_complete = document.get("external_truth_complete")
        if not isinstance(external_complete, bool):
            raise AuditResultContractViolation("external_truth_complete must be boolean")

        if candidate_count != len(rows):
            raise AuditResultContractViolation("candidate_count must equal auditor row count")
        if stories_published > candidate_count:
            raise AuditResultContractViolation("stories_published exceeds candidate_count")
        if photo_verified > stories_published:
            raise AuditResultContractViolation("photo_verified_count exceeds published stories")
        if facebook_delivered > candidate_count or instagram_delivered > candidate_count:
            raise AuditResultContractViolation("social delivered count exceeds candidate_count")
        if truth_complete > candidate_count or external_blocked > candidate_count:
            raise AuditResultContractViolation("truth/blocker count exceeds candidate_count")
        if latency_observed + latency_missing != stories_published:
            raise AuditResultContractViolation("latency evidence counts do not cover published stories")
        if (latency_observed == 0) != (latency_median is None):
            raise AuditResultContractViolation("latency median/observed count mismatch")

        expected_photo_rate = 0.0 if stories_published == 0 else photo_verified / stories_published
        expected_fb_rate = 0.0 if candidate_count == 0 else facebook_delivered / candidate_count
        expected_ig_rate = 0.0 if candidate_count == 0 else instagram_delivered / candidate_count
        for actual, expected, name in (
            (photo_coverage, expected_photo_rate, "photo_coverage"),
            (facebook_rate, expected_fb_rate, "facebook_delivery_rate_receipt_bound"),
            (instagram_rate, expected_ig_rate, "instagram_delivery_rate_receipt_bound"),
        ):
            if abs(actual - expected) > 1e-12:
                raise AuditResultContractViolation(f"{name} does not match its receipt-bound numerator/denominator")

        if duplicates != len(rows) - len({str(row.get("story_id") or "") for row in rows}):
            raise AuditResultContractViolation("duplicates metric does not match row identities")
        if any(not str(row.get("story_id") or "").strip() for row in rows):
            raise AuditResultContractViolation("every auditor row requires story_id")

        row_blocked = sum(1 for row in rows if row.get("blockers"))
        row_truth_complete = sum(1 for row in rows if row.get("truth_complete") is True)
        row_published = sum(1 for row in rows if row.get("site_published_external") is True)
        row_photo = sum(1 for row in rows if row.get("approved_photo_external") is True)
        row_fb = sum(1 for row in rows if row.get("facebook_delivered_receipt_bound") is True)
        row_ig = sum(1 for row in rows if row.get("instagram_delivered_receipt_bound") is True)
        row_fabricated = sum(int(row.get("fabricated_claims") or 0) for row in rows)
        row_manual = sum(int(row.get("manual_intervention") or 0) for row in rows)
        row_unresolved = sum(int(row.get("unresolved_material_signals") or 0) for row in rows)
        if (
            row_blocked != external_blocked
            or row_truth_complete != truth_complete
            or row_published != stories_published
            or row_photo != photo_verified
            or row_fb != facebook_delivered
            or row_ig != instagram_delivered
            or row_fabricated != fabricated
            or row_manual != manual
            or row_unresolved != unresolved
        ):
            raise AuditResultContractViolation("auditor aggregate metrics do not match auditor rows")

        for row in rows:
            if row.get("truth_complete") is True:
                if not all(
                    row.get(key) is True
                    for key in (
                        "site_published_external",
                        "approved_photo_external",
                        "facebook_delivered_receipt_bound",
                        "instagram_delivered_receipt_bound",
                    )
                ):
                    raise AuditResultContractViolation("truth_complete row lacks external delivery evidence")
                if int(row.get("fabricated_claims") or 0) != 0 or int(row.get("unresolved_material_signals") or 0) != 0:
                    raise AuditResultContractViolation("truth_complete row has unresolved factual defects")
                if row.get("blockers"):
                    raise AuditResultContractViolation("truth_complete row still has blockers")

        expected_external_complete = bool(
            candidate_count > 0
            and truth_complete == candidate_count
            and external_blocked == 0
            and stories_published == candidate_count
            and photo_verified == candidate_count
            and facebook_delivered == candidate_count
            and instagram_delivered == candidate_count
            and duplicates == 0
            and fabricated == 0
            and unresolved == 0
            and manual == 0
        )
        if external_complete != expected_external_complete:
            raise AuditResultContractViolation("external_truth_complete is not truth-bound to complete evidence")
        if document.get("status") == "PASS_SHADOW" and candidate_count == 0:
            raise AuditResultContractViolation("PASS_SHADOW requires candidates")
        if document.get("status") == "BLOCKED_NO_CANDIDATES" and candidate_count != 0:
            raise AuditResultContractViolation("BLOCKED_NO_CANDIDATES requires zero candidates")

        return cls(
            schema_version="core-v2-audit-result-shadow.v1",
            mode="SHADOW_TRUTH_BOUND_AUDIT_RESULT",
            status=str(document["status"]),
            external_truth_ok=True,
            external_truth_complete=external_complete,
            external_blocked_story_count=external_blocked,
            candidate_count=candidate_count,
            stories_published=stories_published,
            discovery_to_publish_latency_seconds_median=latency_median,
            discovery_to_publish_latency_observed_count=latency_observed,
            discovery_to_publish_latency_missing_evidence_count=latency_missing,
            photo_verified_count=photo_verified,
            photo_coverage=photo_coverage,
            facebook_delivered_receipt_bound=facebook_delivered,
            facebook_delivery_rate_receipt_bound=facebook_rate,
            instagram_delivered_receipt_bound=instagram_delivered,
            instagram_delivery_rate_receipt_bound=instagram_rate,
            duplicates=duplicates,
            fabricated_claims=fabricated,
            unresolved_material_signals=unresolved,
            manual_intervention=manual,
            truth_complete_transactions=truth_complete,
            rows=rows,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "status": self.status,
            "external_truth_ok": self.external_truth_ok,
            "external_truth_complete": self.external_truth_complete,
            "external_blocked_story_count": self.external_blocked_story_count,
            "metrics": {
                "candidate_count": self.candidate_count,
                "stories_published": self.stories_published,
                "discovery_to_publish_latency_seconds_median": self.discovery_to_publish_latency_seconds_median,
                "discovery_to_publish_latency_observed_count": self.discovery_to_publish_latency_observed_count,
                "discovery_to_publish_latency_missing_evidence_count": self.discovery_to_publish_latency_missing_evidence_count,
                "photo_verified_count": self.photo_verified_count,
                "photo_coverage": self.photo_coverage,
                "facebook_delivered_receipt_bound": self.facebook_delivered_receipt_bound,
                "facebook_delivery_rate_receipt_bound": self.facebook_delivery_rate_receipt_bound,
                "instagram_delivered_receipt_bound": self.instagram_delivered_receipt_bound,
                "instagram_delivery_rate_receipt_bound": self.instagram_delivery_rate_receipt_bound,
                "duplicates": self.duplicates,
                "fabricated_claims": self.fabricated_claims,
                "unresolved_material_signals": self.unresolved_material_signals,
                "manual_intervention": self.manual_intervention,
                "truth_complete_transactions": self.truth_complete_transactions,
            },
            "rows": list(self.rows),
            "evidence_basis": list(self.evidence_basis),
            "publication_authority": self.publication_authority,
            "acceptance_ready": self.acceptance_ready,
            "cutover_authority": self.cutover_authority,
            "retirement_authority": self.retirement_authority,
        }
