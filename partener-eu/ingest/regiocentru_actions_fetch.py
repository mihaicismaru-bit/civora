#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

SOURCE_ID = "SRC-ADR-CENTRU-PR-ACTIONS"
SOURCE_FAMILY = "ROMANIA_ADR"
PROGRAMME_FAMILY = "PROGRAMUL_REGIUNEA_CENTRU_2021_2027"
AUTHORITY_CLASS = "T1_MANAGING_AUTHORITY"
OBSERVATION_STATE = "CALL_INDEX_DISCOVERY"
ADAPTER_ID = "REGIOCENTRU_ACTIONS_V1"
PARSER_VERSION = "REGIOCENTRU_ACTIONS_FETCH_V2"
DEFAULT_URL = "https://www.regiocentru.ro/actiuni/"
ALLOWED_HOSTS = {"www.regiocentru.ro", "regiocentru.ro"}
ALLOWED_PATH_PREFIXES = ("/actiuni/",)
MAX_BYTES = 4 * 1024 * 1024
USER_AGENT = "CIVORA-PARTENER-EU/1.0 (+https://civora.ro)"
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "publish_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
)
MISSING_FOR_OPEN = [
    "exact_call_or_mysmis_identifier",
    "current_official_exact_action_endpoint",
    "explicit_current_open_status",
    "semantic_reconciliation",
]


class AcquisitionFailure(RuntimeError):
    def __init__(self, message: str, *, failure_class: str, http_status: int | None = None) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.http_status = http_status


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def validate_authority_url(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("RegioCentru acquisition requires HTTPS")
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError(f"unexpected RegioCentru host: {parsed.hostname!r}")
    path = parsed.path or "/"
    if not any(path.startswith(prefix) for prefix in ALLOWED_PATH_PREFIXES):
        raise ValueError(f"unexpected RegioCentru path: {path!r}")


class StrictRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        absolute = urllib.parse.urljoin(req.full_url, newurl)
        validate_authority_url(absolute)
        return super().redirect_request(req, fp, code, msg, headers, absolute)


class ActionLinkParser(HTMLParser):
    def __init__(self, authority_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.authority_url = authority_url
        self._href: str | None = None
        self._text: list[str] = []
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        href = urllib.parse.urljoin(self.authority_url, self._href)
        title = normalize_space(" ".join(self._text))
        self._href = None
        self._text = []
        parsed = urllib.parse.urlparse(href)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
            return
        path = parsed.path or "/"
        if path.rstrip("/") == "/actiuni" or not path.startswith("/actiuni/"):
            return
        if not title:
            title = path.rstrip("/").split("/")[-1].replace("-", " ")
        self.rows.append({"title_candidate": title, "detail_url_candidate": href})


def extract_action_candidates(raw: bytes, authority_url: str) -> list[dict[str, str]]:
    parser = ActionLinkParser(authority_url)
    parser.feed(raw.decode("utf-8", errors="replace"))
    unique: dict[str, dict[str, str]] = {}
    for row in parser.rows:
        url = row["detail_url_candidate"]
        unique.setdefault(url, row)
    return [unique[url] for url in sorted(unique)]


def classify_url_error(exc: urllib.error.URLError) -> str:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, ssl.SSLCertVerificationError):
        return "TLS_CERTIFICATE_VERIFY_FAILED"
    if isinstance(reason, TimeoutError):
        return "TRANSPORT_TIMEOUT"
    return "TRANSPORT_URL_ERROR"


def fetch_raw(url: str = DEFAULT_URL) -> tuple[bytes, str, int, str]:
    validate_authority_url(url)
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl.create_default_context()),
        StrictRedirectHandler(),
    )
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with opener.open(request, timeout=30) as response:
            final_url = response.geturl()
            validate_authority_url(final_url)
            status = int(getattr(response, "status", 200))
            content_type = response.headers.get_content_type().lower()
            if status != 200:
                raise AcquisitionFailure(
                    f"unexpected HTTP status {status}",
                    failure_class=f"HTTP_{status}_UNEXPECTED",
                    http_status=status,
                )
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise AcquisitionFailure(
                    f"unexpected content type {content_type!r}",
                    failure_class="CONTENT_TYPE_DRIFT",
                    http_status=status,
                )
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise AcquisitionFailure(
                    "RegioCentru response exceeded bounded acquisition limit",
                    failure_class="RESPONSE_SIZE_LIMIT_EXCEEDED",
                    http_status=status,
                )
            return data, final_url, status, content_type
    except urllib.error.HTTPError as exc:
        label = "FORBIDDEN" if exc.code == 403 else "HTTP_ERROR"
        raise AcquisitionFailure(
            f"HTTP {exc.code} while acquiring RegioCentru action index",
            failure_class=f"HTTP_{exc.code}_{label}",
            http_status=int(exc.code),
        ) from exc
    except urllib.error.URLError as exc:
        raise AcquisitionFailure(
            "transport failure while acquiring RegioCentru action index",
            failure_class=classify_url_error(exc),
        ) from exc
    except TimeoutError as exc:
        raise AcquisitionFailure(
            "timeout while acquiring RegioCentru action index",
            failure_class="TRANSPORT_TIMEOUT",
        ) from exc


