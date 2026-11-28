#!/usr/bin/env python3
"""Offline SURFACEMC EUI capacity-building handoff replay (NO network or publication).

Two distinct EUI non-grant application roles are verified against the pinned
source registry. Acquired original bytes are immutable inputs, not Git state.
No status, application deadline, or funding entitlement is inferred here.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import tempfile
import unicodedata

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu" / "ingest" / "source_registry.json"
SCHEMA = "PARTENER_EUI_CAPACITY_SURFACEMC_HANDOFF_V1"
PARSER_VERSION = "EUI_CAPACITY_NON_GRANT_HANDOFF_REPLAY_V1"
ROLE_MARKERS = {
    "SRC-EU-EUI-PEER-REVIEWS-AUTUMN-2026": ("peer review", "autumn 2026"),
    "SRC-EU-EUI-PEER-REVIEWERS-PERMANENT-2026": ("peer review", "ongoing"),
}
ROOT_KEYS = {"schema", "run_id", "rows"}
ROW_KEYS = {
    "source_id", "requested_url", "final_url", "fetched_at", "raw_file",
    "raw_sha256", "http_status", "content_type", "acquisition_parser_version",
    "source_family", "programme_family", "authority_class", "observation_state",
    "material_fact_use", "open_call_authorized", "publish_authorized", "publication_effect",
}
MAX_BYTES = 4_000_000
SHA = re.compile(r"[0-9a-f]{64}\Z")
RUN = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
FILE = re.compile(r"[A-Za-z0-9_.-]{1,160}\.html\Z")


def strict_json(raw: bytes):
    def unique(pairs):
        obj = {}
        for key, val in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = val
        return obj
    return json.loads(raw, object_pairs_hook=unique)


class Visible(HTMLParser):
    HIDDEN_TAGS = {"head", "script", "style", "noscript", "svg", "template", "iframe", "dialog", "textarea", "select"}
    VOID_TAGS = {"br", "img", "input", "hr", "meta", "link", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.hidden_depth = 0
        self.words = []

    def handle_starttag(self, tag, attrs):
        values = {}
        for key, val in attrs:
            values.setdefault(key.lower(), []).append((val or "").strip().casefold())
        classes = {piece for value in values.get("class", []) for piece in value.split()}
        styles = values.get("style", [])
        concealed = (tag in self.HIDDEN_TAGS or "hidden" in values or "inert" in values
                     or any(v == "true" for v in values.get("aria-hidden", []))
                     or bool(classes & {"hidden", "d-none", "sr-only", "visually-hidden", "invisible", "collapsing"})
                     or any(re.fullmatch(r"d-(?:sm|md|lg|xl|xxl)-none", c) for c in classes)
                     or ("collapse" in classes and "show" not in classes)
                     or ("tab-pane" in classes and "active" not in classes)
                     or any(re.search(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)\b", s) for s in styles)
                     or len(values.get("class", [])) > 1 or len(styles) > 1)
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, concealed))
            if concealed:
                self.hidden_depth += 1

    def handle_endtag(self, tag):
        match = next((i for i in range(len(self.stack) - 1, -1, -1) if self.stack[i][0] == tag), None)
        if match is not None:
            self.hidden_depth -= sum(1 for _, c in self.stack[match:] if c)
            del self.stack[match:]

    def handle_data(self, data):
        if not self.hidden_depth:
            self.words.append(data)


def visible_subject(raw: bytes, markers: tuple[str, str]) -> bool:
    parser = Visible()
    parser.feed(raw.decode("utf-8", "replace"))
    txt = unicodedata.normalize("NFKD", " ".join(parser.words)).casefold()
    txt = " ".join(txt.split())
    return all(marker in txt for marker in markers)


def parse_utc(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value):
        raise ValueError("fetched_at must be UTC seconds with Z")
    date = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if date.utcoffset().total_seconds() != 0:
        raise ValueError("non-UTC fetched_at")
    return value


def replay(manifest: Path, registry: Path = REGISTRY):
    manifest = Path(manifest)
    raw_manifest = manifest.read_bytes()
    doc = strict_json(raw_manifest)
    if not isinstance(doc, dict) or set(doc) != ROOT_KEYS or doc["schema"] != SCHEMA:
        raise ValueError("unknown handoff envelope")
    if not isinstance(doc["run_id"], str) or not RUN.fullmatch(doc["run_id"]):
        raise ValueError("invalid acquisition run_id")
    if not isinstance(doc["rows"], list) or len(doc["rows"]) != 2:
        raise ValueError("exactly two EUI role receipts required")
    entries = strict_json(Path(registry).read_bytes()).get("sources")
    indexed = {r["id"]: r for r in entries if isinstance(r, dict) and r.get("id") in ROLE_MARKERS}
    if set(indexed) != set(ROLE_MARKERS):
        raise ValueError("official EUI sources missing from registry")
    rows = []
    seen = set()
    for row in doc["rows"]:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise ValueError("unexpected/missing raw row fields")
        sid = row["source_id"]
        if sid not in ROLE_MARKERS or sid in seen:
            raise ValueError("EUI source role collision")
        seen.add(sid)
        source = indexed[sid]
        if (row["requested_url"] != source["url"] or row["final_url"] != source["url"]
                or row["authority_class"] != source["authority_class"]
                or row["programme_family"] != source["programme_family"]
                or row["source_family"] != "EU_DIRECT/BRUSSELS/NON_GRANT"
                or row["observation_state"] != "RAW_ACQUIRED_UNRECONCILED"
                or row["publication_effect"] != "NONE"
                or any(row[f] is not False for f in ("material_fact_use", "open_call_authorized", "publish_authorized"))):
            raise ValueError("EUI role, source or publication authority drift")
        if row["http_status"] != 200 or type(row["http_status"]) is not int:
            raise ValueError("raw source transport not HTTP 200")
        if not isinstance(row["content_type"], str) or row["content_type"].split(";", 1)[0].strip().casefold() not in {"text/html", "application/xhtml+xml"}:
            raise ValueError("non-HTML official original")
        if not isinstance(row["acquisition_parser_version"], str) or not RUN.fullmatch(row["acquisition_parser_version"]):
            raise ValueError("missing acquisition parser provenance")
        parse_utc(row["fetched_at"])
        raw_file = row["raw_file"]
        if not isinstance(raw_file, str) or not FILE.fullmatch(raw_file):
            raise ValueError("raw filename must be a local HTML basename")
        path = manifest.parent / raw_file
        if path.is_symlink() or not path.is_file():
            raise ValueError("missing or symlinked original")
        raw = path.read_bytes()
        if not 250 <= len(raw) <= MAX_BYTES or b"<html" not in raw[:4096].lower():
            raise ValueError("raw HTML envelope invalid")
        if not isinstance(row["raw_sha256"], str) or not SHA.fullmatch(row["raw_sha256"]) or hashlib.sha256(raw).hexdigest() != row["raw_sha256"]:
            raise ValueError("immutable raw hash mismatch")
        if not visible_subject(raw, ROLE_MARKERS[sid]):
            raise ValueError("official subject/role not visible in acquired HTML")
        rows.append({
            "source_id": sid, "registered_url": source["url"], "fetched_at": row["fetched_at"],
            "raw_sha256": row["raw_sha256"], "raw_bytes": len(raw),
            "acquisition_parser_version": row["acquisition_parser_version"],
            "parser_version": PARSER_VERSION, "run_id": doc["run_id"],
            "source_family": row["source_family"], "programme_family": row["programme_family"],
            "authority_class": row["authority_class"], "observation_state": "RAW_REPLAY_VERIFIED_NON_GRANT_DISCOVERY",
            "material_fact_use": False, "open_call_authorized": False, "publish_authorized": False,
            "publication_effect": "NONE",
        })
    return {"schema": "PARTENER_EUI_CAPACITY_REPLAY_RECEIPT_V1", "run_id": doc["run_id"],
            "handoff_sha256": hashlib.sha256(raw_manifest).hexdigest(),
            "publication_effect": "NONE", "canonical_corpus_mutation": False,
            "open_call_authorized": False, "publish_authorized": False,
            "rows": sorted(rows, key=lambda r: r["source_id"])}


def selftest():
    import copy
    with tempfile.TemporaryDirectory() as d:
        directory = Path(d)
        source_rows = []
        urls = {
            "SRC-EU-EUI-PEER-REVIEWS-AUTUMN-2026": "https://www.urban-initiative.eu/capacity-building/peer-reviews/call-autumn2026",
            "SRC-EU-EUI-PEER-REVIEWERS-PERMANENT-2026": "https://www.urban-initiative.eu/capacity-building/peer-reviews/ongoing-call-peer-reviews",
        }
        registered = []
        for i, (sid, url) in enumerate(urls.items()):
            text = "European Urban Initiative Peer Reviews Autumn 2026" if i == 0 else "European Urban Initiative Peer Reviews Ongoing Peer Reviewer Call"
            raw = ("<html><body><main><h1>" + text + "</h1><p>Capacity building " + "a" * 240 + "</p></main></body></html>").encode()
            name = f"eui{i}.html"
            (directory / name).write_bytes(raw)
            registered.append({"id": sid, "url": url, "authority_class": "T1_OFFICIAL_EUI_SECRETARIAT", "programme_family": "EUI " + str(i)})
            source_rows.append({
                "source_id": sid, "requested_url": url, "final_url": url,
                "fetched_at": "2026-11-12T08:00:00Z", "raw_file": name,
                "raw_sha256": hashlib.sha256(raw).hexdigest(), "http_status": 200,
                "content_type": "text/html; charset=utf-8", "acquisition_parser_version": "SURFACEMC_RAW_V1",
                "source_family": "EU_DIRECT/BRUSSELS/NON_GRANT", "programme_family": "EUI " + str(i),
                "authority_class": "T1_OFFICIAL_EUI_SECRETARIAT",
                "observation_state": "RAW_ACQUIRED_UNRECONCILED", "material_fact_use": False,
                "open_call_authorized": False, "publish_authorized": False, "publication_effect": "NONE",
            })
        reg = directory / "registry.json"
        reg.write_text(json.dumps({"sources": registered}))
        handoff = {"schema": SCHEMA, "run_id": "TEST-EUI-HANDOFF", "rows": source_rows}
        path = directory / "manifest.json"
        def save(doc):
            path.write_text(json.dumps(doc, sort_keys=True))
        save(handoff)
        good = replay(path, reg)
        assert good == replay(path, reg)
        assert len(good["rows"]) == 2 and not good["publish_authorized"]
        bad_cases = [
            lambda x: x["rows"][0].update({"raw_sha256": "0" * 64}),
            lambda x: x["rows"][0].update({"final_url": x["rows"][1]["final_url"]}),
            lambda x: x["rows"][1].update({"source_id": x["rows"][0]["source_id"]}),
            lambda x: x["rows"][0].update({"open_call_authorized": True}),
            lambda x: x["rows"][0].update({"observation_state": "OPEN_CALL"}),
            lambda x: x["rows"][0].update({"raw_file": "../secrets.html"}),
            lambda x: x["rows"][0].update({"fetched_at": "2026-11-12T08:00:00+02:00"}),
            lambda x: x["rows"][0].update({"extra": "invented"}),
            lambda x: x["rows"][0].update({"authority_class": "T3_SOCIAL"}),
        ]
        for change in bad_cases:
            corrupted = copy.deepcopy(handoff)
            change(corrupted)
            save(corrupted)
            try:
                replay(path, reg)
            except ValueError:
                pass
            else:
                raise AssertionError("tampered EUI handoff accepted")
        save(handoff)
        original = (directory / "eui0.html").read_bytes()
        (directory / "eui0.html").write_bytes(original.replace(b"Autumn 2026", b"Other year "))
        try:
            replay(path, reg)
        except ValueError:
            pass
        else:
            raise AssertionError("changed original accepted")
        (directory / "eui0.html").write_bytes(original)
        hidden = original.replace(b"<h1>", b"<h1 class='d-none'>")
        (directory / "eui0.html").write_bytes(hidden)
        recalc = copy.deepcopy(handoff)
        recalc["rows"][0]["raw_sha256"] = hashlib.sha256(hidden).hexdigest()
        save(recalc)
        try:
            replay(path, reg)
        except ValueError:
            pass
        else:
            raise AssertionError("hidden-only EUI role evidence accepted")
    print("EUI passive SURFACEMC handoff replay: PASS (2 roles; 11 adversarial checks)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", type=Path)
    p.add_argument("--registry", type=Path, default=REGISTRY)
    p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test:
        selftest()
    elif args.manifest:
        print(json.dumps(replay(args.manifest, args.registry), ensure_ascii=False, sort_keys=True, indent=2))
    else:
        p.error("provide --manifest or --self-test")


if __name__ == "__main__":
    main()
