#!/usr/bin/env python3
"""Runtime patch for MIPE v2 MySMIS registry row identity.

Oracle APEX renders the official call code inside a javascript: dialog href.
The base parser intentionally rejects javascript URLs, which made distinct
calls with identical visible names collapse onto the same fallback identity.
This runner extracts only the structured p201_cod_apel value from the official
APEX markup, uses it for stable row identity, and keeps the public provenance
URL on the verified official registry page.
"""
from __future__ import annotations

import argparse
import html
import re
import urllib.parse
from typing import Any, Optional

import mipe_ingest_v2 as v2

CALL_CODE_PREFIX = "CALLCODE:"


def decode_apex_href(value: str) -> str:
    text = html.unescape(value or "")
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
    decoded = decode_apex_href(value)
    match = re.search(r"(?:[?&]|\\b)p201_cod_apel=([^&'\"\\s,)]+)", decoded, flags=re.I)
    return v2.clean(match.group(1)) if match else ""


_original_handle_starttag = v2.RegistryTableParser.handle_starttag


def patched_handle_starttag(self: Any, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
    _original_handle_starttag(self, tag, attrs)
    if tag.lower() != "a" or self._cell is None:
        return
    href = dict(attrs).get("href") or ""
    code = extract_call_code(href)
    if code:
        marker = CALL_CODE_PREFIX + code
        if marker not in self._cell["links"]:
            self._cell["links"].append(marker)


v2.RegistryTableParser.handle_starttag = patched_handle_starttag


def patched_rows_from_matrix(
    matrix: list[list[Any]],
    links_by_row: Optional[list[list[list[str]]]] = None,
) -> list[dict[str, str]]:
    header_index: Optional[int] = None
    columns: dict[int, str] = {}
    for index, raw_row in enumerate(matrix[:20]):
        headers = [v2.normalized_header(cell) for cell in raw_row]
        if {"program operational", "apel", "stare apel"}.issubset(set(headers)):
            header_index = index
            columns = {
                position: v2.HEADER_ALIASES[name]
                for position, name in enumerate(headers)
                if name in v2.HEADER_ALIASES
            }
            break
    if header_index is None:
        return []

    rows: list[dict[str, str]] = []
    for source_index, raw_row in enumerate(matrix[header_index + 1 :], start=header_index + 1):
        row = {
            key: v2.clean(raw_row[position])
            for position, key in columns.items()
            if position < len(raw_row)
        }
        if not (row.get("program") and row.get("callName") and row.get("state")):
            continue

        call_code = ""
        official_links: list[str] = []
        if links_by_row and source_index < len(links_by_row):
            flattened = [url for cell_links in links_by_row[source_index] for url in cell_links]
            for value in flattened:
                if value.startswith(CALL_CODE_PREFIX):
                    call_code = value[len(CALL_CODE_PREFIX) :]
                else:
                    normalized = v2.normalize_url(value)
                    if normalized:
                        official_links.append(normalized)

        if official_links:
            row["infoUrl"] = official_links[-1]
        elif call_code:
            # Keep click-through on the verified registry itself.  The call code
            # remains in the structured provenance row; we do not fabricate a
            # checksum-bearing APEX dialog URL.
            row["infoUrl"] = v2.MYSMIS_REGISTRY_URL

        if call_code:
            stable = "CALL_CODE\n" + call_code
        else:
            stable = row.get("infoUrl") or "\n".join(
                (row["program"], row.get("callType", ""), row["callName"])
            )
        row["id"] = v2.sha256_hex(stable)[:24]
        rows.append(row)
    return rows


v2.rows_from_matrix = patched_rows_from_matrix


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser", action="store_true")
    args = parser.parse_args()
    v2.run(enable_browser=args.browser)


if __name__ == "__main__":
    main()
