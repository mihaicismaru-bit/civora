#!/usr/bin/env python3
import copy
import json
import tempfile
from pathlib import Path

from validate_service_proof_architecture import (
    ARCH_PATH,
    PORTFOLIO_PATH,
    ValidationError,
    validate,
)


def write_pair(root, architecture, portfolio):
    architecture_path = root / "architecture.json"
    portfolio_path = root / "portfolio.json"
    architecture_path.write_text(json.dumps(architecture, ensure_ascii=False), encoding="utf-8")
    portfolio_path.write_text(json.dumps(portfolio, ensure_ascii=False), encoding="utf-8")
    return architecture_path, portfolio_path


def expect_failure(architecture, portfolio, label):
    with tempfile.TemporaryDirectory() as tmp:
        paths = write_pair(Path(tmp), architecture, portfolio)
        try:
            validate(*paths)
        except ValidationError:
            return
        raise AssertionError(f"{label} did not fail closed")


def main():
    architecture = json.loads(ARCH_PATH.read_text(encoding="utf-8"))
    portfolio = json.loads(PORTFOLIO_PATH.read_text(encoding="utf-8"))
    validate()

    unknown_claim = copy.deepcopy(architecture)
    unknown_claim["service_coverage"][0]["offering_claim_id"] = "CLM-UNVERIFIED"
    expect_failure(unknown_claim, portfolio, "unknown offering claim")

    irrelevant_job = copy.deepcopy(architecture)
    irrelevant_job["service_coverage"][0]["demand_job_ids"] = ["JTBD-BEN-03"]
    expect_failure(irrelevant_job, portfolio, "irrelevant job mapping")

    invented_history = copy.deepcopy(architecture)
    invented_history["service_coverage"][0]["historical_proof_object_ids"] = ["PROOF-CASE-RURALBIZ"]
    invented_history["service_coverage"][0]["proof_state"] = "OFFERING_AND_HISTORICAL_PROOF_PUBLISHABLE"
    expect_failure(invented_history, portfolio, "historical proof outside case scope")

    promoted_relationship = copy.deepcopy(portfolio)
    target = next(item for item in promoted_relationship["organization_candidates"] if item["id"] == "PORT-ORG-CCI-VALCEA")
    target["classification"] = "PUBLIC_VERIFIED"
    target["publication_allowed"] = True
    target["relationship_to_euroconsult"] = "CLIENT"
    expect_failure(architecture, promoted_relationship, "unsupported organization relationship")

    invented_project_role = copy.deepcopy(portfolio)
    target = next(item for item in invented_project_role["project_candidates"] if item["id"] == "PORT-QUEUE-FAS")
    target["euroconsult_role"] = "CONSULTANT"
    expect_failure(architecture, invented_project_role, "unsupported project role")

    print("EUCONS R03 service/proof fail-closed tests passed")


if __name__ == "__main__":
    main()
