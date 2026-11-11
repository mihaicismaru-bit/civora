#!/usr/bin/env python3
"""Water4All 2026: official page -> current EPSS public login, evidence only.

The 6-Oct call-announcement PDF names proposals.etag.ee/water4all/, but the
operator's 23-Oct notice replaced it with epss.proposals.ee/water4all/2026.
Neither a reachable sign-in page nor April's invited-only stage is OPEN_CALL.
This adapter reads the *existing* immutable operator HTML handoff and creates
a separate immutable, non-authorizing gateway receipt. No new source writer.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import ssl
import tempfile
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

import water4all_2026_official_pair as pair

PARSER = "WATER4ALL_2026_EPSS_PUBLIC_GATEWAY_V1"
SCHEMA = "PARTENER_WATER4ALL_2026_EPSS_HANDOFF_V1"
CALL_ID = "SRC-EU-WATER4ALL-2026-JTC"
GATEWAY = "https://epss.proposals.ee/water4all/2026"
OLD_PDF_ENDPOINT = "https://proposals.etag.ee/water4all/"
MAX_BYTES = 2_000_000
LOCKED = ("material_fact_use", "open_call_authorized", "publish_authorized",
          "distribution_authorized", "deadline_authorized", "budget_authorized",
          "eligibility_authorized", "submission_live_authorized")
SOURCE_PATH = f"raw/{CALL_ID}.html"


class OfficialLinkParser(HTMLParser):
    """Only visible labelled anchors beneath the submission heading qualify."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.section = False
        self.heading = None
        self.anchor = None
        self.matches = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"meta", "link", "img", "br", "hr", "input", "source", "wbr"}:
            return
        if tag == "a" and sum(k.lower() == "href" for k, _ in attrs) != 1:
            raise ValueError("missing or duplicated official gateway href")
        if self.anchor is not None and tag == "a":
            raise ValueError("nested official gateway anchor")
        attr = dict(attrs)
        hidden = ((self.stack[-1][1] if self.stack else False) or
                  tag in {"head", "script", "style", "noscript", "svg", "iframe", "nav", "footer"} or
                  "hidden" in attr or (attr.get("aria-hidden") or "").lower() == "true" or
                  "display:none" in (attr.get("style") or "").replace(" ", "").lower())
        self.stack.append((tag, hidden))
        if tag in {"h2", "h3", "h4"}:
            self.heading = []
            self.section = False
        if tag == "a":
            self.anchor = {"href": attr["href"], "hidden": hidden, "label": []}

    def handle_data(self, data):
        if self.stack and self.stack[-1][1]:
            return
        if self.heading is not None:
            self.heading.append(data)
        if self.anchor is not None:
            self.anchor["label"].append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "a" and self.anchor is not None:
            label = " ".join("".join(self.anchor["label"]).lower().split())
            if self.section and not self.anchor["hidden"] and label == "here":
                self.matches.append(self.anchor["href"])
            self.anchor = None
        if tag in {"h2", "h3", "h4"} and self.heading is not None:
            heading = " ".join("".join(self.heading).lower().split())
            self.section = "online submission tool" in heading and "partnering tool" in heading
            self.heading = None
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break


def validate_gateway_url(url):
    part = urlsplit(url)
    if (url != GATEWAY or part.scheme != "https" or
            part.hostname != "epss.proposals.ee" or part.path != "/water4all/2026" or
            part.username or part.password or part.port not in (None, 443) or
            part.query or part.fragment):
        raise ValueError("Water4All exact 2026 EPSS endpoint drift")


def source_link(raw):
    pair.validate_html(CALL_ID, raw, "text/html")
    parser = OfficialLinkParser()
    parser.feed(raw.decode("utf-8", "replace"))
    urls = [urljoin(pair.SOURCES[CALL_ID]["url"], v) for v in parser.matches]
    if not urls or len(set(urls)) != 1:
        raise ValueError("no unique visible official Water4All EPSS anchor")
    validate_gateway_url(urls[0])
    return urls[0]


class VisibleHeadings(pair.VisibleText):
    """Require an actual visible login heading, not a sentence or script text."""
    def __init__(self):
        super().__init__()
        self.active_heading = None
        self.headings = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"} and not self.stack[-1][1]:
            self.active_heading = (tag, [])

    def handle_data(self, data):
        super().handle_data(data)
        if self.active_heading and not (self.stack and self.stack[-1][1]):
            self.active_heading[1].append(data)

    def handle_endtag(self, tag):
        if self.active_heading and tag == self.active_heading[0]:
            self.headings.append(pair.fold(" ".join(self.active_heading[1])))
            self.active_heading = None
        super().handle_endtag(tag)


def validate_gateway(raw, mime):
    if (not isinstance(raw, bytes) or not 250 <= len(raw) <= MAX_BYTES or
            mime.split(";", 1)[0].strip().lower() not in {"text/html", "application/xhtml+xml"} or
            b"<html" not in raw[:8192].lower()):
        raise ValueError("EPSS response content/MIME/size mismatch")
    view = pair.VisibleText()
    view.feed(raw.decode("utf-8", "replace"))
    text = pair.fold(" ".join(view.parts))
    for marker in ("water4all 2026 joint transnational call",
                   "sustainable water management", "sign in"):
        if marker not in text:
            raise ValueError("Water4All public 2026 login identity mismatch")
    headers = VisibleHeadings()
    headers.feed(raw.decode("utf-8", "replace"))
    if "sign in" not in headers.headings:
        raise ValueError("Water4All 2026 visible login heading missing")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("EPSS public gateway redirect refused")


