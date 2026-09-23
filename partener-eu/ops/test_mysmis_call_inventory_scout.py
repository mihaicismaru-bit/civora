#!/usr/bin/env python3
"""Regression coverage for exact-call MySMIS inventory diagnostics."""
from __future__ import annotations

import copy
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

from mysmis_call_inventory_scout import call_code_from_href, parse_inventory  # noqa: E402


def info_href(code: str) -> str:
    encoded = code.replace("/", "\\u00252F")
    return "javascript:apex.navigation.dialog('\\u002Fords\\u002Frepo_bo\\u002Fr\\u002Fmysmis-2021\\u002Fdetaliu-apel?p201_cod_apel=" + encoded + "\\u0026clear=Y')"


def page(rows: list[dict[str, str]], total: int | None = None) -> str:
    headers = [
        "Program operațional",
        "Tip apel",
        "Apel",
        "Stare apel",
        "Entități participante",
        "Nr. schițe",
        "Nr. proiecte înregistrate (depuse)",
        "Nr. contracte",
        "Nr. proiecte retrase",
        "Buget nerambursabil apel",
        "Buget total proiecte (schițe & depuse)",
        "Buget Nerambursabil Proiecte Depuse",
        "Info",
    ]
    html = ["<html><body><h1>Apeluri validate 2021-2027</h1>"]
    if total is not None:
        html.append(f"<div>1 - {len(rows)} of {total}</div>")
    html.append("<table><tr>" + "".join(f"<th>{h}</th>" for h in headers) + "</tr>")
    for row in rows:
        values = [
            row["programme"], row["type"], row["call"], row["status"],
            row.get("entities", "1"), row.get("drafts", "2"), row.get("submitted", "3"),
            row.get("contracts", "4"), row.get("withdrawn", "5"), row["budget"],
            row.get("totalBudget", "6"), row.get("submittedBudget", "7"),
        ]
        cells = "".join(f"<td>{value}</td>" for value in values)
        href = row.get("href")
        info = f'<td><a href="{href}">i</a></td>' if href else "<td></td>"
        html.append("<tr>" + cells + info + "</tr>")
    html.append("</table></body></html>")
    return "".join(html)


def fixtures() -> list[dict[str, str]]:
    shared = "Aceeași denumire umană de apel"
    return [
        {
            "programme": "Program Regional Test",
            "type": "Competitiv cu termen-limită de depunere",
            "call": shared,
            "status": "FINALIZAT",
            "budget": "100.000",
            "href": info_href("PRT/101/PRT_P1/OP1"),
        },
        {
            "programme": "Program Regional Test",
            "type": "Competitiv cu termen-limită de depunere",
            "call": shared,
            "status": "DESCHIS",
            "budget": "200.000",
            "href": info_href("PRT/102/PRT_P1/OP1"),
        },
    ]


def main() -> int:
    code = "PFM/169/PFM_P1/NA/P1_OS1/FM_1.1"
    assert call_code_from_href(info_href(code)) == code

    base_rows = fixtures()
    base = parse_inventory(page(base_rows, total=954))
    assert base["validatedCallCount"] == 954
    assert base["visibleRowCount"] == 2
    assert base["exactIdentityRowCount"] == 2
    assert base["exactIdentityCompleteForVisiblePage"] is True
    assert base["paginationRequired"] is True
    assert {row["callCode"] for row in base["rows"]} == {"PRT/101/PRT_P1/OP1", "PRT/102/PRT_P1/OP1"}
    # Same call title must not collapse two exact official call identities.
    assert len(base["rows"]) == 2

    operational = copy.deepcopy(base_rows)
    operational[0]["contracts"] = "999"
    operational[0]["submitted"] = "888"
    operational[0]["totalBudget"] = "999.999.999"
    after_operational = parse_inventory(page(operational, total=954))
    assert after_operational["materialSemanticSha256"] == base["materialSemanticSha256"]

    material = copy.deepcopy(base_rows)
    material[0]["status"] = "DESCHIS"
    after_material = parse_inventory(page(material, total=954))
    assert after_material["materialSemanticSha256"] != base["materialSemanticSha256"]

    missing = copy.deepcopy(base_rows)
    missing[0]["href"] = ""
    missing_result = parse_inventory(page(missing, total=954))
    assert missing_result["exactIdentityCompleteForVisiblePage"] is False
    assert missing_result["exactIdentityRowCount"] == 1
    assert missing_result["identityFailures"][0]["reason"] == "EXACT_CALL_CODE_MISSING_OR_AMBIGUOUS"

    duplicate = copy.deepcopy(base_rows)
    duplicate[1]["href"] = duplicate[0]["href"]
    duplicate_result = parse_inventory(page(duplicate, total=954))
    assert duplicate_result["exactIdentityCompleteForVisiblePage"] is False
    assert duplicate_result["duplicateCallCodes"] == ["PRT/101/PRT_P1/OP1"]

    print("PASS: MySMIS exact-call inventory identity, semantic hash, pagination and fail-closed regressions")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
