#!/usr/bin/env python3
"""Runtime hardening for MIPE v2 MySMIS registry identity.

The public Oracle APEX registry exposes each call's stable `p201_cod_apel` only
inside its Info dialog link.  Visible columns are not unique: distinct calls can
share program, type and title.  This adapter extracts exactly one official call
code from each rendered table row, requires a one-to-one unique alignment with
the parsed registry rows, and only then replaces fallback row IDs.  If that
alignment cannot be proven, the base parser is left untouched and the existing
fail-closed duplicate-ID gate rejects the snapshot.
"""
from __future__ import annotations

import argparse
import html
import re
import urllib.parse
from typing import Any

import mipe_ingest_v2 as v2


def decode_apex_text(value: str) -> str:
    text = html.unescape(value or "")
    # APEX encodes separators as JavaScript unicode escapes and then URL-encodes
    # the call code itself (for example \\u00252F -> %2F -> /).
    for _ in range(4):
        before = text
        text = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda match: chr(int(match.group(1), 16)),
            text,
        )
        text = urllib.parse.unquote(text)
        if text == before:
            break
    return text


def extract_call_code(value: str) -> str:
    decoded = decode_apex_text(value)
    match = re.search(
        r"p201_cod_apel=([^&'\"\s<>()]+)",
        decoded,
        flags=re.I,
    )
    return v2.clean(match.group(1)) if match else ""


def extract_row_call_codes(raw_html: str) -> list[str]:
    codes: list[str] = []
    # Restrict extraction to table rows.  That prevents dialog/config script
    # repetitions elsewhere in APEX markup from being mistaken for data rows.
    for match in re.finditer(r"<tr\b[^>]*>.*?</tr>", raw_html, flags=re.I | re.S):
        segment = match.group(0)
        if "p201_cod_apel" not in segment.lower():
            continue
        code = extract_call_code(segment)
        if code:
            codes.append(code)
    return codes


_original_parse_registry_html = v2.parse_registry_html


def patched_parse_registry_html(data: bytes) -> dict[str, Any]:
    parsed = _original_parse_registry_html(data)
    rows = parsed.get("rows") or []
    if not rows:
        return parsed

    raw = data.decode("utf-8", errors="replace")
    codes = extract_row_call_codes(raw)
    # Strict proof gate: never guess row/code alignment.  The snapshot is only
    # promoted when every rendered registry row has one unique stable call code.
    if len(codes) != len(rows) or len(set(codes)) != len(codes):
        parsed["callCodeIdentity"] = {
            "accepted": False,
            "rowCount": len(rows),
            "callCodeCount": len(codes),
            "uniqueCallCodeCount": len(set(codes)),
        }
        return parsed

    for row, code in zip(rows, codes):
        row["id"] = v2.sha256_hex("MYSMIS_CALL_CODE\n" + code)[:24]
        row["infoUrl"] = v2.MYSMIS_REGISTRY_URL
        # Retained in the parser output for diagnostics/provenance.  The base
        # stable-row serializer intentionally keeps only fields used in change
        # detection; the stable hash already incorporates this code.
        row["callCode"] = code

    parsed["callCodeIdentity"] = {
        "accepted": True,
        "rowCount": len(rows),
        "callCodeCount": len(codes),
        "uniqueCallCodeCount": len(set(codes)),
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
