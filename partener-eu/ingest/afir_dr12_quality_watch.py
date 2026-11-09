#!/usr/bin/env python3
"""AFIR DR-12 quality-threshold raw evidence, never a call-status writer.

Runs inside the existing AFIR workflow. Original official bytes are preserved
in a per-run artifact; the two preannounced monthly quality thresholds are
*observations*, not eligibility, funding status, or permission to publish.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import afir_ingest as transport

NOTICE_URL = "https://www.afir.ro/comunicate/170-de-milioane-euro-pentru-exploatatiile-tinerilor-fermieri/"
PARSER_VERSION = "afir-dr12-monthly-quality-watch-v6"
PREVIOUS_PARSER_VERSION = "afir-dr12-monthly-quality-watch-v5"
# AFIR official notice is timestamped 1 Oct 2026, 10:00 EEST (07:00Z).
# An acquisition predating this exact official publication cannot be genuine.
EARLIEST_SOURCE_UTC = dt.datetime(2026, 10, 1, 7, tzinfo=dt.timezone.utc)
MAX_FUTURE_SKEW = dt.timedelta(minutes=5)
PRIOR_PARSER_VERSION = "afir-dr12-monthly-quality-watch-v4"
# An official notice must contain one coherent monthly-stage statement.
# A second (even malformed) announcement must not be silently discarded.
STAGE_INTRO = re.compile(r"\bpragul\s+de\s+calitate\s+lunar\b", re.IGNORECASE)
MAX_STAGE_SPAN = 480
STAGE_PATTERN = re.compile(
    r"pragul\s+de\s+calitate\s+lunar.*?"
    r"\b80\s+de\s+puncte\b.*?"
    r"\b6\s+octombrie\s*[–—-]\s*5\s+noiembrie\s+2026\b.*?"
    r"\b45\s+de\s+puncte\b.*?"
    r"\b6\s+noiembrie\s*[–—-]\s*2\s+decembrie\s+2026\b.*?"
    r"\bpentru\s+ambele\s+componente\b",
    flags=re.IGNORECASE | re.DOTALL,
)
STAGES = (
    {"from_date": "2026-10-06", "through_date": "2026-11-05", "minimum_quality_points": 80},
    {"from_date": "2026-11-06", "through_date": "2026-12-02", "minimum_quality_points": 45},
)


class _VisibleNotice(HTMLParser):
    """Only static visible official prose can establish monthly stage evidence.

    Generic AFIR corpus parsing includes scripts, templates and hidden DOM.
    Those bytes remain in the immutable original but cannot become a threshold.
    """

    VOID = frozenset({
        "area", "base", "br", "col", "embed", "hr", "img", "input",
        "link", "meta", "param", "source", "track", "wbr",
    })
    INERT = frozenset({
        "head", "script", "style", "noscript", "template", "svg", "math",
        "iframe", "object", "canvas", "dialog", "select", "textarea",
        "datalist",
    })
    HIDDEN_CLASSES = frozenset({
        "d-none", "hidden", "invisible", "visually-hidden", "sr-only",
    })
    VISIBILITY_ATTRIBUTES = frozenset({
        "style", "class", "hidden", "inert", "aria-hidden", "popover", "open",
    })

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[tuple[str, bool]] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values: dict[str, str] = {}
        ambiguous = False
        for name, value in attrs:
            name = name.lower()
            if name in values and name in self.VISIBILITY_ATTRIBUTES:
                ambiguous = True
            values.setdefault(name, value or "")
        style = re.sub(r"\s+", "", values.get("style", "").casefold())
        classes = set(values.get("class", "").casefold().split())
        hidden = (
            ambiguous
            or tag in self.INERT
            or (tag == "details" and "open" not in values)
            or "hidden" in values or "inert" in values
            or "popover" in values
            or values.get("aria-hidden", "").strip().casefold() == "true"
            or bool(classes & self.HIDDEN_CLASSES)
            or re.search(r"(?:^|;)display:none(?:!important)?(?:;|$)", style) is not None
            or re.search(r"(?:^|;)visibility:(?:hidden|collapse)(?:!important)?(?:;|$)", style) is not None
            or re.search(r"(?:^|;)content-visibility:hidden(?:!important)?(?:;|$)", style) is not None
            or re.search(r"(?:^|;)opacity:0(?:\.0+)?(?:!important)?(?:;|$)", style) is not None
        )
        if tag not in self.VOID:
            self.stack.append((tag, hidden))
            self.hidden_depth += int(hidden)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        # HTML's non-void <div hidden/> is NOT a closed element. HTMLParser's
        # default calls handle_endtag immediately, exposing forged hidden text.
        # Only actual void elements can be self-closing in text/html.
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.hidden_depth -= sum(int(hidden) for _, hidden in self.stack[index:])
                del self.stack[index:]
                break

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth and data.strip():
            self.parts.append(data.strip())


def parse_notice(raw: bytes) -> list[dict]:
    """Admit exact stage evidence only if both ranges and both components occur."""
    if not isinstance(raw, bytes) or not raw or len(raw) > 12_000_000:
        raise ValueError("empty or oversized AFIR DR-12 raw source")
    parser = _VisibleNotice()
    parser.feed(raw.decode("utf-8", "replace"))
    text = transport.clean(" ".join(parser.parts))
    if not re.search(r"\bDR\s*[-–]\s*12\b", text, re.IGNORECASE):
        raise ValueError("official DR-12 intervention identity missing")
    intros = list(STAGE_INTRO.finditer(text))
    match = STAGE_PATTERN.search(text)
    # Never stitch 80 points from one announcement to 45 points in another,
    # or accept a second conflicting/duplicate monthly-stage announcement.
    if (len(intros) != 1 or match is None or match.start() != intros[0].start()
            or match.end() - match.start() > MAX_STAGE_SPAN):
        raise ValueError("AFIR DR-12 monthly stages missing, duplicated or contradictory")
    return [dict(stage, components=["ZOOTEHNIC", "VEGETAL"]) for stage in STAGES]


def official_html_mime(value: object) -> bool:
    """Accept only a real HTML media type, not substring lookalikes."""
    return isinstance(value, str) and value.split(";", 1)[0].strip().lower() in (
        "text/html", "application/xhtml+xml"
    )


def validated_receipt_time(value: object) -> dt.datetime:
    """Require plausible UTC source-provenance time on capture AND replay.

    Even correctly hashed source bytes cannot redeem an invented timestamp.
    """
    if not isinstance(value, str):
        raise ValueError("DR-12 receipt fetched_at_utc must be a UTC string")
    try:
        observed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("DR-12 receipt fetched_at_utc invalid") from exc
    if observed.tzinfo is None:
        raise ValueError("DR-12 receipt timestamp must be timezone-aware")
    if observed.utcoffset() != dt.timedelta(0):
        raise ValueError("DR-12 receipt fetched_at_utc must be UTC")
    if observed < EARLIEST_SOURCE_UTC:
        raise ValueError("DR-12 receipt predates official source publication")
    if observed > dt.datetime.now(dt.timezone.utc) + MAX_FUTURE_SKEW:
        raise ValueError("DR-12 receipt fetched_at_utc is in the future")
    return observed


def capture(
    fetched: dict,
    destination: Path,
    *,
    run_id: str,
    fetched_at_utc: str,
    run_attempt: str = "1",
) -> dict:
    """Write once to a new run-scoped directory; never overwrite prior proof."""
    raw = fetched.get("data")
    if (
        not run_id or not run_id.strip()
        or fetched.get("ok") is not True
        or fetched.get("url") != NOTICE_URL
        or fetched.get("status") != 200
        or not official_html_mime(fetched.get("content_type"))
        or not isinstance(raw, bytes)
    ):
        raise ValueError("DR-12 raw receipt lacks exact official HTTPS identity, status, run or HTML bytes")
    observed = validated_receipt_time(fetched_at_utc)
    stages = parse_notice(raw)
    if destination.exists():
        raise ValueError("DR-12 immutable receipt destination already exists")
    manifest = {
        "schema_version": "1.0",
        "requested_url": NOTICE_URL,
        "final_url": fetched["url"],
        "fetched_at_utc": observed.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "raw_evidence_file": "notice.raw.html",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "http_status": fetched["status"],
        "content_type": fetched.get("content_type"),
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AGENCY",
        "source_publication_date": "2026-10-01",
        "observation_state": "RAW_MONTHLY_QUALITY_STAGE_OBSERVED_PENDING_GUIDE_COUNTER_RECONCILIATION",
        "stage_kind": "PREANNOUNCED_MONTHLY_QUALITY_THRESHOLD",
        "stages": stages,
        "exact_current_call_identifier_verified": False,
        "open_call_authorized": False,
        "eligibility_change_authorized": False,
        "material_fact_action": "NONE",
        "publish_authorized": False,
        "distribution_authorized": False,
    }
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "notice.raw.html").write_bytes(raw)
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest



def _strict_json_pairs(pairs: list[tuple[str, object]]) -> dict:
    """Preserve every JSON key's uniqueness, including inside stage objects."""
    decoded = {}
    for key, value in pairs:
        if key in decoded:
            raise ValueError(f"DR-12 receipt duplicate JSON key: {key}")
        decoded[key] = value
    return decoded


