#!/usr/bin/env python3
"""PDDTJ delegated-OI original HTML receipts; acquisition-only, NEVER call authority.

This probe captures the *two pinned delegated intermediary-body pages* already
registered as discovery-only. It does not claim MIPE T1 acquisition, guide
effectiveness, consultation cutoff resolution, OPEN_CALL, or publication.
Per-run raw bytes + canonical handoff are retained only in immutable CI artifacts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import unicodedata
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "partener-eu/ingest/source_registry.json"
VERSION = "PDDTJ_OI_DISCOVERY_ORIGINAL_V1"
SCHEMA = "PARTENER_EU_PDDTJ_OI_NONAUTHORITATIVE_HANDOFF_V1"
MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 25
PINNED = {
    "SRC-ADRVEST-PDDTJ-PARKS-1794-2026": {
        "url": "https://adrvest.ro/parcuri-industriale-si-tehnologice/",
        "host": "adrvest.ro",
        "words": ("parcuri industriale", "1794"),
        "state": "GUIDE_AMENDMENT_DISCOVERED_RAW_PENDING",
        "raw": "adrvest-pddtj-parks-1794.original.html",
    },
    "SRC-ADRCENTRU-PDDTJ-DISABILITY-HOUSING-CONSULT-20261106": {
        "url": "https://www.adrcentru.ro/comunicare/consultare-publica-pddtj-ghidul-solicitantului-actiunea-2-locuinte-sociale-din-cadrul-programului-dezvoltare-durabila-si-tranzitie-justa/",
        "host": "www.adrcentru.ro",
        "words": ("consultare publica", "locuinte sociale", "dizabilitati"),
        "state": "PUBLIC_CONSULTATION_DISCOVERED_RAW_PENDING",
        "raw": "adrcentru-pddtj-housing-consultation.original.html",
    },
}
OFF = {
    "material_fact_use": False,
    "open_call_authorized": False,
    "publish_authorized": False,
    "distribution_authorized": False,
    "canonical_corpus_mutation": False,
    "publication_effect": "NONE",
    "t1_primary_reconciled": False,
}
HTML_TYPES = {"text/html", "application/xhtml+xml"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr"}
INERT = {"head", "script", "style", "noscript", "template", "svg",
         "iframe", "object", "dialog", "textarea", "select", "canvas"}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(value).hexdigest()


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def fold(s):
    t = unicodedata.normalize("NFKD", s)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).casefold()


def unique_pairs(pairs):
    result = {}
    for k, v in pairs:
        if k in result:
            raise ValueError("duplicate manifest/registry key")
        result[k] = v
    return result


def strict_load(data):
    return json.loads(data, object_pairs_hook=unique_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(
                          ValueError("non-finite JSON")))


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.words = []

    def handle_starttag(self, tag, attrs):
        attr = {}
        duplicate_visibility = False
        for k, v in attrs:
            if k in attr and k in {"style", "hidden", "inert", "aria-hidden", "class"}:
                duplicate_visibility = True
            attr.setdefault(k, v or "")
        style = re.sub(r"\s+", "", attr.get("style", "").casefold())
        classes = set(attr.get("class", "").casefold().split())
        hidden = (duplicate_visibility or tag in INERT
                  or (tag == "details" and "open" not in attr)
                  or "hidden" in attr or "inert" in attr or "popover" in attr
                  or attr.get("aria-hidden", "").casefold() == "true"
                  or bool(classes & {"d-none", "hidden", "visually-hidden", "sr-only"})
                  or "display:none" in style or "visibility:hidden" in style
                  or "content-visibility:hidden" in style)
        if tag not in VOID:
            self.stack.append((tag, hidden or (self.stack[-1][1] if self.stack else False)))

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID | {"svg", "math"}:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, text):
        if not self.stack or not self.stack[-1][1]:
            self.words.append(text)


def validate_visible(raw, spec):
    if not raw or len(raw) > MAX_BYTES or b"\x00" in raw:
        raise ValueError("empty, binary or oversized official HTML")
    view = Visible()
    view.feed(raw.decode("utf-8-sig", errors="replace"))
    text = fold(" ".join(view.words))
    if len(text) < 180 or any(term not in text for term in spec["words"]):
        raise ValueError("low-information shell or wrong official article identity")
    return digest(text.encode("utf-8"))


def source_rows(registry):
    if not isinstance(registry, dict) or not isinstance(registry.get("sources"), list):
        raise ValueError("invalid official registry")
    found = {}
    ids = set()
    for row in registry["sources"]:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("invalid source entry")
        if row["id"] in ids:
            raise ValueError("duplicate source ID")
        ids.add(row["id"])
        if row["id"] in PINNED:
            found[row["id"]] = row
    if set(found) != set(PINNED):
        raise ValueError("PDDTJ delegated OI sources missing")
    for sid, spec in PINNED.items():
        row = found[sid]
        if (row.get("url") != spec["url"]
                or row.get("tier") != "T1B"
                or row.get("observation_state") != spec["state"]
                or row.get("material_fact_use") is not False
                or row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False
                or row.get("source_families") != ["ROMANIA", "MIPE_OI",
                    "GUIDE_AMENDMENT" if "PARKS" in sid else "CONSULTATION"]):
            raise ValueError("PDDTJ registry authority or family drift")
    return found


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("official delegated OI redirect needs manual review")


def network_fetch(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.username or parts.password
            or parts.port not in (None, 443) or parts.fragment):
        raise ValueError("untrusted delegated OI URL")
    opener = build_opener(NoRedirect(),
                          HTTPSHandler(context=ssl.create_default_context()))
    req = Request(url, headers={
        "User-Agent": "PARTENER.EU-PDDTJ-OI-Discovery/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=TIMEOUT_SECONDS) as res:
        if res.geturl() != url or getattr(res, "status", 200) != 200:
            raise ValueError("official OI status/final URL mismatch")
        media = res.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media not in HTML_TYPES:
            raise ValueError("official OI response not HTML")
        if res.headers.get("Content-Encoding", "identity").lower().strip() != "identity":
            raise ValueError("official OI raw bytes were content-encoded")
        raw = res.read(MAX_BYTES + 1)
        length = res.headers.get("Content-Length")
        if len(raw) > MAX_BYTES or (length is not None
            and (not length.isdecimal() or int(length) != len(raw))):
            raise ValueError("truncated/oversized official OI body")
        return raw, media, res.geturl(), 200


def capture(registry, raw_dir, run_id, fetcher=network_fetch, captured_at=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("unsafe or missing run ID")
    sources = source_rows(registry)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    seen = list(raw_dir.iterdir())
    if seen:
        raise ValueError("raw evidence destination must be empty per run")
    rows = []
    for sid, spec in PINNED.items():
        source = sources[sid]
        row = {
            "source_id": sid, "requested_url": spec["url"],
            "programme": source["programmes"][0],
            "source_family": source["source_families"],
            "authority_class": "T1B_DELEGATED_OI_DISCOVERY",
            "observation_state": spec["state"],
            "parser_version": VERSION, "run_id": run_id,
            **OFF,
        }
        try:
            raw, media, final, status = fetcher(spec["url"])
            if urlsplit(final).hostname != spec["host"] or final != spec["url"] or status != 200:
                raise ValueError("final authority/endpoint mismatch")
            if media not in HTML_TYPES:
                raise ValueError("invalid official OI media type")
            sem = validate_visible(raw, spec)
            path = raw_dir / spec["raw"]
            path.write_bytes(raw)
            row.update({
                "fetch_status": "PASS", "http_status": status,
                "content_type": media, "final_url": final,
                "fetched_at": captured_at or utc(), "raw_bytes": len(raw),
                "raw_sha256": digest(raw), "semantic_sha256": sem,
                "raw_file": spec["raw"],
            })
        except (OSError, ValueError, RuntimeError) as error:
            # A 403, timeout, changed article, redirect, or shell is REVIEW,
            # never a synthetic raw receipt or promotion.
            row.update({
                "fetch_status": "FAIL_REVIEW", "error_type": type(error).__name__,
                "fetched_at": None, "raw_sha256": None, "raw_file": None,
            })
        rows.append(row)
    manifest = {
        "schema": SCHEMA, "created_at": captured_at or utc(),
        "run_id": run_id, "rows": rows,
        "fetch_pass": sum(x["fetch_status"] == "PASS" for x in rows),
        "fetch_fail": sum(x["fetch_status"] == "FAIL_REVIEW" for x in rows),
        **OFF,
    }
    manifest["handoff_sha256"] = digest(canonical(manifest))
    validate_replay(manifest, raw_dir, registry)
    return manifest


def validate_replay(manifest, raw_dir, registry):
    sources = source_rows(registry)
    if not isinstance(manifest, dict) or manifest.get("schema") != SCHEMA:
        raise ValueError("PDDTJ handoff schema mismatch")
    proof = manifest.get("handoff_sha256")
    if not isinstance(proof, str) or len(proof) != 64:
        raise ValueError("missing immutable handoff fingerprint")
    base = {k: v for k, v in manifest.items() if k != "handoff_sha256"}
    if digest(canonical(base)) != proof:
        raise ValueError("handoff manifest hash mismatch")
    if any(manifest.get(k) != v for k, v in OFF.items()):
        raise ValueError("publishing boundary changed")
    rows = manifest.get("rows")
    if not isinstance(rows, list) or len(rows) != len(PINNED):
        raise ValueError("PDDTJ receipt source set mismatch")
    if {x.get("source_id") for x in rows if isinstance(x, dict)} != set(PINNED):
        raise ValueError("duplicate or missing PDDTJ source")
    n_pass = 0
    expected_files = set()
    for row in rows:
        sid = row["source_id"]
        spec = PINNED[sid]
        source = sources[sid]
        fixed = {
            "source_id": sid, "requested_url": spec["url"],
            "programme": source["programmes"][0],
            "source_family": source["source_families"],
            "authority_class": "T1B_DELEGATED_OI_DISCOVERY",
            "observation_state": spec["state"],
            "parser_version": VERSION, "run_id": manifest["run_id"],
            **OFF,
        }
        if any(row.get(k) != v for k, v in fixed.items()):
            raise ValueError("receipt identity/authority drift")
        if row.get("fetch_status") == "PASS":
            n_pass += 1
            if set(row) != set(fixed) | {
                    "fetch_status", "http_status", "content_type", "final_url",
                    "fetched_at", "raw_bytes", "raw_sha256", "semantic_sha256", "raw_file"}:
                raise ValueError("success receipt field mismatch")
            name = spec["raw"]
            expected_files.add(name)
            raw = (Path(raw_dir) / name).read_bytes()
            if (row["raw_file"] != name or row["final_url"] != spec["url"]
                    or row["http_status"] != 200 or row["content_type"] not in HTML_TYPES
                    or row["raw_bytes"] != len(raw) or row["raw_sha256"] != digest(raw)
                    or row["semantic_sha256"] != validate_visible(raw, spec)):
                raise ValueError("raw receipt source/hash/semantic mismatch")
            try:
                stamp = dt.datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() != dt.timedelta(0):
                    raise ValueError("receipt time lacks UTC")
            except (TypeError, AttributeError) as ex:
                raise ValueError("invalid UTC receipt time") from ex
        elif row.get("fetch_status") == "FAIL_REVIEW":
            if set(row) != set(fixed) | {
                    "fetch_status", "error_type", "fetched_at", "raw_sha256", "raw_file"}:
                raise ValueError("failure receipt field mismatch")
            if (not row["error_type"] or row["fetched_at"] is not None
                    or row["raw_sha256"] is not None or row["raw_file"] is not None):
                raise ValueError("failure invented raw provenance")
        else:
            raise ValueError("unknown observation/fetch status")
    if (manifest.get("fetch_pass") != n_pass
            or manifest.get("fetch_fail") != len(PINNED) - n_pass
            or set(x.name for x in Path(raw_dir).iterdir()) != expected_files):
        raise ValueError("PDDTJ evidence completeness mismatch")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--replay-manifest", type=Path)
    args = parser.parse_args()
    registry = strict_load(REGISTRY.read_text(encoding="utf-8"))
    if args.replay_manifest:
        obj = strict_load(args.replay_manifest.read_text(encoding="utf-8"))
        validate_replay(obj, args.raw_dir, registry)
    else:
        obj = capture(registry, args.raw_dir, args.run_id or "")
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_bytes(canonical(obj) + b"\n")
    print(json.dumps({"source_count": len(PINNED),
                      "fetch_pass": obj["fetch_pass"], "fetch_fail": obj["fetch_fail"],
                      "t1_primary_reconciled": False, "publication_effect": "NONE"},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
