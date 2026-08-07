from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class AuthorizedStoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class AuthorizedStoryPolicy:
    require_grounded_provenance: bool = True
    require_corroborated_facts: bool = True
    require_uncontested_facts: bool = True
    allow_candidate_uncertain_claims: bool = True


class AuthorizedStoryBuilder:
    """Project durable editorial state into the only facts drafting may consume.

    The builder never infers or rewrites facts. It aligns the immutable Fact
    Kernel revision with reconciliation, contradiction and editorial-decision
    records, then emits only records that satisfy the configured production
    policy. A human approval authorizes the *story decision*; it does not turn
    weak, unsupported or contradicted facts into confirmed facts.
    """

    def __init__(self, policy: AuthorizedStoryPolicy | None = None):
        self.policy = policy or AuthorizedStoryPolicy()

    @staticmethod
    def _validate_alignment(
        kernel_record: dict,
        reconciliation_report: dict,
        contradiction_report: dict,
        editorial_decision: dict,
    ) -> None:
        expected = {
            "story_id": kernel_record.get("story_id"),
            "kernel_id": kernel_record.get("kernel_id"),
            "kernel_revision": kernel_record.get("revision"),
            "kernel_semantic_hash": kernel_record.get("semantic_hash"),
        }
        for name, record in (
            ("reconciliation", reconciliation_report),
            ("contradiction", contradiction_report),
            ("editorial decision", editorial_decision),
        ):
            for key, value in expected.items():
                if record.get(key) != value:
                    raise AuthorizedStoryError(f"{name} is misaligned on {key}")

        inputs = editorial_decision.get("inputs", {})
        if inputs.get("reconciliation_report_id") != reconciliation_report.get("report_id"):
            raise AuthorizedStoryError("editorial decision references stale reconciliation report")
        if inputs.get("contradiction_report_id") != contradiction_report.get("report_id"):
            raise AuthorizedStoryError("editorial decision references stale contradiction report")

    @staticmethod
    def _validate_authorization(editorial_decision: dict, approval: Optional[dict]) -> str:
        decision = editorial_decision.get("decision")
        if decision == "auto_draft":
            return "auto_draft"
        if decision != "review":
            raise AuthorizedStoryError("unknown editorial decision")
        if approval is None or approval.get("state") != "approved":
            raise AuthorizedStoryError("review decision requires an approved editorial case")
        if approval.get("editorial_decision_id") != editorial_decision.get("decision_id"):
            raise AuthorizedStoryError("approval is bound to a different editorial decision")
        if approval.get("story_id") != editorial_decision.get("story_id"):
            raise AuthorizedStoryError("approval story mismatch")
        if approval.get("kernel_semantic_hash") != editorial_decision.get("kernel_semantic_hash"):
            raise AuthorizedStoryError("approval is stale for the current Fact Kernel")
        return "human_approved"

    def build(
        self,
        *,
        kernel_record: dict,
        reconciliation_report: dict,
        contradiction_report: dict,
        editorial_decision: dict,
        approval: Optional[dict] = None,
    ) -> dict:
        self._validate_alignment(
            kernel_record,
            reconciliation_report,
            contradiction_report,
            editorial_decision,
        )
        authorization_mode = self._validate_authorization(editorial_decision, approval)

        reconciliation = reconciliation_report.get("result", {})
        contradiction = contradiction_report.get("result", {})
        reconciliation_map = {
            item.get("record_id"): item
            for item in [
                *reconciliation.get("fact_assessments", []),
                *reconciliation.get("claim_assessments", []),
            ]
        }
        contradiction_map = {
            item.get("record_id"): item
            for item in contradiction.get("assessments", [])
        }

        authorized_facts: list[dict] = []
        excluded_facts: list[dict] = []
        for fact in kernel_record.get("confirmed_facts", []):
            fact_id = fact.get("fact_id")
            rec = reconciliation_map.get(fact_id)
            con = contradiction_map.get(fact_id)
            reasons: list[str] = []
            if self.policy.require_grounded_provenance and (
                fact.get("provenance_status") != "grounded" or not fact.get("evidence_ids")
            ):
                reasons.append("provenance_not_grounded")
            if rec is None:
                reasons.append("missing_reconciliation_assessment")
            elif self.policy.require_corroborated_facts and rec.get("status") != "corroborated":
                reasons.append("fact_not_corroborated")
            if con is None:
                reasons.append("missing_contradiction_assessment")
            elif self.policy.require_uncontested_facts and con.get("status") != "uncontested":
                reasons.append("fact_not_uncontested")

            if reasons:
                excluded_facts.append(
                    {
                        "fact_id": fact_id,
                        "statement": fact.get("statement"),
                        "reasons": sorted(set(reasons)),
                    }
                )
                continue
            authorized_facts.append(
                {
                    "fact_id": fact_id,
                    "statement": fact.get("statement"),
                    "evidence_ids": list(fact.get("evidence_ids", [])),
                    "confidence": rec.get("confidence"),
                    "independent_source_count": rec.get("independent_source_count"),
                    "source_ids": list(rec.get("source_ids", [])),
                    "contradiction_status": con.get("status"),
                }
            )

        authorized_uncertain: list[dict] = []
        if self.policy.allow_candidate_uncertain_claims:
            for claim in kernel_record.get("uncertain_claims", []):
                claim_id = claim.get("claim_id")
                rec = reconciliation_map.get(claim_id)
                con = contradiction_map.get(claim_id)
                if (
                    claim.get("evidence_ids")
                    and rec is not None
                    and rec.get("status") == "candidate_corroborated"
                    and con is not None
                    and con.get("status") == "uncontested"
                ):
                    authorized_uncertain.append(
                        {
                            "claim_id": claim_id,
                            "statement": claim.get("statement"),
                            "evidence_ids": list(claim.get("evidence_ids", [])),
                            "confidence": rec.get("confidence"),
                            "source_ids": list(rec.get("source_ids", [])),
                        }
                    )

        if not authorized_facts:
            raise AuthorizedStoryError("no confirmed facts are authorized for drafting")

        return {
            "story_id": kernel_record["story_id"],
            "kernel_id": kernel_record["kernel_id"],
            "kernel_revision": kernel_record["revision"],
            "kernel_semantic_hash": kernel_record["semantic_hash"],
            "editorial_decision_id": editorial_decision["decision_id"],
            "authorization_mode": authorization_mode,
            "authorized_facts": authorized_facts,
            "authorized_uncertain_claims": authorized_uncertain,
            "excluded_facts": excluded_facts,
            "policy": {
                "require_grounded_provenance": self.policy.require_grounded_provenance,
                "require_corroborated_facts": self.policy.require_corroborated_facts,
                "require_uncontested_facts": self.policy.require_uncontested_facts,
                "allow_candidate_uncertain_claims": self.policy.allow_candidate_uncertain_claims,
            },
        }