def _reject_nonfinite_json(token: str):
    raise ValueError(f"DR-12 receipt non-finite JSON number: {token}")


def replay_receipt(destination: Path) -> dict:
    """Independently replay an exact, immutable receipt; never authorize facts."""
    # Strict file set: an unexpected sidecar, symlink, or substituted manifest
    # must not pass as the original official-source receipt.
    required_files = {"notice.raw.html", "manifest.json"}
    if (
        destination.is_symlink() or not destination.is_dir()
        or {entry.name for entry in destination.iterdir()} != required_files
        or any(entry.is_symlink() or not entry.is_file() for entry in destination.iterdir())
    ):
        raise ValueError("DR-12 evidence directory has missing, extra or symlinked files")
    raw = (destination / "notice.raw.html").read_bytes()
    manifest = json.loads(
        (destination / "manifest.json").read_text(encoding="utf-8"),
        object_pairs_hook=_strict_json_pairs,
        parse_constant=_reject_nonfinite_json,
    )
    expected_fields = {
        "schema_version", "requested_url", "final_url", "fetched_at_utc",
        "raw_evidence_file", "raw_sha256", "raw_bytes", "http_status",
        "content_type", "parser_version", "run_id", "run_attempt",
        "programme", "source_family", "authority_class",
        "source_publication_date", "observation_state", "stage_kind",
        "stages", "exact_current_call_identifier_verified",
        "open_call_authorized", "eligibility_change_authorized",
        "material_fact_action", "publish_authorized",
        "distribution_authorized",
    }
    if set(manifest) != expected_fields or manifest.get("schema_version") != "1.0":
        raise ValueError("DR-12 receipt schema changed or includes unregistered fields")
    version = manifest.get("parser_version")
    if version not in (PARSER_VERSION, PREVIOUS_PARSER_VERSION, PRIOR_PARSER_VERSION):
        raise ValueError("DR-12 historical receipt parser version unrecognized")
    # Earlier v4/v5 receipts are replayable only if the SAME original source also
    # passes the hardened visible-prose parser. A hidden-only v4 receipt fails.
    expected = {
        "requested_url": NOTICE_URL,
        "final_url": NOTICE_URL,
        "raw_evidence_file": "notice.raw.html",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "raw_bytes": len(raw),
        "parser_version": version,
        "http_status": 200,
        "programme": "PS_PAC_2023_2027/DR12",
        "source_family": "AFIR",
        "authority_class": "T1_OFFICIAL_AGENCY",
        "stage_kind": "PREANNOUNCED_MONTHLY_QUALITY_THRESHOLD",
        "observation_state": "RAW_MONTHLY_QUALITY_STAGE_OBSERVED_PENDING_GUIDE_COUNTER_RECONCILIATION",
        "source_publication_date": "2026-10-01",
        "stages": parse_notice(raw),
        "exact_current_call_identifier_verified": False,
        "open_call_authorized": False,
        "eligibility_change_authorized": False,
        "material_fact_action": "NONE",
        "publish_authorized": False,
        "distribution_authorized": False,
    }
    for field, value in expected.items():
        if manifest.get(field) != value:
            raise ValueError(f"DR-12 immutable replay disagreement: {field}")
    if not official_html_mime(manifest.get("content_type")):
        raise ValueError("DR-12 replay content-type mismatch")
    if not str(manifest.get("run_id") or "").strip():
        raise ValueError("DR-12 replay run_id missing")
    if not str(manifest.get("run_attempt") or "").isdigit():
        raise ValueError("DR-12 replay run_attempt invalid")
    validated_receipt_time(manifest["fetched_at_utc"])
    return manifest


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] == "--replay-dir":
        proof = replay_receipt(Path(sys.argv[2]))
        print(json.dumps({
            "verified": True, "raw_sha256": proof["raw_sha256"],
            "run_id": proof["run_id"], "publish_authorized": False,
        }, sort_keys=True))
        return 0
    if len(sys.argv) != 1:
        print("usage: afir_dr12_quality_watch.py [--replay-dir PATH]", file=sys.stderr)
        return 2
    root = os.environ.get("PARTENER_AFIR_DR12_EVIDENCE_DIR")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not root or not run_id:
        print("DR-12 capture requires a run-scoped evidence destination and GITHUB_RUN_ID", file=sys.stderr)
        return 2
    fetched = transport.fetch(NOTICE_URL, timeout=20)
    if not fetched.get("ok"):
        print("AFIR DR-12 official notice unavailable; preserve LKG, no material admission: "
              + str(fetched.get("error")), file=sys.stderr)
        return 2
    try:
        result = capture(
            fetched, Path(root), run_id=run_id,
            fetched_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
            run_attempt=os.environ.get("GITHUB_RUN_ATTEMPT", "1"),
        )
    except ValueError as exc:
        print(f"AFIR DR-12 receipt rejected; source-bound review only: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "observation_state": result["observation_state"],
        "raw_sha256": result["raw_sha256"],
        "run_id": result["run_id"],
        "publish_authorized": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
