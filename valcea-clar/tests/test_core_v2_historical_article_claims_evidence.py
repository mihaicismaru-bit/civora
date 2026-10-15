from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "core_v2"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from historical_article_claims_evidence import build


CANDIDATES = {
    "first_ten_candidate_ids": [
        "valcea-apa-canal-contract-152m-20260902",
        "cet-govora-cine-a-decis-oprirea-20260821",
    ]
}


def kernel_document() -> dict:
    rows = []
    for story_id, claims in (
        (
            "valcea-apa-canal-contract-152m-20260902",
            [
                "Contractul de finanțare nr. 179 pentru proiectul regional a fost semnat la 28 august 2026.",
                "Valoarea totală a contractului este 931.728.052,15 lei, iar finanțarea nerambursabilă maximă este 709.812.993,20 lei.",
            ],
        ),
        (
            "cet-govora-cine-a-decis-oprirea-20260821",
            [
                "CET Govora a notificat că își va înceta definitiv producția cel târziu la 31 august 2026, invocând dispoziții legale imperative privind eliminarea producției pe bază de cărbune.",
                "Studiul aprobat indică delegarea prin concesiune ca soluție și cere Municipiului Râmnicu Vâlcea să demareze achiziția publică pentru contractul de delegare a serviciului termic.",
                "De la 1 ianuarie 2026, prețul de facturare pentru populația racordată la distribuție este 553,15 lei/Gcal, iar pentru populația racordată la transport 400,28 lei/Gcal, fără TVA.",
            ],
        ),
    ):
        evidence = []
        claim_evidence = []
        field_ids = [f"hist:{story_id}:field:{field}" for field in ("what", "who", "where", "when", "why_it_matters")]
        for field_id in field_ids:
            evidence.append({"evidence_id": field_id, "kind": "FIELD_EVIDENCE", "verified": True})
        claim_ids = []
        for index, claim in enumerate(claims):
            evidence_id = f"hist:{story_id}:claim:{index}"
            claim_ids.append(evidence_id)
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "kind": "CLAIM_EVIDENCE",
                    "claim_index": index,
                    "claim": claim,
                    "source_url": "https://example.test/source",
                    "source_content_sha256": "a" * 64,
                    "verified": True,
                }
            )
            claim_evidence.append({"claim_index": index, "claim": claim, "evidence_ids": [evidence_id]})
        rows.append(
            {
                "story_id": story_id,
                "fact_kernel_evidence_ready": True,
                "state": "FACT_KERNEL_EVIDENCE_READY_SHADOW",
                "fact_kernel": {
                    "what": "Un fapt material verificat a avut loc în Vâlcea.",
                    "who": "instituțiile indicate de sursa oficială",
                    "where": "județul Vâlcea",
                    "when": "2026",
                    "why_it_matters": "Faptul are consecințe publice materiale și este documentat în sursa citată.",
                    "source": "sursa oficială verificată",
                    "source_url": "https://example.test/source",
                    "claims": claims,
                    "evidence_ids": field_ids + claim_ids,
                },
                "evidence": evidence,
                "claim_evidence": claim_evidence,
            }
        )
    return {"schema_version": "1.0", "rows": rows}


def test_two_packages_are_claim_by_claim_evidence_bound() -> None:
    result = build(CANDIDATES, kernel_document())
    assert result["publication_authority"] == "NONE"
    assert result["article_claims_evidence_ready_count"] == 2
    for row in result["rows"]:
        assert row["state"] == "ARTICLE_CLAIMS_EVIDENCE_READY_SHADOW"
        assert row["article_claims_evidence_ready"] is True
        package = row["article_package"]
        assert package["writer_id"] == "historical_replay_shadow_editorial_v1"
        assert package["publication_authority"] == "NONE"
        assert package["site_publish_allowed"] is False
        assert package["social_publish_allowed"] is False
        assert len(package["body"]) >= 180
        for index, claim in enumerate(package["claims"]):
            assert claim["kernel_claim_index"] == index
            assert claim["evidence_ids"]
            assert claim["evidence_fingerprints"]


def test_claim_index_tamper_fails_closed() -> None:
    kernels = kernel_document()
    row = kernels["rows"][0]
    row["claim_evidence"][0]["claim_index"] = 99
    result = build(CANDIDATES, kernels)
    target = next(item for item in result["rows"] if item["story_id"] == row["story_id"])
    assert target["state"] == "BLOCKED_CLAIM_EVIDENCE_BINDING"
    assert target["article_claims_evidence_ready"] is False
    assert any("binding_cardinality" in value for value in target["blockers"])


def test_unknown_evidence_id_tamper_fails_closed() -> None:
    kernels = kernel_document()
    row = kernels["rows"][0]
    row["claim_evidence"][0]["evidence_ids"] = ["hist:tampered:claim:0"]
    result = build(CANDIDATES, kernels)
    target = next(item for item in result["rows"] if item["story_id"] == row["story_id"])
    assert target["state"] == "BLOCKED_CLAIM_EVIDENCE_BINDING"
    assert target["article_claims_evidence_ready"] is False
    assert any("evidence_not_in_kernel" in value for value in target["blockers"])


def test_unverified_claim_evidence_fails_closed() -> None:
    kernels = kernel_document()
    row = kernels["rows"][1]
    claim_evidence_id = row["claim_evidence"][0]["evidence_ids"][0]
    for evidence in row["evidence"]:
        if evidence.get("evidence_id") == claim_evidence_id:
            evidence["verified"] = False
    result = build(CANDIDATES, kernels)
    target = next(item for item in result["rows"] if item["story_id"] == row["story_id"])
    assert target["state"] == "BLOCKED_CLAIM_EVIDENCE_BINDING"
    assert any("unverified_evidence" in value for value in target["blockers"])


def main() -> None:
    test_two_packages_are_claim_by_claim_evidence_bound()
    test_claim_index_tamper_fails_closed()
    test_unknown_evidence_id_tamper_fails_closed()
    test_unverified_claim_evidence_fails_closed()
    print("historical article claims evidence tests: PASS")


if __name__ == "__main__":
    main()