def base_evidence(*, requested_url: str, fetched_at: str, run_id: str) -> dict:
    validate_authority_url(requested_url)
    return {
        "schema_version": "1.1",
        "adapter_id": ADAPTER_ID,
        "parser_version": PARSER_VERSION,
        "run_id": run_id,
        "fetched_at": fetched_at,
        "source_id": SOURCE_ID,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "requested_url": requested_url,
        "material_fact_use": False,
        "open_call_authorized": False,
        "publish_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "requires_exact_action_endpoint": True,
        "requires_semantic_reconcile": True,
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }


def build_evidence(raw: bytes, *, requested_url: str, final_url: str, status: int, content_type: str, fetched_at: str, run_id: str) -> dict:
    validate_authority_url(final_url)
    candidates = extract_action_candidates(raw, authority_url=final_url)
    evidence = base_evidence(requested_url=requested_url, fetched_at=fetched_at, run_id=run_id)
    evidence.update({
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "raw_sha256": sha256_bytes(raw),
        "action_candidate_count": len(candidates),
        "action_candidates": candidates,
        "source_health_state": "HEALTHY",
        "failure_class": None,
        "lkg_required": False,
        "evidence_usable_for_reconciliation": True,
        "current_material_truth_available": False,
    })
    return evidence


def build_degraded_evidence(*, requested_url: str, fetched_at: str, run_id: str, failure_class: str, http_status: int | None = None) -> dict:
    evidence = base_evidence(requested_url=requested_url, fetched_at=fetched_at, run_id=run_id)
    evidence.update({
        "final_url": None,
        "http_status": http_status,
        "content_type": None,
        "raw_sha256": None,
        "action_candidate_count": 0,
        "action_candidates": [],
        "source_health_state": "DEGRADED",
        "failure_class": failure_class,
        "lkg_required": True,
        "evidence_usable_for_reconciliation": False,
        "current_material_truth_available": False,
    })
    return evidence


