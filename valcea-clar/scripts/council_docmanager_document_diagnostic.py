#!/usr/bin/env python3
"""Diagnose failed Council DocManager document pages without editorial authority.

Reads the most recent Council Fact Kernel state and revisits only the bounded set
of official OpenDocument pages that failed semantic verification. It persists a
sanitized structural fingerprint and a bounded diagnostic of same-UNID HTML
children so the resolver can be improved from observed Lotus markup instead of
by weakening the evidence threshold.

No raw HTML, scripts, cookies, headers or external URLs are persisted. Short
normalized text prefixes are retained only from the public official documents
to identify document shape. This artifact can never promote a Fact Kernel or
publish a story.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import council_docmanager_embedded_resolver as embedded
import council_watch_rm_valcea as council

ROOT = Path(__file__).resolve().parents[1]
KERNELS = ROOT / "editorial" / "fact_kernel_registry.json"
OUTPUT = ROOT / "editorial" / "council_docmanager_document_structure.json"
MAX_TARGETS = 12
MAX_ATTR_ROWS = 40
MAX_QUOTED_ROWS = 40
MAX_CHILD_DIAGNOSTICS = 4
TEXT_PREFIX_LIMIT = 700
ROUTE_ATTRS = {
    "href", "src", "data", "action", "formaction", "onclick", "value",
    "data-href", "data-url", "data-link", "data-target", "data-document",
}
QUOTED = re.compile(r"(?P<q>['\"])(?P<value>[^'\"]{1,2000})(?P=q)", re.S)
UNID_RE = re.compile(r"(?<![0-9a-f])([0-9a-f]{32})(?![0-9a-f])", re.I)


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def _document_unid(url: str) -> str | None:
    matches = list(UNID_RE.finditer(urllib.parse.unquote(str(url or ""))))
    return matches[-1].group(1).upper() if matches else None


def _official_url_shape(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parsed.path)
    low = path.casefold()
    return {
        "path_sha256": sha(path),
        "path_suffix": path[-180:],
        "query_keys": sorted(urllib.parse.parse_qs(parsed.query, keep_blank_values=True).keys()),
        "is_file_attachment": "$file" in low,
        "extension": Path(path).suffix.casefold(),
    }


def _flags(value: str, base_unid: str | None) -> dict[str, Any]:
    decoded = urllib.parse.unquote(html.unescape(str(value or "")))
    low = decoded.casefold()
    unids = [m.group(1).upper() for m in UNID_RE.finditer(decoded)]
    return {
        "value_sha256": sha(decoded),
        "value_length": len(decoded),
        "has_file_literal": "$file" in low,
        "has_open_document": "opendocument" in low,
        "has_open_field": "openfield" in low,
        "has_lotus_path": "hotarari.nsf" in low,
        "lotus_unid_count": len(unids),
        "same_document_unid": bool(base_unid and unids and unids[-1] == base_unid),
    }


def _body_summary(body: str) -> dict[str, Any]:
    text = council.to_text(body)
    compact = re.sub(r"\s+", " ", text).strip()
    return {
        "operative_article_count": len(council.operative_articles(text)),
        "semantic_markers": {
            "annual_authorization": bool(re.search(r"autoriza(?:t|ț)ie\s+anual(?:a|ă)|autorizatie\s+anuala", compact, re.I)),
            "gambling": bool(re.search(r"jocuri\s+de\s+noroc|slot[ -]?machine|pariuri", compact, re.I)),
            "open_document_literal_count": body.casefold().count("opendocument"),
            "open_field_literal_count": body.casefold().count("openfield"),
            "file_literal_count": body.casefold().count("$file") + body.casefold().count("%24file"),
            "window_open_literal_count": body.casefold().count("window.open"),
            "location_literal_count": body.casefold().count("location"),
        },
        "text_prefix": compact[:TEXT_PREFIX_LIMIT],
        "text_prefix_sha256": sha(compact[:1000]),
        "text_length": len(compact),
    }


class StructureParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.base_unid = _document_unid(base_url)
        self.tag_counts: dict[str, int] = {}
        self.route_attrs: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        low_tag = tag.casefold()
        self.tag_counts[low_tag] = self.tag_counts.get(low_tag, 0) + 1
        if len(self.route_attrs) >= MAX_ATTR_ROWS:
            return
        for raw_name, raw_value in attrs:
            name = str(raw_name or "").casefold()
            value = str(raw_value or "").strip()
            if not value:
                continue
            if name in ROUTE_ATTRS or name.startswith("data-"):
                row = {"tag": low_tag, "attr": name, **_flags(value, self.base_unid)}
                canonical = council.canonical_url(self.base_url, urllib.parse.unquote(html.unescape(value)))
                if canonical:
                    row["official_url_shape"] = _official_url_shape(canonical)
                self.route_attrs.append(row)
                if len(self.route_attrs) >= MAX_ATTR_ROWS:
                    return


def failed_targets(document: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for fact in document.get("facts") or []:
        if not isinstance(fact, dict) or fact.get("status") == "verified":
            continue
        provenance = fact.get("kernel_provenance") or {}
        for row in provenance.get("verification") or []:
            if not isinstance(row, dict) or row.get("verified") is True:
                continue
            url = str(row.get("candidate_url") or row.get("url") or "").strip()
            if not url:
                continue
            rows.append({
                "fact_id": fact.get("id"),
                "decision_number": row.get("decision_number"),
                "decision_date": row.get("decision_date"),
                "candidate_url": url,
            })
            if len(rows) >= MAX_TARGETS:
                return rows
    return rows


def diagnose_child(parent_url: str, child_url: str) -> dict[str, Any]:
    fetched = council.fetch(child_url, timeout=18)
    row: dict[str, Any] = {
        "url_sha256": sha(child_url),
        "url_shape": _official_url_shape(child_url),
        "parent_document_unid": _document_unid(parent_url),
        "child_document_unid": _document_unid(child_url),
        "same_document_unid": _document_unid(parent_url) == _document_unid(child_url),
        "reachable": bool(fetched.get("ok")),
        "http_status": fetched.get("status"),
        "body_sha256": fetched.get("sha256"),
        "error": fetched.get("error"),
    }
    if not fetched.get("ok"):
        return row
    body = str(fetched.get("body") or "")
    parser = StructureParser(str(fetched.get("url") or child_url))
    parser.feed(body)
    row["tag_counts"] = parser.tag_counts
    row.update(_body_summary(body))
    return row


def diagnose_target(target: dict[str, Any]) -> dict[str, Any]:
    url = str(target["candidate_url"])
    fetched = council.fetch(url, timeout=18)
    row: dict[str, Any] = {
        "fact_id": target.get("fact_id"),
        "decision_number": target.get("decision_number"),
        "decision_date": target.get("decision_date"),
        "candidate_url_sha256": sha(url),
        "candidate_url_shape": _official_url_shape(url),
        "candidate_document_unid": _document_unid(url),
        "reachable": bool(fetched.get("ok")),
        "http_status": fetched.get("status"),
        "final_url_sha256": sha(str(fetched.get("url") or url)),
        "body_sha256": fetched.get("sha256"),
        "error": fetched.get("error"),
    }
    if not fetched.get("ok"):
        return row

    final_url = str(fetched.get("url") or url)
    body = str(fetched.get("body") or "")
    base_unid = _document_unid(final_url)
    parser = StructureParser(final_url)
    parser.feed(body)

    quoted_rows: list[dict[str, Any]] = []
    for match in QUOTED.finditer(html.unescape(body)):
        value = match.group("value")
        flags = _flags(value, base_unid)
        if not (flags["has_file_literal"] or flags["has_open_document"] or flags["has_open_field"] or flags["has_lotus_path"]):
            continue
        quoted_rows.append(flags)
        if len(quoted_rows) >= MAX_QUOTED_ROWS:
            break

    embedded_links = embedded.embedded_attachment_links(final_url, body)
    child_diagnostics = [
        diagnose_child(final_url, str(link.get("url") or ""))
        for link in embedded_links[:MAX_CHILD_DIAGNOSTICS]
        if str(link.get("url") or "").strip()
    ]
    row.update({
        "tag_counts": parser.tag_counts,
        "route_attributes": parser.route_attrs,
        "route_attribute_count": len(parser.route_attrs),
        "quoted_lotus_literals": quoted_rows,
        "quoted_lotus_literal_count": len(quoted_rows),
        "embedded_attachment_candidate_count": len(embedded_links),
        "embedded_attachment_candidate_hashes": [sha(str(link.get("url") or "")) for link in embedded_links],
        "child_diagnostics": child_diagnostics,
        "child_diagnostic_count": len(child_diagnostics),
        **_body_summary(body),
    })
    return row


def build() -> dict[str, Any]:
    if not KERNELS.is_file():
        return {
            "schema_version": "1.1",
            "instance_id": "valcea",
            "product": "VÂLCEA CLAR failed DocManager document diagnostic",
            "status": "NO_KERNEL_STATE",
            "publication_authority": "NONE",
            "targets": [],
        }
    document = json.loads(KERNELS.read_text(encoding="utf-8"))
    targets = failed_targets(document)
    diagnostics = [diagnose_target(target) for target in targets]
    output = {
        "schema_version": "1.1",
        "instance_id": "valcea",
        "product": "VÂLCEA CLAR failed DocManager document diagnostic",
        "status": "PASS",
        "publication_authority": "NONE",
        "bounds": {
            "target_limit": MAX_TARGETS,
            "route_attribute_limit_per_target": MAX_ATTR_ROWS,
            "quoted_literal_limit_per_target": MAX_QUOTED_ROWS,
            "child_diagnostic_limit_per_target": MAX_CHILD_DIAGNOSTICS,
            "text_prefix_limit": TEXT_PREFIX_LIMIT,
            "raw_html_persisted": False,
            "script_source_persisted": False,
            "external_urls_persisted": False,
        },
        "target_count": len(diagnostics),
        "targets": diagnostics,
        "policy": {
            "development_diagnostic_only": True,
            "may_promote_fact": False,
            "may_publish_story": False,
            "may_reduce_document_coverage_requirement": False,
        },
    }
    output["diagnostic_fingerprint_sha256"] = sha(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return output


def self_test() -> int:
    unid = "0123456789ABCDEF0123456789ABCDEF"
    page = f"https://dm.primariavl.ro/dm/2026/hotarari.nsf/vwHotarariByAn/{unid}?OpenDocument"
    body = f"""
      <html><body><form action="?OpenField">
      <iframe src="/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/$FILE/test.htm"></iframe>
      <script>var x='/dm/2026/hotarari.nsf/93b6e47af3dd4c36c2257ad3003c531b/{unid}/%24FILE/script.htm';</script>
      Art. 1. Se aprobă autorizația anuală pentru jocuri de noroc.
      </form></body></html>
    """
    parser = StructureParser(page)
    parser.feed(body)
    assert parser.tag_counts.get("iframe") == 1
    assert any(row.get("has_file_literal") for row in parser.route_attrs)
    links = embedded.embedded_attachment_links(page, body)
    assert len(links) == 2
    assert all(_official_url_shape(str(link["url"]))["extension"] == ".htm" for link in links)
    flags = _flags(f"/dm/2026/hotarari.nsf/x/{unid}/%24FILE/test.htm", unid)
    assert flags["has_file_literal"] and flags["same_document_unid"]
    summary = _body_summary(body)
    assert summary["operative_article_count"] == 1
    assert summary["semantic_markers"]["annual_authorization"] is True
    assert summary["semantic_markers"]["gambling"] is True
    assert "autorizația anuală" in summary["text_prefix"]
    mock = {
        "facts": [{
            "id": "x", "status": "candidate_hold",
            "kernel_provenance": {"verification": [
                {"decision_number": 1, "decision_date": "2026-01-01", "candidate_url": page, "verified": False},
                {"decision_number": 2, "decision_date": "2026-01-01", "candidate_url": page, "verified": True},
            ]},
        }]
    }
    assert len(failed_targets(mock)) == 1
    print("VÂLCEA CLAR failed DocManager child document diagnostic self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    doc = build()
    if args.check:
        assert doc.get("publication_authority") == "NONE"
        assert (doc.get("policy") or {}).get("may_publish_story") is False
        print(json.dumps({"status": doc.get("status"), "target_count": doc.get("target_count", 0), "publication_authority": "NONE"}, ensure_ascii=False))
        return 0
    OUTPUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": doc.get("status"), "target_count": doc.get("target_count", 0), "output": str(OUTPUT.relative_to(ROOT)), "publication_authority": "NONE"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
