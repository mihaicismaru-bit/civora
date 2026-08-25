#!/usr/bin/env python3
import copy
import json
import tempfile
from pathlib import Path

from validate_customer_demand_model import DEFAULT_MODEL, ValidationError, validate


def expect_failure(data, label):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "model.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        try:
            validate(path)
        except ValidationError:
            return
        raise AssertionError(f"{label} did not fail closed")


def main():
    baseline = json.loads(DEFAULT_MODEL.read_text(encoding="utf-8"))
    validate(DEFAULT_MODEL)

    missing_source = copy.deepcopy(baseline)
    missing_source["market_facts"][0]["evidence_urls"] = []
    expect_failure(missing_source, "fact without evidence")

    inferred_hypothesis = copy.deepcopy(baseline)
    inferred_hypothesis["acquisition_hypotheses"][0]["classification"] = "FACT"
    expect_failure(inferred_hypothesis, "hypothesis promoted to fact")

    unknown_service = copy.deepcopy(baseline)
    unknown_service["demand_matrix"][0]["service_ids"] = ["imaginary_service"]
    expect_failure(unknown_service, "unknown service mapping")

    unknown_trigger = copy.deepcopy(baseline)
    unknown_trigger["demand_matrix"][0]["trigger_ids"] = ["TRG-UNSOURCED"]
    expect_failure(unknown_trigger, "unknown trigger mapping")

    privacy_drift = copy.deepcopy(baseline)
    privacy_drift["acceptance"]["no_autonomous_contact"] = False
    expect_failure(privacy_drift, "autonomous contact enabled")

    print("EUCONS R02 customer demand fail-closed tests passed")


if __name__ == "__main__":
    main()
