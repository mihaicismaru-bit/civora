#!/usr/bin/env python3
"""Read-only diagnostics for the official Râmnicu Vâlcea Lotus council registers."""
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
        # Official DocManager views exposed by the same database template.
        # These are read-only and used only to resolve whether a council
        # convocation disposition exists for the target date.
        cw.BASE + "/6118d3860998c41ac225705f004dfd17?OpenView&Count=500",
        cw.BASE + "/c586e2c6e478cd3dc2256e8b0022b24e?OpenView&Count=500",
        cw.BASE + "/3d84a029a0242175c2256c5d0039c0c4?OpenView&Count=500",
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
                "text_head": text[:12000],
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
    # Prefer rows whose text looks like the target meeting/convocation; then a
    # bounded generic sample to learn the canonical Lotus record shape.
    def score(row):
        text = (row.get("text") or "").casefold()
        if "14 august 2026" in text or "14.08.2026" in text:
            return 0
        if "convoc" in text and "consili" in text:
            return 1
        if "august" in text:
            return 2
        if "2026" in text:
            return 3
        return 4
    candidates.sort(key=lambda r: (score(r), r["url"]))
    for meta in candidates[:10]:
        result = cw.fetch(meta["url"], timeout=8)
        probe = {
            "url": meta["url"],
            "text": meta.get("text"),
            "class": meta["class"],
            "from": meta.get("from"),
            "ok": result["ok"],
            "status": result["status"],
            "error": result["error"],
        }
        if result["ok"]:
            body_text = cw.to_text(result["body"])
            probe["text_head"] = body_text[:12000]
            plinks, _, ptitle = cw.parse_links(result["url"], result["body"])
            probe["title"] = ptitle
            probe["links"] = [{**x, "class": classify(x["url"])} for x in plinks[:120]]
        probes.append(probe)

    payload = {
        "schema_version": "1.2",
        "pages": pages,
        "link_class_counts": counts,
        "links": links[:1800],
        "record_probes": probes,
        "publication_allowed": False,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pages": len(pages), "links": len(links), "classes": counts, "probes": len(probes)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
