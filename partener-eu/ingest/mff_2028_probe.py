#!/usr/bin/env python3
"""Strict-TLS, evidence-only MFF 2028-2034 official source monitor.

A successful HTTP fetch is an observation, never an adopted-stage or OPEN_CALL
decision. Immutable per-run evidence is uploaded separately by GitHub Actions;
only a read-only health/semantic review ledger is eligible for main.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import ssl
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
REG = ROOT / "partener-eu" / "ingest" / "mff_2028_source_registry.json"
STATE = ROOT / "partener-eu" / "ingest" / "state" / "mff_2028_health.json"
PARSER_VERSION = "mff_2028_probe_v2"
MAX_BYTES = 3_000_000
UA = "Mozilla/5.0 CIVORA-PARTENER-EU/2.0 (+mff-2028-validation)"
OFFICIAL_HOSTS = (
    "consilium.europa.eu", "digital-strategy.ec.europa.eu",
    "eprs.europarl.europa.eu", "fed.mai.gov.ro"
)
FORBIDDEN_CALL_STAGES = {
    "OPEN", "OPEN_CALL", "CLOSED_CALL", "ADOPTED_MFF",
    "PIPELINE_AS_OPEN_CALL", "PUBLICATION_AUTHORIZED",
}
# An editorial summary of parliamentary comments is not a formal EP vote.
# Lock source identity + event dates before a watch row can enter the ledger.
OCTOBER_STAGE_LOCKS = {
    "SRC-EU-MFF-IRISH-NEGOTIATING-BOX-20261010":
        ("PRESIDENCY_NEGOTIATING_PROPOSAL", "2026-10-10", None),
    "SRC-EU-MFF-EP-CORAPPORTEURS-20261016":
        ("PARLIAMENTARY_POSITION_COMMENTARY", "2026-10-16", None),
    "SRC-EU-MFF-CMO-PARTIAL-20261019":
        ("COUNCIL_PARTIAL_CMO_POSITION", "2026-10-19", "2026-10-20"),
    "SRC-EU-MFF-CAP-PARTIAL-20261026":
        ("COUNCIL_PARTIAL_CAP_POSITION", "2026-10-26", "2026-10-28"),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def sem(raw: bytes, ctype: str) -> bytes:
    if "html" not in (ctype or "").lower():
        return raw
    t = raw.decode("utf-8", "ignore")
    t = re.sub(r"<script\b[^>]*>.*?</script>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<style\b[^>]*>.*?</style>", " ", t, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t).strip().encode("utf-8")


def official_https(url: str) -> bool:
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme == "https"
            and parts.username is None
            and parts.password is None
            and parts.port in (None, 443)
            and bool(host)
            and any(host == h or host.endswith("." + h) for h in OFFICIAL_HOSTS)
        )
    except ValueError:
        return False


def same_source_authority(requested_url: str, candidate_url: str) -> bool:
    """Bind a receipt to the exact registered source host, not another T1 host.

    Council, Parliament, Commission and Romanian official hosts are all trusted
    for their *own* registry rows, but a redirect between them is not evidence
    for the original source. New host aliases require explicit review.
    """
    return (
        official_https(requested_url)
        and official_https(candidate_url)
        and urlsplit(requested_url).hostname.lower() == urlsplit(candidate_url).hostname.lower()
    )


class _StrictOfficialRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Validate the source-host identity before following *every* redirect."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not same_source_authority(req.full_url, newurl):
            raise ValueError("MFF redirect would change registered official source authority")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_official(req, timeout=25):
    opener = urllib.request.build_opener(
        _StrictOfficialRedirectHandler(),
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    )
    return opener.open(req, timeout=timeout)


def validate_registry(reg: dict) -> None:
    allowed = set(reg.get("stage_policy") or [])
    if not allowed or allowed.intersection(FORBIDDEN_CALL_STAGES):
        raise ValueError("MFF registry declares call/publication stage")
    seen: set[str] = set()
    for src in reg.get("sources") or []:
        sid = src.get("id", "")
        if not re.fullmatch(r"[A-Z0-9-]{5,100}", sid) or sid in seen:
            raise ValueError("missing, duplicate, or unsafe MFF source id")
        seen.add(sid)
        if not official_https(src.get("url", "")):
            raise ValueError("MFF authority URL is not a strictly verified official HTTPS host")
        if src.get("stage") is not None and src["stage"] not in allowed:
            raise ValueError("MFF source stage is outside non-authorizing registry taxonomy")
        if sid in OCTOBER_STAGE_LOCKS:
            expected = OCTOBER_STAGE_LOCKS[sid]
            observed = (src.get("stage"), src.get("event_date"), src.get("updated_date"))
            if observed != expected:
                raise ValueError("MFF October source identity/stage/date mismatch; fail closed")
        if src.get("class") == "official_parliamentary_analyst_commentary" and src.get("stage") != "PARLIAMENTARY_POSITION_COMMENTARY":
            raise ValueError("Parliamentary commentary cannot be relabelled as a formal EP position")
        if src.get("open_call_authorized", False) is not False or src.get("material_fact_publication_authorized", False) is not False:
            raise ValueError("MFF source attempted to grant publication/call authority")
    if not seen:
        raise ValueError("empty MFF source registry")


def fetch(url: str) -> dict:
    if not official_https(url):
        raise ValueError("untrusted MFF requested URL")
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml;q=0.9"}
    )
    with _open_official(req, timeout=25) as resp:
        status = resp.status
        final_url = resp.geturl()
        ctype = resp.headers.get("content-type") or ""
        if not same_source_authority(url, final_url) or status != 200:
            raise ValueError("untrusted redirect or non-success official response")
        if "html" not in ctype.lower():
            raise ValueError("unexpected official MFF content type")
        # urllib does not transparently decode a compressed response body.
        # Never hash or semantically normalize gzip/br bytes as HTML evidence.
        content_encoding = (resp.headers.get("Content-Encoding") or "identity").strip().lower()
        if content_encoding != "identity":
            raise ValueError("unsupported encoded MFF body; refuse unverified raw semantics")
        raw = resp.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or len(raw) < 256:
            raise ValueError("MFF official body too large or too small; no partial hash")
        declared = resp.headers.get("Content-Length")
        if declared is not None:
            declared = declared.strip()
            if not declared.isdigit() or int(declared) != len(raw):
                raise ValueError("MFF official body differs from declared Content-Length")
        # A 200 response from an official host can still be a WAF/login page.
        # It is not a source receipt, and must not replace last-known evidence.
        html = raw.decode("utf-8", "replace")
        title_match = re.search(r"<title\b[^>]*>(.*?)</title\s*>", html, flags=re.I | re.S)
        if title_match:
            title = re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", title_match.group(1))).strip().lower()
            if title.startswith(("access denied", "just a moment", "verify you are human",
                                 "attention required", "bot verification", "sign in to")):
                raise ValueError("official host returned an interstitial, not source content")
        semantic = sem(raw, ctype)
        if len(semantic) < 80:
            raise ValueError("low-information official MFF response")
        return {
            "raw": raw,
            "http_status": status,
            "final_url": final_url,
            "content_type": ctype,
            "bytes": len(raw),
            "raw_sha256": sha(raw),
            "semantic_sha256": sha(semantic),
            "semantic_bytes": len(semantic),
        }



def replay_evidence(evidence_dir: Path, registry_path: Path = REG) -> dict:
    """Independently verify immutable MFF originals against their exact registry.

    The health/LKG state must never be updated from an unverified handoff.
    This is a source-replay check, NOT a legislative-stage reconciliation or
    publication authorization. Original HTTP headers cannot be reconstructed
    from raw files; their receipt is still non-authorizing.
    """
    manifest_path = evidence_dir / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("MFF replay manifest missing or symlinked")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_registry(registry)
    sources = {src["id"]: src for src in registry["sources"]}
    rows = manifest.get("sources")
    if (manifest.get("schema_version") != "1.0"
            or manifest.get("parser_version") != PARSER_VERSION
            or manifest.get("policy") != "ACQUISITION_EVIDENCE_ONLY_NON_AUTHORIZING"
            or not isinstance(manifest.get("run_id"), str)
            or not manifest["run_id"]
            or not isinstance(rows, list)
            or len(rows) != len(sources)):
        raise ValueError("invalid or incomplete MFF replay manifest")
    seen: set[str] = set()
    expected_files = {"manifest.json"}
    passed = 0
    reviews = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid MFF replay row")
        sid = row.get("id")
        if sid not in sources or sid in seen:
            raise ValueError("duplicate or unknown MFF replay source")
        seen.add(sid)
        src = sources[sid]
        bound = {
            "tier": src["tier"],
            "class": src["class"],
            "stage": src.get("stage"),
            "event_date": src.get("event_date"),
            "updated_date": src.get("updated_date"),
            "url": src["url"],
            "source_family": src.get("source_family", "PROGRAMMING_PIPELINE_MFF_2028_2034"),
            "programme": src.get("programme", "MFF_2028_2034"),
            "authority_class": src.get("authority_class", "T1_OFFICIAL_PROGRAMMING_AUTHORITY"),
            "run_id": manifest["run_id"],
            "parser_version": PARSER_VERSION,
        }
        if any(row.get(key) != value for key, value in bound.items()):
            raise ValueError("MFF replay source identity, stage or provenance drift")
        if (row.get("open_call_authorized") is not False
                or row.get("material_fact_publication_authorized") is not False
                or row.get("publish_authorized") is not False
                or row.get("auto_promote_legislative_stage") is not False):
            raise ValueError("MFF replay attempted publication or adoption promotion")
        if row.get("review_required") is not False and row.get("review_required") is not True:
            raise ValueError("MFF replay review flag is not boolean")
        if not isinstance(row.get("attempted_at_utc"), str) or not row["attempted_at_utc"]:
            raise ValueError("MFF replay attempt time missing")
        if row.get("ok") is True:
            raw_name = sid + ".html"
            raw_path = evidence_dir / raw_name
            if (row.get("health") != "PASS"
                    or row.get("observation_state") != "RAW_FETCHED_STAGE_UNRECONCILED"
                    or row.get("raw_evidence_file") != raw_name
                    or row.get("http_status") != 200
                    or not isinstance(row.get("fetched_at_utc"), str)
                    or not row["fetched_at_utc"]
                    or not same_source_authority(src["url"], str(row.get("final_url") or ""))
                    or "html" not in str(row.get("content_type") or "").lower()
                    or not raw_path.is_file() or raw_path.is_symlink()):
                raise ValueError("MFF replay successful receipt lacks trusted original")
            raw = raw_path.read_bytes()
            semantic = sem(raw, row["content_type"])
            if (len(raw) < 256 or len(raw) > MAX_BYTES
                    or row.get("bytes") != len(raw)
                    or row.get("raw_sha256") != sha(raw)
                    or row.get("semantic_bytes") != len(semantic)
                    or row.get("semantic_sha256") != sha(semantic)):
                raise ValueError("MFF replay original bytes or semantic SHA mismatch")
            passed += 1
            expected_files.add(raw_name)
        elif row.get("ok") is False:
            if (row.get("health") != "FAIL"
                    or row.get("observation_state") != "PROVISIONAL_FAIL_CLOSED"
                    or row.get("review_required") is not False
                    or not row.get("error")
                    or row.get("fetched_at_utc") is not None
                    or row.get("raw_sha256") is not None
                    or row.get("semantic_sha256") is not None
                    or any(key in row for key in (
                        "raw_evidence_file", "bytes", "http_status", "final_url",
                        "content_type", "semantic_bytes"))):
                raise ValueError("MFF failed source contains promoted evidence")
        else:
            raise ValueError("unknown MFF replay health state")
        reviews += int(row["review_required"])
    if seen != set(sources):
        raise ValueError("incomplete MFF replay source set")
    if ({entry.name for entry in evidence_dir.iterdir()} != expected_files
            or any(entry.is_symlink() for entry in evidence_dir.iterdir())):
        raise ValueError("MFF replay has orphaned or symlinked original files")
    expected_summary = {
        "total": len(rows),
        "pass": passed,
        "fail": len(rows) - passed,
        "review_required": reviews,
    }
    if manifest.get("summary") != expected_summary:
        raise ValueError("MFF replay summary disagrees with originals")
    return expected_summary


def run(
    registry_path: Path = REG,
    state_path: Path = STATE,
    evidence_dir: Path | None = None,
    run_id: str | None = None,
) -> dict:
    reg = json.loads(registry_path.read_text(encoding="utf-8"))
    validate_registry(reg)
    old_state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    previous = {x["id"]: x for x in old_state.get("sources", [])}
    rid = run_id or os.environ.get("GITHUB_RUN_ID") or "local-" + now().replace(":", "-")
    rid = re.sub(r"[^A-Za-z0-9_-]", "-", rid)[:100]
    outdir = evidence_dir or Path(os.environ.get("PARTENER_MFF_EVIDENCE_DIR") or (
        Path(tempfile.gettempdir()) / ("partener-mff-evidence-" + rid)
    ))
    # Raw evidence is an immutable per-run handoff. A repeated invocation or
    # reused artifact destination must fail closed before writing any receipt.
    outdir.mkdir(parents=True, exist_ok=False)
    observed = now()
    out = {
        "schema_version": "1.1",
        "observed_at": observed,
        "parser_version": PARSER_VERSION,
        "policy": "strict-official-raw-hash-stage-watch-no-auto-adoption-no-open-call",
        "sources": [],
    }
    for src in reg["sources"]:
        sid = src["id"]
        prior = previous.get(sid, {})
        last_semantic = prior.get("semantic_sha256") or prior.get("last_known_semantic_sha256")
        row = {
            "id": sid,
            "tier": src["tier"],
            "class": src["class"],
            "stage": src.get("stage"),
            "event_date": src.get("event_date"),
            "updated_date": src.get("updated_date"),
            "url": src["url"],
            "source_family": src.get("source_family", "PROGRAMMING_PIPELINE_MFF_2028_2034"),
            "programme": src.get("programme", "MFF_2028_2034"),
            "authority_class": src.get("authority_class", "T1_OFFICIAL_PROGRAMMING_AUTHORITY"),
            "run_id": rid,
            "parser_version": PARSER_VERSION,
            "attempted_at_utc": now(),
            "fetched_at_utc": None,
            "raw_sha256": None,
            "semantic_sha256": None,
            "ok": False,
            "review_required": False,
            "auto_promote_legislative_stage": False,
            "open_call_authorized": False,
            "material_fact_publication_authorized": False,
            "publish_authorized": False,
            "observation_state": "PROVISIONAL_FAIL_CLOSED",
        }
        try:
            result = fetch(src["url"])
            raw = result.pop("raw")
            # Raw original bytes go to one per-run artifact, never to public/product corpus.
            raw_path = outdir / (sid + ".html")
            raw_path.write_bytes(raw)
            row.update(result)
            row.update({
                "ok": True,
                "health": "PASS",
                "fetched_at_utc": now(),
                "raw_evidence_file": raw_path.name,
                "semantic_hash_changed": bool(last_semantic and last_semantic != result["semantic_sha256"]),
                "observation_state": "RAW_FETCHED_STAGE_UNRECONCILED",
            })
            row["review_required"] = row["semantic_hash_changed"]
        except Exception as exc:
            row.update({
                "ok": False,
                "health": "FAIL",
                "error": f"{type(exc).__name__}: {exc}",
                "semantic_hash_changed": False,
                "last_known_semantic_sha256": last_semantic,
            })
        out["sources"].append(row)

    out["summary"] = {
        "total": len(out["sources"]),
        "pass": sum(x["health"] == "PASS" for x in out["sources"]),
        "fail": sum(x["health"] == "FAIL" for x in out["sources"]),
        "review_required": sum(bool(x["review_required"]) for x in out["sources"]),
    }
    manifest = {
        "schema_version": "1.0",
        "run_id": rid,
        "parser_version": PARSER_VERSION,
        "observed_at": observed,
        "policy": "ACQUISITION_EVIDENCE_ONLY_NON_AUTHORIZING",
        "sources": out["sources"],
        "summary": out["summary"],
    }
    (outdir / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    replay_evidence(outdir, registry_path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    result = run()
    print(json.dumps(result["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
