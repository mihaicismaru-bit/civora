#!/usr/bin/env python3
"""Regression tests for controlled MySMIS exact-call fail-closed outcomes."""
import importlib.util
from pathlib import Path

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

# Reproduce the live MySMIS condition observed on 2026-09-23: the official
# report emitted the same exact call row twice. Identical repeats are safe to
# collapse for candidate identity; the same call code with conflicting fields
# must remain fail-closed.
root = Path(__file__).resolve().parents[2]
scout_path = root / "partener-eu" / "ingest" / "mysmis_call_inventory_scout.py"
spec = importlib.util.spec_from_file_location("mysmis_call_inventory_scout", scout_path)
assert spec and spec.loader
scout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scout)


def html_row(status: str) -> str:
    return (
        "<tr><td>Program Test</td><td>Competitiv</td><td>Apel Test</td>"
        f"<td>{status}</td><td>1000000</td>"
        "<td><a href='?p201_cod_apel=TEST%2F1'>Info</a></td></tr>"
    )


def html_page(*rows: str) -> str:
    return (
        "<html><body>Apeluri validate 2021-2027 <span>1 - "
        + str(len(rows))
        + " of 954</span><table>"
        "<tr><th>Program operational</th><th>Tip apel</th><th>Apel</th>"
        "<th>Stare apel</th><th>Buget nerambursabil apel</th><th>Info</th></tr>"
        + "".join(rows)
        + "</table></body></html>"
    )


mirrored = scout.parse_inventory(html_page(html_row("FINALIZAT"), html_row("FINALIZAT")))
cases.extend([
    ("identical duplicate rows remain exact", mirrored["exactIdentityCompleteForVisiblePage"] is True),
    ("identical duplicate collapses to one exact identity", mirrored["exactIdentityRowCount"] == 1),
    ("identical duplicate stays auditable", mirrored["mirroredDuplicateCallCodes"] == ["TEST/1"] and mirrored["mirroredDuplicateRowCount"] == 1),
    ("identical duplicate is not a semantic conflict", mirrored["duplicateCallCodes"] == []),
])

conflicting = scout.parse_inventory(html_page(html_row("FINALIZAT"), html_row("DESCHIS")))
cases.extend([
    ("conflicting duplicate remains fail-closed", conflicting["exactIdentityCompleteForVisiblePage"] is False),
    ("conflicting duplicate is surfaced", conflicting["duplicateCallCodes"] == ["TEST/1"]),
])

failed = [name for name, ok in cases if not ok]
if failed:
    raise SystemExit("FAIL MySMIS candidate gate regression: " + "; ".join(failed))
print(f"PASS MySMIS candidate gate regression ({len(cases)} cases)")
