#!/usr/bin/env python3
"""AFIR DR-31 11-Nov-2026 guide consultation: official HTML acquisition only.

Consultation is not a funding-call window. Nothing here authorizes OPEN,
beneficiary eligibility, call deadline, budgets, LKG or public distribution.
The guide PDF is deliberately NOT interpreted by this HTML adapter.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import unicodedata
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

REGISTRY = Path(__file__).with_name("source_registry.json")
PARSER_VERSION = "AFIR_DR31_CONSULTATION_PAIR_RAW_V1"
SCHEMA = "PARTENER_AFIR_DR31_CONSULTATION_PAIR_V1"
FAMILY = "PS_PAC_2023_2027/DR31"
MAX_BYTES = 2_000_000
PUBLISHED_UTC = datetime(2026, 11, 11, 16, 0, tzinfo=timezone.utc)
PRIMARY = "SRC-RO-AFIR-DR31-CONSULTATION-20261111"
DEBATE = "SRC-RO-AFIR-DR31-DEBATE-20261111"
SOURCES = {
    PRIMARY: "https://www.afir.ro/info-la-zi/versiunea-consultativa-a-ghidului-solicitantului-dr-31/",
    DEBATE: "https://www.afir.ro/comunicare/utile/dezbatere-publica/",
}
OFF = ("material_fact_use", "open_call_authorized", "publish_authorized",
       "distribution_authorized", "budget_authorized", "eligibility_authorized",
       "call_deadline_authorized")
HIDDEN_CLASSES = {"hidden", "d-none", "d-sm-none", "d-md-none", "d-lg-none",
                  "d-xl-none", "d-xxl-none", "visually-hidden", "invisible",
                  "sr-only", "screen-reader-text"}
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}
SKIP = {"head", "script", "style", "template", "svg", "math", "noscript",
        "iframe", "nav", "footer", "dialog", "textarea", "select"}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def strict(raw: bytes) -> dict:
    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("duplicate immutable evidence key")
            out[k] = v
        return out
    def reject(_):
        raise ValueError("non-finite immutable evidence number")
    data = json.loads(raw, object_pairs_hook=unique, parse_constant=reject)
    if not isinstance(data, dict):
        raise ValueError("immutable evidence not object")
    return data


def fold(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.translate(str.maketrans({"–": "-", "—": "-", "−": "-"}))
    return re.sub(r"\s+", " ", value).strip()


class Visible(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        seen = {}
        dup = False
        for k, v in attrs:
            if k in seen and k in {"style", "class", "hidden", "inert", "aria-hidden"}:
                dup = True
            seen.setdefault(k, v or "")
        style = re.sub(r"\s+", "", seen.get("style", "").casefold())
        classes = set(seen.get("class", "").casefold().split())
        hidden = (dup or tag in SKIP or "hidden" in seen or "inert" in seen
                  or "popover" in seen or bool(classes & HIDDEN_CLASSES)
                  or (tag == "details" and "open" not in seen)
                  or seen.get("aria-hidden", "").strip().casefold() == "true"
                  or "display:none" in style or "visibility:hidden" in style
                  or "visibility:collapse" in style
                  or "content-visibility:hidden" in style
                  or re.search(r"(?:^|;)opacity:0(?:\.0+)?(?:!important)?(?:;|$)", style) is not None)
        if tag not in VOID:
            self.stack.append((tag, hidden))

    def handle_startendtag(self, tag, attrs):
        # HTML self-closing syntax does not close non-void HTML nodes.
        if tag not in VOID | {"svg", "math"}:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        if value.strip() and not any(v for _, v in self.stack):
            self.parts.append(value.strip())


def validate(sid: str, raw: bytes, mime: str) -> None:
    if sid not in SOURCES or not isinstance(raw, bytes) or not 256 <= len(raw) <= MAX_BYTES:
        raise ValueError("DR31 source/size invalid")
    if not isinstance(mime, str) or mime.split(";", 1)[0].strip().lower() not in {
            "text/html", "application/xhtml+xml"}:
        raise ValueError("DR31 official HTML MIME invalid")
    if b"<html" not in raw[:8192].lower():
        raise ValueError("DR31 HTML envelope missing")
    parser = Visible()
    parser.feed(raw.decode("utf-8", "replace"))
    body = fold(" ".join(parser.parts))
    if sid == PRIMARY:
        # AFIR renders the intervention name across multiple inline HTML
        # fragments. Bind the *ordered* intervention tokens in a short
        # visible span rather than requiring contiguous DOM text nodes.
        must = ("versiunea consultativa", "dr-31",
                "11 noiembrie 2026", "dezbatere publica")
        if re.search(
            r"\\bcontributii\\b.{0,140}\\bfinanciare\\b.{0,140}"
            r"\\bplata\\b.{0,140}\\bprimelor\\b.{0,140}\\basigurare\\b",
            body,
        ) is None:
            raise ValueError("DR31 exact official intervention title not visibly established")
    else:
        must = ("documente aflate in dezbatere publica",
                "ghid solicitant dr 31 consultativ",
                "11.11.2026 - 02.12.2026",
                "contributii financiare la plata primelor de asigurare")
    missing = [marker for marker in must if marker not in body]
    if missing:
        raise ValueError("DR31 exact consultation source/identity/window missing: " + ", ".join(missing))
    if sid == DEBATE and "inaintea aprobarii acestora prin ordin" not in body:
        raise ValueError("DR31 consultation cannot masquerade as approved guide")


def registry_check(path=REGISTRY):
    rows = strict(Path(path).read_bytes()).get("sources")
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("AFIR source registry invalid")
    if len({r.get("id") for r in rows}) != len(rows):
        raise ValueError("duplicate AFIR source IDs")
    index = {r["id"]: r for r in rows}
    for sid, url in SOURCES.items():
        row = index.get(sid)
        if (not row or row.get("url") != url or
            row.get("observation_state") != "PROGRAMMING_PIPELINE" or
            row.get("consultation_state") != "CONSULTATION" or
            row.get("authority_class") != "T1_OFFICIAL_AGENCY" or
            row.get("authority_scope") != "PROGRAMMING_FRAMEWORK" or
            row.get("programme_family") != FAMILY or
            row.get("paired_official_source_id") != (DEBATE if sid == PRIMARY else PRIMARY) or
            not {"ROMANIA", "AFIR", "PROGRAMMING_PIPELINE", "CONSULTATION"}.issubset(
                set(row.get("source_families") or [])) or
            row.get("material_fact_use") is not False or
            row.get("open_call_authorized") is not False or
            row.get("material_fact_publication_authorized") is not False):
            raise ValueError("DR31 registry stage/authority drift")


def stamp_check(value):
    if not isinstance(value, str) or not re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        raise ValueError("DR31 timestamp not canonical UTC")
    observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not PUBLISHED_UTC <= observed <= datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("DR31 receipt predates publication or is in future")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("DR31 official endpoint redirect requires review")


def fetch(sid):
    if sid not in SOURCES:
        raise ValueError("unregistered DR31 source")
    url = SOURCES[sid]
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(url, headers={
        "User-Agent": "PARTENER.EU-DR31-consultation-evidence/1.0",
        "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity",
        "Cache-Control": "no-cache"})
    with opener.open(req, timeout=25) as response:
        if response.geturl() != url or response.status != 200:
            raise ValueError("DR31 exact source endpoint/status drift")
        if (response.headers.get("Content-Encoding") or "identity").strip().lower() != "identity":
            raise ValueError("DR31 original encoding not identity")
        mime = response.headers.get("Content-Type") or ""
        raw = response.read(MAX_BYTES + 1)
        size = response.headers.get("Content-Length")
        if size is not None and (not size.isdecimal() or int(size) != len(raw)):
            raise ValueError("DR31 incomplete original")
    validate(sid, raw, mime)
    timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return raw, mime, timestamp


def build(originals: dict, run_id: str):
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", run_id):
        raise ValueError("invalid DR31 run_id")
    if PRIMARY not in originals or not set(originals).issubset(SOURCES):
        raise ValueError("DR31 official announcement original required")
    rows, files = [], {}
    for sid in sorted(originals):
        raw, mime, timestamp = originals[sid]
        validate(sid, raw, mime)
        stamp_check(timestamp)
        name = "raw-" + sid + ".html"
        files[name] = raw
        row = {
            "source_id": sid, "requested_url": SOURCES[sid],
            "final_url": SOURCES[sid], "fetched_at": timestamp,
            "raw_file": name, "raw_sha256": sha(raw), "raw_bytes": len(raw),
            "content_type": mime, "http_status": 200, "run_id": run_id,
            "parser_version": PARSER_VERSION, "programme_family": FAMILY,
            "source_family": "ROMANIA/AFIR/PROGRAMMING_PIPELINE",
            "authority_class": "T1_OFFICIAL_AGENCY",
            "observation_state": "PROGRAMMING_PIPELINE",
            "consultation_state": "CONSULTATION",
            **{field: False for field in OFF},
        }
        rows.append(row)
    manifest = {
        "schema": SCHEMA, "run_id": run_id, "parser_version": PARSER_VERSION,
        "programme_family": FAMILY, "observation_state": "PROGRAMMING_PIPELINE",
        "consultation_state": "CONSULTATION",
        "pending_source_ids": sorted(set(SOURCES) - set(originals)),
        "receipts": rows, "publication_effect": "NONE",
        **{field: False for field in OFF},
    }
    manifest["handoff_sha256"] = sha(canonical(manifest))
    return manifest, files


def seal(out: Path, originals: dict, run_id: str):
    manifest, originals_by_file = build(originals, run_id)
    out = Path(out)
    if out.is_symlink():
        raise ValueError("symlinked handoff directory")
    out.mkdir(parents=True, exist_ok=False)
    for name, raw in originals_by_file.items():
        with (out / name).open("xb") as f:
            f.write(raw)
    with (out / "manifest.json").open("xb") as f:
        f.write(canonical(manifest))
    replay(out)
    return manifest


def replay(out: Path):
    out = Path(out)
    if out.is_symlink() or not out.is_dir():
        raise ValueError("missing DR31 immutable handoff")
    if any(p.is_symlink() or not p.is_file() for p in out.iterdir()):
        raise ValueError("untrusted DR31 evidence file")
    manifest = strict((out / "manifest.json").read_bytes())
    expected_manifest, _ = build_from_receipts(manifest, out)
    if canonical(expected_manifest) != canonical(manifest):
        raise ValueError("DR31 manifest semantic replay mismatch")
    return {
        "status": "DR31_CONSULTATION_PAIR_RAW_REPLAY_VERIFIED"
                  if not manifest["pending_source_ids"]
                  else "DR31_ARTICLE_RAW_REPLAY_VERIFIED_DEBATE_PENDING",
        "observation_state": "PROGRAMMING_PIPELINE",
        "open_call_authorized": False,
        "publish_authorized": False,
        "pending_source_ids": manifest["pending_source_ids"],
        "raw_hashes": {x["source_id"]: x["raw_sha256"] for x in manifest["receipts"]},
    }


def build_from_receipts(manifest, out):
    if not isinstance(manifest.get("handoff_sha256"), str):
        raise ValueError("DR31 missing handoff hash")
    actual_hash = sha(canonical({k: v for k, v in manifest.items() if k != "handoff_sha256"}))
    if manifest["handoff_sha256"] != actual_hash:
        raise ValueError("DR31 handoff hash mismatch")
    rows = manifest.get("receipts")
    if not isinstance(rows, list) or not rows or len(rows) > len(SOURCES):
        raise ValueError("DR31 receipt array invalid")
    originals, names = {}, {"manifest.json"}
    for row in rows:
        if not isinstance(row, dict) or row.get("source_id") not in SOURCES:
            raise ValueError("DR31 unknown source receipt")
        sid = row["source_id"]
        if sid in originals:
            raise ValueError("DR31 duplicate source receipt")
        name = "raw-" + sid + ".html"
        if row.get("raw_file") != name:
            raise ValueError("DR31 unsafe original file path")
        names.add(name)
        raw = (out / name).read_bytes()
        if sha(raw) != row.get("raw_sha256") or len(raw) != row.get("raw_bytes"):
            raise ValueError("DR31 immutable original was modified")
        if (row.get("requested_url") != SOURCES[sid] or
            row.get("final_url") != SOURCES[sid] or
            row.get("http_status") != 200 or
            row.get("parser_version") != PARSER_VERSION or
            row.get("observation_state") != "PROGRAMMING_PIPELINE" or
            row.get("consultation_state") != "CONSULTATION" or
            any(row.get(field) is not False for field in OFF)):
            raise ValueError("DR31 receipt provenance/authority drift")
        originals[sid] = (raw, row.get("content_type"), row.get("fetched_at"))
    if {p.name for p in out.iterdir()} != names:
        raise ValueError("DR31 extra or missing original")
    rebuilt, _ = build(originals, manifest.get("run_id"))
    return rebuilt, originals


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--out", type=Path)
    mode.add_argument("--replay-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    registry_check()
    if args.replay_dir:
        print(json.dumps(replay(args.replay_dir), sort_keys=True))
        return
    if not args.run_id:
        raise SystemExit("--run-id is required")
    originals = {}
    for sid in SOURCES:
        try:
            originals[sid] = fetch(sid)
        except (ValueError, OSError) as exc:
            if sid == PRIMARY:
                raise
            print(json.dumps({"source_id": sid, "observation_state": "DEBATE_RAW_QUARANTINED",
                              "error_type": type(exc).__name__, "publication_effect": "NONE"}))
    manifest = seal(args.out, originals, args.run_id)
    print(json.dumps({"run_id": manifest["run_id"],
                      "status": "DR31_CONSULTATION_ACQUIRED_NON_AUTHORIZING",
                      "pending_source_ids": manifest["pending_source_ids"],
                      "handoff_sha256": manifest["handoff_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()
