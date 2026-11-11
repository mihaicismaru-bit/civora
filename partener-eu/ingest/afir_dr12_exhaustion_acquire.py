#!/usr/bin/env python3
"""11 Nov DR-12 other-sectors exhaustion original; acquisition-only and review-only.

This does not promote call status, eligibility, deadline, funding or release.
The zootechnical component is intentionally not conflated with other sectors.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import ssl
import sys
import unicodedata
import urllib.request

URL = ("https://www.afir.ro/comunicate/"
       "fondurile-pentru-componenta-alte-sectoare-dr-12-au-fost-epuizate/")
PARSER_VERSION = "AFIR_DR12_OTHER_SECTORS_EXHAUSTION_RAW_V1"
RAW_NAME = "afir-dr12-other-sectors-exhaustion.raw.html"
SCHEMA = "PARTENER_EU_AFIR_DR12_COMPONENT_EXHAUSTION_ORIGINAL_V1"
MAX_BYTES = 2_000_000
# AFIR dated this notice 11 November 2026, 08:48 Romanian time (EET, UTC+02).
# Reject impossible prefabricated receipts independently of the raw hash.
NOTICE_PUBLISHED_AT_UTC = dt.datetime(2026, 11, 11, 6, 48, tzinfo=dt.timezone.utc)
FIELDS = frozenset({
    "schema", "requested_url", "final_url", "fetched_at", "raw_sha256",
    "raw_bytes", "raw_file", "content_type", "http_status", "run_id",
    "parser_version", "programme_family", "source_family", "authority_class",
    "observation_state", "material_fact_use", "open_call_authorized",
    "publish_authorized", "distribution_authorized", "publication_effect",
    "handoff_sha256",
})
OFF = ("material_fact_use", "open_call_authorized", "publish_authorized",
       "distribution_authorized")
HEADERS = {"User-Agent": "PARTENER.EU-AFIR-DR12-Exhaustion/1.0",
           "Accept": "text/html,application/xhtml+xml",
           "Accept-Encoding": "identity", "Cache-Control": "no-cache"}


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def strict_json(text: str) -> dict:
    def unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate notice manifest key")
            out[key] = value
        return out
    def nonfinite(value):
        raise ValueError("non-finite notice manifest number")
    data = json.loads(text, object_pairs_hook=unique, parse_constant=nonfinite)
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("notice manifest schema mismatch")
    return data


def fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).casefold().strip()


class Visible(HTMLParser):
    SKIP = {"head", "script", "style", "noscript", "template", "svg", "iframe",
            "nav", "footer", "dialog", "textarea", "select"}
    VOID = {"img", "meta", "link", "input", "br", "hr", "source", "wbr"}
    HIDDEN_CLASSES = {"hidden", "d-none", "invisible", "visually-hidden", "sr-only"}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.text = []
        self.headings = []

    def handle_starttag(self, tag, attrs):
        attrs_seen = {}
        duplicated = False
        for k, v in attrs:
            if k in attrs_seen and k in {"hidden", "style", "aria-hidden", "inert"}:
                duplicated = True
            attrs_seen.setdefault(k, v or "")
        style = fold(attrs_seen.get("style", "")).replace(" ", "")
        classes = set(fold(attrs_seen.get("class", "")).split())
        hidden = (duplicated or tag in self.SKIP or
                  "hidden" in attrs_seen or "inert" in attrs_seen or
                  bool(classes & self.HIDDEN_CLASSES) or
                  attrs_seen.get("aria-hidden", "").casefold() == "true" or
                  "display:none" in style or "visibility:hidden" in style or
                  "content-visibility:hidden" in style or
                  bool(re.search(r"(?:^|;)opacity:0(?:[.;]|$)", style)))
        if tag not in self.VOID:
            parent_hidden = self.stack[-1][1] if self.stack else False
            self.stack.append((tag, hidden or parent_hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_startendtag(self, tag, attrs):
        # HTML's self-closing slash does not close non-void HTML elements.
        # Treat <div hidden/> / <script/> as open elements: otherwise
        # their browser-hidden descendants could forge the required
        # AFIR notice date, DR identifiers and conditional exception.
        # SVG/MathML roots have true self-closing foreign-content syntax.
        if tag not in self.VOID | {"svg", "math"}:
            self.handle_starttag(tag, attrs)

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if data.strip():
            self.text.append(data.strip())
            if any(t in {"h1", "h2"} for t, _ in self.stack):
                self.headings.append(data.strip())


def validate_official_notice(raw: bytes, content_type: str) -> None:
    if (not isinstance(content_type, str) or
        content_type.split(";", 1)[0].strip().lower()
            not in {"text/html", "application/xhtml+xml"}):
        raise ValueError("notice is not official HTML")
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("notice raw size invalid")
    page = Visible()
    page.feed(raw.decode("utf-8", "replace"))
    heading = fold(" ".join(page.headings))
    body = fold(" ".join(page.text))
    # Match the *specific component* on the official agency article.
    # Never let the broader DR-12 calendar or counters relabel every component.
    required = (
        "11 noiembrie 2026", "dr-12", "alte sectoare",
        "2 decembrie 2026", "au fost epuizate integral",
        "s-a inchis", "sectorul zootehnic", "continua",
    )
    if ("alte sectoare" not in heading or "dr-12" not in heading or
            "epuizate" not in heading or any(term not in body for term in required)):
        raise ValueError("DR-12 exhausted-component notice identity missing")
    if not re.search(
        r"sesiunea pentru componenta alte sectoare.{0,150}s-a inchis", body
    ):
        raise ValueError("DR-12 other-sectors closure statement not established")
    # The deadline referenced by the exhausted *other sectors* component
    # must appear in that same statement, not merely somewhere else on the
    # page (e.g. the unaffected zootechnical component).
    if not re.search(
        r"fondurile alocate prin interventia dr-12.{0,300}"
        r"pentru componenta alte sectoare.{0,140}"
        r"au fost epuizate integral.{0,125}2 decembrie 2026",
        body,
    ):
        raise ValueError("DR-12 exhausted-component source/deadline binding missing")
    if not re.search(
        r"sesiunea de depunere.{0,160}dr-12 continua pentru sectorul zootehnic",
        body,
    ):
        raise ValueError("DR-12 zootechnical counter-scope distinction missing")
    if re.search(
        r"(?:sectorul zootehnic|componenta sector zootehnic).{0,110}"
        r"(?:s-a inchis|fonduri epuizate|s-au epuizat)", body
    ):
        raise ValueError("DR-12 contradictory zootechnical state requires review")

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("AFIR DR-12 official notice redirect needs authority review")


def acquire():
    opener = urllib.request.build_opener(
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(urllib.request.Request(URL, headers=HEADERS), timeout=25) as res:
        fetched_at = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
        ctype = res.headers.get("Content-Type", "")
        if res.geturl() != URL or getattr(res, "status", 200) != 200:
            raise ValueError("AFIR notice endpoint/status changed")
        if (res.headers.get("Content-Encoding") or "identity").lower().strip() != "identity":
            raise ValueError("encoded AFIR notice body unsupported")
        raw = res.read(MAX_BYTES + 1)
        length = res.headers.get("Content-Length")
        if length is not None and (not length.isdigit() or int(length) != len(raw)):
            raise ValueError("AFIR notice was truncated or length invalid")
        validate_official_notice(raw, ctype)
        return raw, ctype, fetched_at


def seal(outdir: Path, raw: bytes, ctype: str, fetched_at: str, run_id: str) -> dict:
    validate_official_notice(raw, ctype)
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", run_id):
        raise ValueError("invalid run_id")
    _time(fetched_at)
    if outdir.is_symlink():
        raise ValueError("symlinked evidence directory")
    outdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": SCHEMA, "requested_url": URL, "final_url": URL,
        "fetched_at": fetched_at, "raw_sha256": sha(raw),
        "raw_bytes": len(raw), "raw_file": RAW_NAME, "content_type": ctype,
        "http_status": 200, "run_id": run_id, "parser_version": PARSER_VERSION,
        "programme_family": "PS_PAC_2023_2027/DR12/ALTE_SECTOARE",
        "source_family": "AFIR", "authority_class": "T1_OFFICIAL_AGENCY",
        "observation_state": "RAW_VERIFIED_SEMANTIC_REVIEW_REQUIRED",
        "publication_effect": "NONE",
        **{field: False for field in OFF},
    }
    manifest["handoff_sha256"] = sha(canonical(manifest))
    with (outdir / RAW_NAME).open("xb") as f:
        f.write(raw)
    with (outdir / "manifest.json").open("xb") as f:
        f.write(json.dumps(manifest, indent=2, sort_keys=True,
                           ensure_ascii=False).encode("utf-8") + b"\n")
    return manifest


def _time(text: str) -> dt.datetime:
    if not isinstance(text, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", text
    ):
        raise ValueError("notice timestamp must be UTC")
    observed = dt.datetime.fromisoformat(text[:-1] + "+00:00")
    if observed < NOTICE_PUBLISHED_AT_UTC:
        raise ValueError("notice receipt predates official publication")
    if observed > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
        raise ValueError("notice fetched_at in future")
    return observed


def replay(outdir: Path) -> dict:
    if outdir.is_symlink() or not outdir.is_dir():
        raise ValueError("evidence directory missing or symlinked")
    if {p.name for p in outdir.iterdir()} != {RAW_NAME, "manifest.json"}:
        raise ValueError("extra or missing evidence files")
    for filename in (RAW_NAME, "manifest.json"):
        if (outdir / filename).is_symlink() or not (outdir / filename).is_file():
            raise ValueError("untrusted evidence file")
    manifest = strict_json((outdir / "manifest.json").read_text(encoding="utf-8"))
    digest = manifest.pop("handoff_sha256")
    if digest != sha(canonical(manifest)):
        raise ValueError("notice manifest fingerprint mismatch")
    if (manifest["schema"] != SCHEMA or manifest["requested_url"] != URL or
        manifest["final_url"] != URL or manifest["raw_file"] != RAW_NAME or
        manifest["http_status"] != 200 or
        manifest["parser_version"] != PARSER_VERSION or
        manifest["programme_family"] != "PS_PAC_2023_2027/DR12/ALTE_SECTOARE" or
        manifest["source_family"] != "AFIR" or
        manifest["authority_class"] != "T1_OFFICIAL_AGENCY" or
        manifest["observation_state"] != "RAW_VERIFIED_SEMANTIC_REVIEW_REQUIRED" or
        manifest["publication_effect"] != "NONE" or
        any(manifest[field] is not False for field in OFF) or
        not isinstance(manifest["run_id"], str) or
        not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", manifest["run_id"])):
        raise ValueError("notice authority/publication gate mismatch")
    _time(manifest["fetched_at"])
    raw = (outdir / RAW_NAME).read_bytes()
    if type(manifest["raw_bytes"]) is not int or manifest["raw_bytes"] != len(raw):
        raise ValueError("notice raw size mismatch")
    if manifest["raw_sha256"] != sha(raw):
        raise ValueError("notice original SHA mismatch")
    validate_official_notice(raw, manifest["content_type"])
    return {"status": "RAW_NOTICE_REPLAY_VERIFIED_NOT_PUBLISHED",
            "raw_sha256": sha(raw), "run_id": manifest["run_id"],
            "publish_authorized": False, "open_call_authorized": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--replay-dir", type=Path)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if bool(args.out) == bool(args.replay_dir):
        parser.error("specify exactly one of --out and --replay-dir")
    try:
        if args.replay_dir:
            result = replay(args.replay_dir)
        else:
            run_id = args.run_id or ("-".join((os.environ.get("GITHUB_RUN_ID", ""),
                                              os.environ.get("GITHUB_RUN_ATTEMPT", "1"))))
            raw, ctype, stamp = acquire()
            seal(args.out, raw, ctype, stamp, run_id)
            result = replay(args.out)
    except (OSError, ValueError, UnicodeError, urllib.error.URLError) as exc:
        print(f"AFIR_DR12_EXHAUSTION_HELD: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
