#!/usr/bin/env python3
"""Read-only diagnostics for the official Râmnicu Vâlcea Lotus HCL register."""
from __future__ import annotations

import json
import re
import urllib.parse

import council_watch_rm_valcea as cw

OUT = cw.ROOT / "editorial" / "council_watch_rm_valcea_diag.json"


def classify(url: str) -> str:
    low = urllib.parse.unquote(url).lower()
    if "$file" in low:
        return "attachment"
    if "opendocument" in low:
        return "open_document"
    if "openview" in low:
        return "open_view"
    if re.search(r"/[0-9a-f]{32}(?:\?|$)", low):
        return "unid_record"
    return "other"


def main() -> int:
    seeds = [
        cw.BASE + "/vwHotarariByAn?OpenView&Count=500",
        cw.BASE + "/f4ea1f1d59c125fec22571090052215b?OpenView&Count=500",
        cw.BASE + "/d8c74d540a4c4a9bc2256c6900408bec?OpenView&Count=500",
        cw.BASE + "/7bc19da5efdf2be6c2256c59003667d1?OpenView&Count=500",
    ]
    pages = []
    all_links = []
    for seed in seeds:
        result = cw.fetch(seed, timeout=10)
        row = {"url": seed, "ok": result["ok"], "status": result["status"], "error": result["error"]}
        if result["ok"]:
            links, frames, title = cw.parse_links(result["url"], result["body"])
            text = cw.to_text(result["body"])
            row.update({
                "title": title,
                "link_count": len(links),
                "frame_count": len(frames),
                "text_head": text[:7000],
            })
            for link in links:
                all_links.append({**link, "class": classify(link["url"]), "from": result["url"]})
        pages.append(row)

    dedup = {}
    for row in all_links:
        dedup.setdefault(row["url"], row)
    links = list(dedup.values())
    counts = {}
    for row in links:
        counts[row["class"]] = counts.get(row["class"], 0) + 1

    probes = []
    candidates = [r for r in links if r["class"] in {"open_document", "unid_record", "other"}]
    candidates.sort(key=lambda r: (0 if "2026" in (r.get("text") or "") else 1, r["url"]))
    for meta in candidates[:6]:
        result = cw.fetch(meta["url"], timeout=8)
        probe = {
            "url": meta["url"],
            "text": meta.get("text"),
            "class": meta["class"],
            "ok": result["ok"],
            "status": result["status"],
            "error": result["error"],
        }
        if result["ok"]:
            body_text = cw.to_text(result["body"])
            probe["text_head"] = body_text[:7000]
            plinks, _, ptitle = cw.parse_links(result["url"], result["body"])
            probe["title"] = ptitle
            probe["links"] = [{**x, "class": classify(x["url"])} for x in plinks[:100]]
        probes.append(probe)

    payload = {
        "schema_version": "1.1",
        "pages": pages,
        "link_class_counts": counts,
        "links": links[:1200],
        "record_probes": probes,
        "publication_allowed": False,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(pages), "links": len(links), "classes": counts, "probes": len(probes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
