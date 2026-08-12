#!/usr/bin/env python3
"""Runtime hardening for MIPE v2 MySMIS registry identity.

The public Oracle APEX registry exposes each call's `p201_cod_apel` inside the
Info dialog link. Visible columns alone are not unique. The adapter aligns one
call code with each rendered data row. Repeated call codes are accepted only
when the complete visible row is byte-semantically identical after whitespace
normalization; those duplicate renderings are collapsed to one call. Any
conflicting duplicate remains fail-closed.
"""
from __future__ import annotations

import argparse
import html
import re
import urllib.parse
from collections import defaultdict
from typing import Any

import mipe_ingest_v2 as v2


def decode_apex_text(value: str) -> str:
    text = html.unescape(value or "")
    for _ in range(4):
        before = text
        text = re.sub(r"\\u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), text)
        text = urllib.parse.unquote(text)
        if text == before:
            break
    return text


def extract_call_code(value: str) -> str:
    decoded = decode_apex_text(value)
    match = re.search(r"p201_cod_apel=([^&'\"\s<>()]+)", decoded, flags=re.I)
    return v2.clean(match.group(1)) if match else ""


def extract_row_call_codes(raw_html: str) -> list[str]:
    codes: list[str] = []
    for match in re.finditer(r"<tr\b[^>]*>.*?</tr>", raw_html, flags=re.I | re.S):
        segment = match.group(0)
        if "p201_cod_apel" not in segment.lower():
            continue
        code = extract_call_code(segment)
        if code:
            codes.append(code)
    return codes


def comparable_row(row: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    excluded = {"id", "infoUrl", "callCode"}
    return tuple(sorted((str(key), v2.clean(value)) for key, value in row.items() if key not in excluded))


_original_parse_registry_html = v2.parse_registry_html


def patched_parse_registry_html(data: bytes) -> dict[str, Any]:
    parsed = _original_parse_registry_html(data)
    rows = list(parsed.get("rows") or [])
    if not rows:
        return parsed

    codes = extract_row_call_codes(data.decode("utf-8", errors="replace"))
    if len(codes) != len(rows):
        parsed["callCodeIdentity"] = {
            "accepted": False,
            "reason": "row/call-code count mismatch",
            "rowCount": len(rows),
            "callCodeCount": len(codes),
        }
        return parsed

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ordered_codes: list[str] = []
    for row, code in zip(rows, codes):
        if code not in grouped:
            ordered_codes.append(code)
        grouped[code].append(row)

    conflicts: list[str] = []
    deduplicated = 0
    unique_rows: list[dict[str, Any]] = []
    for code in ordered_codes:
        group = grouped[code]
        signatures = {comparable_row(row) for row in group}
        if len(signatures) != 1:
            conflicts.append(code)
            continue
        row = dict(group[0])
        row["id"] = v2.sha256_hex("MYSMIS_CALL_CODE\n" + code)[:24]
        row["infoUrl"] = v2.MYSMIS_REGISTRY_URL
        row["callCode"] = code
        unique_rows.append(row)
        deduplicated += len(group) - 1

    if conflicts:
        parsed["callCodeIdentity"] = {
            "accepted": False,
            "reason": "conflicting duplicate call-code rows",
            "rowCount": len(rows),
            "callCodeCount": len(codes),
            "uniqueCallCodeCount": len(grouped),
            "conflictingDuplicateCount": len(conflicts),
            "conflictingCallCodes": conflicts[:20],
        }
        return parsed

    was_complete = bool(parsed.get("complete"))
    parsed["rows"] = unique_rows
    parsed["rawRegistryRowCount"] = len(rows)
    parsed["deduplicatedExactRows"] = deduplicated
    if was_complete:
        parsed["total"] = len(unique_rows)
        parsed["range"] = (1, len(unique_rows), len(unique_rows))
        parsed["complete"] = True
    parsed["callCodeIdentity"] = {
        "accepted": True,
        "rowCount": len(rows),
        "callCodeCount": len(codes),
        "uniqueCallCodeCount": len(grouped),
        "deduplicatedExactRows": deduplicated,
    }
    return parsed


v2.parse_registry_html = patched_parse_registry_html


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    v2.run(enable_browser=args.browser)


if __name__ == "__main__":
    main()
