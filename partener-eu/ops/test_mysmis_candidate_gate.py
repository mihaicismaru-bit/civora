#!/usr/bin/env python3
"""Regression tests for controlled MySMIS exact-call fail-closed outcomes."""
from mysmis_candidate_gate import validate_payload


def base_payload(status: str) -> dict:
    return {
        "status": status,
        "materialFactUse": False,
        "publishAuthorized": False,
        "openCallAuthorized": False,
        "candidateInventory": {
            "exactIdentityCompleteForVisiblePage": False,
            "rows": [],
        },
    }


cases = []

payload = base_payload("PASS_CANDIDATE_ONLY")
payload["candidateInventory"] = {
    "exactIdentityCompleteForVisiblePage": True,
    "rows": [{"callCode": "EXACT-1"}],
}
cases.append(("candidate pass", not validate_payload(payload, 0)))

payload = base_payload("PROVISIONAL_FAIL_CLOSED")
cases.append(("controlled provisional fail-closed", not validate_payload(payload, 2)))

payload = base_payload("PARSER_SEMANTIC_DRIFT_FAIL_CLOSED")
cases.append(("controlled semantic-drift fail-closed", not validate_payload(payload, 2)))

payload = base_payload("SOURCE_UNAVAILABLE_FAIL_CLOSED")
cases.append(("controlled transport fail-closed", not validate_payload(payload, 0)))

payload = base_payload("PROVISIONAL_FAIL_CLOSED")
payload["publishAuthorized"] = True
cases.append(("publication authority cannot leak", bool(validate_payload(payload, 2))))

payload = base_payload("PROVISIONAL_FAIL_CLOSED")
cases.append(("status/exit mismatch cannot pass", bool(validate_payload(payload, 0))))

payload = base_payload("PROVISIONAL_FAIL_CLOSED")
cases.append(("unexpected execution code cannot pass", bool(validate_payload(payload, 1))))

failed = [name for name, ok in cases if not ok]
if failed:
    raise SystemExit("FAIL MySMIS candidate gate regression: " + "; ".join(failed))
print(f"PASS MySMIS candidate gate regression ({len(cases)} cases)")