def validate_evidence(evidence: dict) -> None:
    if evidence.get("source_id") != SOURCE_ID:
        raise ValueError("unexpected source_id")
    if evidence.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("unexpected authority class")
    if evidence.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("action index must remain discovery-only")
    for key in MATERIAL_FLAGS:
        if evidence.get(key) is not False:
            raise ValueError(f"{key} must remain false for call-index evidence")
    if evidence.get("canonical_corpus_mutation") is not False or evidence.get("publication_effect") != "NONE":
        raise ValueError("RegioCentru action-index evidence must remain non-publishing")
    if evidence.get("requires_exact_action_endpoint") is not True or evidence.get("requires_semantic_reconcile") is not True:
        raise ValueError("exact-action evidence and reconcile are mandatory")
    validate_authority_url(str(evidence.get("requested_url", "")))

    state = evidence.get("source_health_state")
    if state == "HEALTHY":
        validate_authority_url(str(evidence.get("final_url", "")))
        if evidence.get("http_status") != 200:
            raise ValueError("healthy RegioCentru evidence requires HTTP 200")
        if evidence.get("content_type") not in ALLOWED_CONTENT_TYPES:
            raise ValueError("healthy RegioCentru evidence has invalid content type")
        if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("raw_sha256") or "")):
            raise ValueError("healthy RegioCentru evidence requires raw SHA-256")
        if evidence.get("lkg_required") is not False or evidence.get("evidence_usable_for_reconciliation") is not True:
            raise ValueError("healthy RegioCentru evidence health contract drift")
        if evidence.get("failure_class") is not None:
            raise ValueError("healthy RegioCentru evidence cannot carry a failure class")
        rows = evidence.get("action_candidates") or []
        if len(rows) != evidence.get("action_candidate_count"):
            raise ValueError("healthy RegioCentru candidate count mismatch")
        for row in rows:
            validate_authority_url(str(row.get("detail_url_candidate", "")))
    elif state == "DEGRADED":
        if evidence.get("final_url") is not None or evidence.get("raw_sha256") is not None or evidence.get("content_type") is not None:
            raise ValueError("degraded RegioCentru evidence cannot fabricate acquired content")
        if evidence.get("action_candidate_count") != 0 or evidence.get("action_candidates") != []:
            raise ValueError("degraded RegioCentru evidence cannot expose candidates")
        if evidence.get("lkg_required") is not True or evidence.get("evidence_usable_for_reconciliation") is not False:
            raise ValueError("degraded RegioCentru evidence must require LKG and block reconciliation")
        if not str(evidence.get("failure_class") or ""):
            raise ValueError("degraded RegioCentru evidence requires failure_class")
    else:
        raise ValueError(f"unexpected RegioCentru source health state: {state!r}")

    if evidence.get("current_material_truth_available") is not False:
        raise ValueError("RegioCentru call index cannot be current material truth")


def persist_evidence(output_dir: str, evidence: dict, raw: bytes | None) -> Path:
    out = Path(output_dir)
    raw_dir = out / "raw"
    handoff_dir = out / "handoff"
    raw_dir.mkdir(parents=True, exist_ok=True)
    handoff_dir.mkdir(parents=True, exist_ok=True)
    if raw is not None:
        raw_path = raw_dir / "regiocentru_actions.html"
        raw_path.write_bytes(raw)
        evidence["raw_path"] = raw_path.as_posix()
    else:
        evidence["raw_path"] = None
    evidence_path = handoff_dir / "regiocentru_actions_fetch.json"
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Bounded acquisition-only adapter for the official Programul Regiunea Centru action index")
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--output-dir", default="partener-eu/ingest/evidence/regiocentru-actions")
    parser.add_argument("--run-id", default="manual")
    args = parser.parse_args()

    fetched_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    raw: bytes | None = None
    try:
        raw, final_url, status, content_type = fetch_raw(args.url)
        evidence = build_evidence(
            raw,
            requested_url=args.url,
            final_url=final_url,
            status=status,
            content_type=content_type,
            fetched_at=fetched_at,
            run_id=args.run_id,
        )
    except AcquisitionFailure as exc:
        evidence = build_degraded_evidence(
            requested_url=args.url,
            fetched_at=fetched_at,
            run_id=args.run_id,
            failure_class=exc.failure_class,
            http_status=exc.http_status,
        )

    validate_evidence(evidence)
    evidence_path = persist_evidence(args.output_dir, evidence, raw)
    print(json.dumps({
        "source_id": SOURCE_ID,
        "source_health_state": evidence["source_health_state"],
        "failure_class": evidence.get("failure_class"),
        "raw_sha256": evidence.get("raw_sha256"),
        "action_candidate_count": evidence["action_candidate_count"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
        "evidence_path": evidence_path.as_posix(),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
