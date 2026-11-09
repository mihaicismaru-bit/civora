#!/usr/bin/env python3
"""Exact AFIR DR-14/DR-18 extension notice original; acquisition-only, never OPEN."""
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

URL = ("https://www.afir.ro/info-la-zi/"
       "prelungire-sesiune-depunere-proiecte-de-investitii-aferente-dr-14-si-dr-18/")
PARSER_VERSION = "AFIR_DR14_DR18_EXTENSION_NOTICE_RAW_V1"
RAW_NAME = "afir-dr14-dr18-extension-notice.raw.html"
SCHEMA = "PARTENER_EU_AFIR_EXTENSION_ORIGINAL_V1"
MAX_BYTES = 2_000_000
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
HEADERS = {"User-Agent": "PARTENER.EU-AFIR-Notice-Original/1.0",
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
            "nav", "footer", "header", "dialog", "textarea", "select"}
    VOID = {"img", "meta", "link", "input", "br", "hr", "source", "wbr"}
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
        hidden = (duplicated or tag in self.SKIP or
                  "hidden" in attrs_seen or "inert" in attrs_seen or
                  attrs_seen.get("aria-hidden", "").casefold() == "true" or
                  "display:none" in style or "visibility:hidden" in style)
        if tag not in self.VOID:
            parent_hidden = self.stack[-1][1] if self.stack else False
            self.stack.append((tag, hidden or parent_hidden))

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if data.strip():
            self.text.append(data.strip())
            if any(t == "h1" for t, _ in self.stack):
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
    # The article announces one conditional extension, not general OPEN
    # status. These phrases identify the exact official 30 October decision.
    required = ("30 octombrie 2026", "dr-14", "dr-18",
                "16 noiembrie 2026", "16:00",
                "achizitii simple", "6 octombrie", "fonduri disponibile")
    if ("prelungire" not in heading or "dr-14" not in heading or
            "dr-18" not in heading or any(term not in body for term in required)):
        raise ValueError("official AFIR notice identity or conditional scope missing")
    if not re.search(r"nu se prelungeste.{0,200}achizitii simple", body):
        raise ValueError("DR-14 exhausted component exclusion not proven")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("AFIR extension notice redirect needs authority review")


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
        "programme_family": "PS_PAC_2023_2027/DR14_DR18",
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
        manifest["programme_family"] != "PS_PAC_2023_2027/DR14_DR18" or
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
        print(f"AFIR_NOTICE_HELD: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