def fetch_gateway():
    validate_gateway_url(GATEWAY)
    opener = build_opener(HTTPSHandler(context=ssl.create_default_context()), NoRedirect())
    req = Request(GATEWAY, headers={
        "User-Agent": "PARTENER.EU-water4all-public-identity/1.0",
        "Accept": "text/html,application/xhtml+xml", "Accept-Encoding": "identity",
        "Cache-Control": "no-cache",
    })
    with opener.open(req, timeout=25) as response:
        validate_gateway_url(response.geturl())
        if response.status != 200:
            raise ValueError("EPSS HTTP status mismatch")
        if (response.headers.get("Content-Encoding") or "identity").lower() != "identity":
            raise ValueError("EPSS transformed content rejected")
        mime = response.headers.get("Content-Type", "")
        raw = response.read(MAX_BYTES + 1)
        length = response.headers.get("Content-Length")
        if length is not None and (not length.isdecimal() or int(length) != len(raw)):
            raise ValueError("EPSS declared body size mismatch")
        validate_gateway(raw, mime)
        return raw, mime, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def origin(source_dir):
    source = pair.replay(source_dir)
    manifest = pair.strict_json((source_dir / "handoff.json").read_bytes())
    receipt = next((r for r in manifest["receipts"] if r["source_id"] == CALL_ID), None)
    if not receipt:
        raise ValueError("operator original missing from paired handoff")
    original = (source_dir / SOURCE_PATH).read_bytes()
    if pair.sha(original) != receipt["raw_sha256"]:
        raise ValueError("operator original SHA drift")
    return manifest, original, source_link(original)


def build(source_dir, gateway_raw, mime, stamp):
    manifest, operator_html, url = origin(source_dir)
    validate_gateway(gateway_raw, mime)
    pair.timestamp_ok(stamp)
    source_stamp = next(r["fetched_at"] for r in manifest["receipts"]
                        if r["source_id"] == CALL_ID)
    delta = datetime.fromisoformat(stamp.replace("Z", "+00:00")) - datetime.fromisoformat(
        source_stamp.replace("Z", "+00:00"))
    if not timedelta(minutes=-5) <= delta <= timedelta(minutes=30):
        raise ValueError("EPSS not observed near official operator fetch")
    result = {
        "schema": SCHEMA, "run_id": manifest["run_id"], "parser_version": PARSER,
        "programme_family": pair.FAMILY, "source_family": "EU_DIRECT/BRUSSELS/PUBLIC_EPSS_LOGIN",
        "authority_class": "T1B_PUBLIC_LOGIN_NOT_SUBMISSION_AUTHORITY",
        "observation_state": "PUBLIC_2026_EPSS_GATEWAY_ONLY_STAGE1_EXPIRED",
        "source_pair_handoff_sha256": manifest["handoff_sha256"],
        "official_operator_url": pair.SOURCES[CALL_ID]["url"],
        "official_operator_raw_sha256": pair.sha(operator_html),
        "pdf_historic_endpoint_not_current": OLD_PDF_ENDPOINT,
        "requested_url": url, "final_url": GATEWAY, "http_status": 200,
        "raw_path": "raw/epss_2026.html", "raw_sha256": pair.sha(gateway_raw),
        "raw_bytes": len(gateway_raw), "content_type": mime,
        "fetched_at": stamp,
        "requires": ["authenticated_current_submission_stage",
                     "2026_pdf_and_national_rules_semantic_reconciliation",
                     "reviewed_exact_call_admission"],
        "publication_effect": "NONE", **{key: False for key in LOCKED},
    }
    result["handoff_sha256"] = pair.sha(pair.canonical(result))
    return result


def replay(source_dir, out):
    if (not out.is_dir() or out.is_symlink() or
            {p.name for p in out.iterdir()} != {"raw", "handoff.json"} or
            (out / "raw").is_symlink() or (out / "handoff.json").is_symlink() or
            {p.name for p in (out / "raw").iterdir()} != {"epss_2026.html"} or
            (out / "raw/epss_2026.html").is_symlink()):
        raise ValueError("EPSS immutable file-set mismatch")
    manifest = pair.strict_json((out / "handoff.json").read_bytes())
    raw = (out / "raw/epss_2026.html").read_bytes()
    expected = build(source_dir, raw, manifest.get("content_type"), manifest.get("fetched_at"))
    if manifest != expected:
        raise ValueError("EPSS immutable source binding/provenance/policy mismatch")
    return {"status": "EPSS_PUBLIC_LOGIN_RAW_REPLAY_VERIFIED_NON_AUTHORIZING",
            "raw_sha256": manifest["raw_sha256"], "run_id": manifest["run_id"],
            "open_call_authorized": False, "publication_effect": "NONE"}


def seal(source_dir, out, raw, mime, stamp):
    data = build(source_dir, raw, mime, stamp)
    if out.exists() or out.is_symlink() or out.parent.is_symlink():
        raise ValueError("immutable EPSS output must not already exist")
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="water4all-epss-", dir=out.parent) as tmp:
        stage = Path(tmp)
        (stage / "raw").mkdir()
        (stage / "raw/epss_2026.html").write_bytes(raw)
        (stage / "handoff.json").write_bytes(pair.canonical(data) + b"\n")
        stage.rename(out)
    return replay(source_dir, out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--source-dir", type=Path, required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--out", type=Path)
    group.add_argument("--replay-dir", type=Path)
    a = p.parse_args()
    if a.replay_dir:
        result = replay(a.source_dir, a.replay_dir)
    else:
        origin(a.source_dir)
        result = seal(a.source_dir, a.out, *fetch_gateway())
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
