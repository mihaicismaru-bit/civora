from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import sqlite3
from typing import Iterable

from .native_adapt import (
    ACTIVE_NATIVE_PLATFORMS,
    NATIVE_ADAPT_MODEL_VERSION,
    NativeAdaptationBundle,
    NativeBundleStatus,
)

IMAGE_RIGHTS_MODEL_VERSION = "PPOS_IMAGE_RIGHTS_BOUND_VISUAL_V1"
SOCIAL_EDITORIAL_PURPOSE = "SOCIAL_EDITORIAL"
AUTO_ELIGIBLE_RIGHTS = {"OWNED", "LICENSED", "PUBLIC_DOMAIN"}
FORBIDDEN_ACQUISITION_ROUTES = {
    "SOCIAL_DOWNLOAD_UNCLEARED",
    "SEARCH_ENGINE_DOWNLOAD",
    "PRESS_COPY_UNCLEARED",
    "MAP_SCREENSHOT_AS_PHOTO",
}
ALLOWED_ACQUISITION_ROUTES = {
    "LOCAL_OWNED",
    "LICENSED_DIRECT",
    "OPEN_LICENSE_DIRECT",
    "PUBLIC_DOMAIN_DIRECT",
    "SYNTHETIC_FIXTURE",
}


class RightsStatus(str, Enum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    FAIR_USE_REVIEW = "FAIR_USE_REVIEW"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class SubjectClearanceStatus(str, Enum):
    CLEAR = "CLEAR"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PENDING = "PENDING"
    REQUIRED = "REQUIRED"
    BLOCKED = "BLOCKED"


class MediaClass(str, Enum):
    CONTEXTUAL_PHOTO = "CONTEXTUAL_PHOTO"
    PROFILE_PHOTO = "PROFILE_PHOTO"
    DOCUMENT_VISUAL = "DOCUMENT_VISUAL"


class ModificationPolicy(str, Enum):
    ALLOWED = "ALLOWED"
    CROP_RESIZE_ONLY = "CROP_RESIZE_ONLY"
    NO_MODIFICATIONS = "NO_MODIFICATIONS"


class EligibilityStatus(str, Enum):
    ELIGIBLE_RENDER_QA = "ELIGIBLE_RENDER_QA"
    HOLD_RIGHTS = "HOLD_RIGHTS"
    HOLD_HUMAN_REVIEW = "HOLD_HUMAN_REVIEW"
    HOLD_STALE_RIGHTS = "HOLD_STALE_RIGHTS"
    BLOCKED = "BLOCKED"


class VisualBindingStatus(str, Enum):
    READY_RIGHTS_BOUND_VISUAL_INPUT = "READY_RIGHTS_BOUND_VISUAL_INPUT"
    HOLD_INPUT_NOT_READY = "HOLD_INPUT_NOT_READY"
    HOLD_RIGHTS = "HOLD_RIGHTS"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_kind: str
    snapshot_bytes: bytes
    canonical_uri: str
    acquired_at_utc: str
    note: str = ""


@dataclass(frozen=True)
class UsageRequest:
    platform: str
    purpose: str
    intended_at_utc: str
    modifications_required: tuple[str, ...]
    commercial_context: bool
    territory: str
    output_license: str | None = None


@dataclass(frozen=True)
class RightsEligibility:
    eligibility_hash: str
    asset_sha256: str
    root_original_id: str
    rights_record_id: str
    rights_record_hash: str
    platform: str
    purpose: str
    status: str
    reason_codes: tuple[str, ...]
    attribution_text: str
    eligible: bool
    publish_eligible: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RightsBoundVisualInput:
    binding_id: str
    binding_hash: str
    model_version: str
    bundle_id: str
    bundle_hash: str
    asset_sha256: str
    root_original_id: str
    rights_record_id: str
    rights_record_hash: str
    eligibility: tuple[RightsEligibility, ...]
    eligible_platforms: tuple[str, ...]
    blocked_platforms: tuple[str, ...]
    status: str
    visual_input_ready: bool
    state: str = "RIGHTS_BOUND_VISUAL_INPUT_ONLY"
    rights_authority: bool = True
    fact_authority: bool = False
    visual_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["eligibility"] = [item.to_dict() for item in self.eligibility]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _json_tuple(value: Iterable[str]) -> str:
    return _canonical_json(tuple(sorted(set(value))))


def _tuple_from_json(value: str) -> tuple[str, ...]:
    return tuple(json.loads(value))


def _native_bundle_body(bundle: NativeAdaptationBundle) -> dict:
    return {
        "schema_version": bundle.model_version,
        "brief_id": bundle.brief_id,
        "brief_hash": bundle.brief_hash,
        "source_url": bundle.source_url,
        "source_class": bundle.source_class,
        "topic": bundle.topic,
        "locality": bundle.locality,
        "adaptations": [item.to_dict() for item in bundle.adaptations],
        "unknowns": bundle.unknowns,
        "status": bundle.status,
        "rights_input_ready": bundle.rights_input_ready,
        "active_platforms": bundle.active_platforms,
        "state": bundle.state,
        "native_adaptation_authority": bundle.native_adaptation_authority,
        "fact_authority": bundle.fact_authority,
        "visual_authority": bundle.visual_authority,
        "queue_authority": bundle.queue_authority,
        "publish_authority": bundle.publish_authority,
        "network_fetch_performed": bundle.network_fetch_performed,
        "real_account_connection_performed": bundle.real_account_connection_performed,
    }


def _validate_native_bundle(bundle: NativeAdaptationBundle) -> None:
    if not isinstance(bundle, NativeAdaptationBundle):
        raise ValueError("rights binding input must be NativeAdaptationBundle")
    if bundle.model_version != NATIVE_ADAPT_MODEL_VERSION:
        raise ValueError("unsupported native adaptation model version")
    expected_id = _hash({
        "brief_id": bundle.brief_id,
        "brief_hash": bundle.brief_hash,
        "stage": bundle.model_version,
    })
    if expected_id != bundle.bundle_id or _hash(_native_bundle_body(bundle)) != bundle.bundle_hash:
        raise ValueError("native adaptation bundle integrity check failed")
    if bundle.active_platforms != ACTIVE_NATIVE_PLATFORMS:
        raise ValueError("native adaptation active platform set mismatch")
    if bundle.state != "NATIVE_ADAPTATION_ONLY" or not bundle.native_adaptation_authority:
        raise ValueError("rights binding accepts canonical M05 bundles only")
    if bundle.fact_authority or bundle.visual_authority or bundle.queue_authority or bundle.publish_authority:
        raise ValueError("native adaptation bundle carries forbidden downstream authority")
    if bundle.network_fetch_performed or bundle.real_account_connection_performed:
        raise ValueError("rights binding accepts local pre-pilot bundles only")


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS image_source_revisions (
    source_revision_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    source_class TEXT NOT NULL,
    display_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    discovery_role TEXT NOT NULL,
    reuse_default TEXT NOT NULL,
    license_or_basis TEXT NOT NULL,
    status TEXT NOT NULL,
    verified_at_utc TEXT NOT NULL,
    supersedes_source_revision_id TEXT,
    source_hash TEXT NOT NULL UNIQUE,
    UNIQUE(source_id, revision)
);
CREATE TABLE IF NOT EXISTS image_originals (
    original_id TEXT PRIMARY KEY,
    original_sha256 TEXT NOT NULL UNIQUE,
    mime_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    media_class TEXT NOT NULL,
    creator_name TEXT NOT NULL,
    acquisition_route TEXT NOT NULL,
    acquisition_source_revision_id TEXT NOT NULL,
    discovery_source_revision_id TEXT,
    source_url TEXT NOT NULL,
    capture_at_utc TEXT,
    capture_location TEXT,
    subject_clearance_status TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    provenance_hash TEXT NOT NULL UNIQUE,
    FOREIGN KEY(acquisition_source_revision_id) REFERENCES image_source_revisions(source_revision_id),
    FOREIGN KEY(discovery_source_revision_id) REFERENCES image_source_revisions(source_revision_id)
);
CREATE TABLE IF NOT EXISTS image_rights_records (
    rights_record_id TEXT PRIMARY KEY,
    original_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    rights_status TEXT NOT NULL,
    basis_type TEXT NOT NULL,
    rights_holder TEXT NOT NULL,
    license_name TEXT,
    license_version TEXT,
    license_url TEXT,
    permitted_platforms_json TEXT NOT NULL,
    permitted_purposes_json TEXT NOT NULL,
    territory TEXT NOT NULL,
    commercial_use_allowed INTEGER NOT NULL,
    modification_policy TEXT NOT NULL,
    attribution_required INTEGER NOT NULL,
    attribution_text TEXT NOT NULL,
    share_alike_required INTEGER NOT NULL,
    required_output_license TEXT,
    valid_from_utc TEXT,
    expires_at_utc TEXT,
    review_at_utc TEXT,
    revocable INTEGER NOT NULL,
    evidence_set_hash TEXT NOT NULL,
    terms_hash TEXT NOT NULL,
    supersedes_rights_record_id TEXT,
    record_hash TEXT NOT NULL UNIQUE,
    FOREIGN KEY(original_id) REFERENCES image_originals(original_id),
    FOREIGN KEY(supersedes_rights_record_id) REFERENCES image_rights_records(rights_record_id),
    UNIQUE(original_id, revision)
);
CREATE TABLE IF NOT EXISTS image_rights_evidence (
    evidence_id TEXT PRIMARY KEY,
    rights_record_id TEXT NOT NULL,
    evidence_kind TEXT NOT NULL,
    snapshot_sha256 TEXT NOT NULL,
    snapshot_size INTEGER NOT NULL,
    canonical_uri TEXT NOT NULL,
    acquired_at_utc TEXT NOT NULL,
    note TEXT NOT NULL,
    evidence_hash TEXT NOT NULL UNIQUE,
    FOREIGN KEY(rights_record_id) REFERENCES image_rights_records(rights_record_id)
);
CREATE TABLE IF NOT EXISTS image_derivatives (
    derivative_id TEXT PRIMARY KEY,
    derivative_sha256 TEXT NOT NULL UNIQUE,
    parent_sha256 TEXT NOT NULL,
    root_original_id TEXT NOT NULL,
    rights_record_id_at_creation TEXT NOT NULL,
    derivative_kind TEXT NOT NULL,
    transform_json TEXT NOT NULL,
    transform_hash TEXT NOT NULL,
    derivation_hash TEXT NOT NULL UNIQUE,
    FOREIGN KEY(root_original_id) REFERENCES image_originals(original_id),
    FOREIGN KEY(rights_record_id_at_creation) REFERENCES image_rights_records(rights_record_id)
);
"""

APPEND_ONLY_TABLES = (
    "image_source_revisions",
    "image_originals",
    "image_rights_records",
    "image_rights_evidence",
    "image_derivatives",
)


class RightsRegistry:
    def __init__(self, database: str = ":memory:"):
        self.connection = sqlite3.connect(database)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA_SQL)
        for table in APPEND_ONLY_TABLES:
            self.connection.executescript(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_update
                BEFORE UPDATE ON {table}
                BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_delete
                BEFORE DELETE ON {table}
                BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
                """
            )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def integrity_check(self) -> str:
        return str(self.connection.execute("PRAGMA integrity_check").fetchone()[0])

    def register_source_revision(
        self,
        *,
        source_id: str,
        revision: int,
        source_class: str,
        display_name: str,
        source_url: str,
        discovery_role: str,
        reuse_default: str,
        license_or_basis: str,
        status: str,
        verified_at_utc: str,
        supersedes_source_revision_id: str | None = None,
    ) -> str:
        if revision < 1:
            raise ValueError("source revision must be >= 1")
        _parse_utc(verified_at_utc)
        body = {
            "source_id": source_id,
            "revision": revision,
            "source_class": source_class,
            "display_name": display_name,
            "source_url": source_url,
            "discovery_role": discovery_role,
            "reuse_default": reuse_default,
            "license_or_basis": license_or_basis,
            "status": status,
            "verified_at_utc": verified_at_utc,
            "supersedes_source_revision_id": supersedes_source_revision_id,
        }
        source_hash = _hash(body)
        source_revision_id = _hash({"source_hash": source_hash, "stage": IMAGE_RIGHTS_MODEL_VERSION})
        row = self.connection.execute(
            "SELECT * FROM image_source_revisions WHERE source_revision_id=?", (source_revision_id,)
        ).fetchone()
        if row:
            return source_revision_id
        if revision > 1:
            previous = self.connection.execute(
                "SELECT source_revision_id FROM image_source_revisions WHERE source_id=? ORDER BY revision DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if previous is None or previous[0] != supersedes_source_revision_id:
                raise ValueError("source revision must supersede exact current revision")
        self.connection.execute(
            """INSERT INTO image_source_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                source_revision_id, source_id, revision, source_class, display_name, source_url,
                discovery_role, reuse_default, license_or_basis, status, verified_at_utc,
                supersedes_source_revision_id, source_hash,
            ),
        )
        self.connection.commit()
        return source_revision_id

    def register_original(
        self,
        asset_bytes: bytes,
        *,
        mime_type: str,
        media_class: str,
        creator_name: str,
        acquisition_route: str,
        acquisition_source_revision_id: str,
        source_url: str,
        subject_clearance_status: str,
        discovery_source_revision_id: str | None = None,
        capture_at_utc: str | None = None,
        capture_location: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        if not asset_bytes:
            raise ValueError("asset bytes must be non-empty")
        if acquisition_route in FORBIDDEN_ACQUISITION_ROUTES or acquisition_route not in ALLOWED_ACQUISITION_ROUTES:
            raise ValueError("acquisition route is not authorized")
        if media_class not in {item.value for item in MediaClass}:
            raise ValueError("unsupported media class")
        if subject_clearance_status not in {item.value for item in SubjectClearanceStatus}:
            raise ValueError("unsupported subject clearance status")
        source = self.connection.execute(
            "SELECT * FROM image_source_revisions WHERE source_revision_id=?", (acquisition_source_revision_id,)
        ).fetchone()
        if source is None:
            raise ValueError("acquisition source revision does not exist")
        if source["status"] != "ACTIVE" or source["reuse_default"] not in {"OWNED", "LICENSE_REVIEWED", "PUBLIC_DOMAIN_REVIEWED", "SYNTHETIC_ONLY"}:
            raise ValueError("source revision is discovery-only or reuse-prohibited")
        if discovery_source_revision_id is not None:
            discovery = self.connection.execute(
                "SELECT 1 FROM image_source_revisions WHERE source_revision_id=?", (discovery_source_revision_id,)
            ).fetchone()
            if discovery is None:
                raise ValueError("discovery source revision does not exist")
        if capture_at_utc is not None:
            _parse_utc(capture_at_utc)
        original_sha256 = sha256(asset_bytes).hexdigest()
        metadata_json = _canonical_json(metadata or {})
        provenance_body = {
            "original_sha256": original_sha256,
            "mime_type": mime_type,
            "byte_size": len(asset_bytes),
            "media_class": media_class,
            "creator_name": creator_name,
            "acquisition_route": acquisition_route,
            "acquisition_source_revision_id": acquisition_source_revision_id,
            "discovery_source_revision_id": discovery_source_revision_id,
            "source_url": source_url,
            "capture_at_utc": capture_at_utc,
            "capture_location": capture_location,
            "subject_clearance_status": subject_clearance_status,
            "metadata_json": metadata_json,
        }
        provenance_hash = _hash(provenance_body)
        original_id = _hash({"original_sha256": original_sha256, "provenance_hash": provenance_hash})
        existing = self.connection.execute(
            "SELECT original_id, provenance_hash FROM image_originals WHERE original_sha256=?", (original_sha256,)
        ).fetchone()
        if existing:
            if existing["provenance_hash"] != provenance_hash:
                raise ValueError("same bytes already registered with different provenance")
            return str(existing["original_id"])
        self.connection.execute(
            """INSERT INTO image_originals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                original_id, original_sha256, mime_type, len(asset_bytes), media_class, creator_name,
                acquisition_route, acquisition_source_revision_id, discovery_source_revision_id,
                source_url, capture_at_utc, capture_location, subject_clearance_status,
                metadata_json, provenance_hash,
            ),
        )
        self.connection.commit()
        return original_id

    def register_rights_revision(
        self,
        original_id: str,
        *,
        rights_status: str,
        basis_type: str,
        rights_holder: str,
        permitted_platforms: Iterable[str],
        permitted_purposes: Iterable[str],
        territory: str,
        commercial_use_allowed: bool,
        modification_policy: str,
        attribution_required: bool,
        attribution_text: str,
        evidence: Iterable[EvidenceSnapshot],
        terms_hash: str,
        license_name: str | None = None,
        license_version: str | None = None,
        license_url: str | None = None,
        share_alike_required: bool = False,
        required_output_license: str | None = None,
        valid_from_utc: str | None = None,
        expires_at_utc: str | None = None,
        review_at_utc: str | None = None,
        revocable: bool = True,
        supersedes_rights_record_id: str | None = None,
    ) -> str:
        if self.connection.execute("SELECT 1 FROM image_originals WHERE original_id=?", (original_id,)).fetchone() is None:
            raise ValueError("original does not exist")
        if rights_status not in {item.value for item in RightsStatus}:
            raise ValueError("unsupported rights status")
        if modification_policy not in {item.value for item in ModificationPolicy}:
            raise ValueError("unsupported modification policy")
        platforms = tuple(sorted(set(permitted_platforms)))
        purposes = tuple(sorted(set(permitted_purposes)))
        unknown_platforms = set(platforms) - set(ACTIVE_NATIVE_PLATFORMS)
        if unknown_platforms:
            raise ValueError("rights grant contains platform outside active pre-pilot lanes")
        if rights_status in AUTO_ELIGIBLE_RIGHTS and (not platforms or not purposes):
            raise ValueError("eligible rights revision requires explicit platform and purpose scope")
        if attribution_required and not attribution_text.strip():
            raise ValueError("attribution text is required")
        if share_alike_required and not (required_output_license or "").strip():
            raise ValueError("ShareAlike requires output license")
        if valid_from_utc:
            _parse_utc(valid_from_utc)
        if expires_at_utc:
            _parse_utc(expires_at_utc)
        if review_at_utc:
            _parse_utc(review_at_utc)
        evidence_items = tuple(evidence)
        if rights_status in AUTO_ELIGIBLE_RIGHTS and not evidence_items:
            raise ValueError("eligible rights revision requires evidence snapshots")
        evidence_rows = []
        for item in evidence_items:
            _parse_utc(item.acquired_at_utc)
            snapshot_sha = sha256(item.snapshot_bytes).hexdigest()
            evidence_body = {
                "evidence_kind": item.evidence_kind,
                "snapshot_sha256": snapshot_sha,
                "snapshot_size": len(item.snapshot_bytes),
                "canonical_uri": item.canonical_uri,
                "acquired_at_utc": item.acquired_at_utc,
                "note": item.note,
            }
            evidence_hash = _hash(evidence_body)
            evidence_rows.append((item, snapshot_sha, evidence_hash))
        evidence_set_hash = _hash(tuple(sorted(row[2] for row in evidence_rows)))
        previous = self.connection.execute(
            "SELECT rights_record_id, revision FROM image_rights_records WHERE original_id=? ORDER BY revision DESC LIMIT 1",
            (original_id,),
        ).fetchone()
        revision = 1 if previous is None else int(previous["revision"]) + 1
        if previous is None:
            if supersedes_rights_record_id is not None:
                raise ValueError("first rights revision cannot supersede another record")
        elif previous["rights_record_id"] != supersedes_rights_record_id:
            raise ValueError("rights revision must supersede exact current record")
        body = {
            "original_id": original_id,
            "revision": revision,
            "rights_status": rights_status,
            "basis_type": basis_type,
            "rights_holder": rights_holder,
            "license_name": license_name,
            "license_version": license_version,
            "license_url": license_url,
            "permitted_platforms": platforms,
            "permitted_purposes": purposes,
            "territory": territory,
            "commercial_use_allowed": commercial_use_allowed,
            "modification_policy": modification_policy,
            "attribution_required": attribution_required,
            "attribution_text": attribution_text,
            "share_alike_required": share_alike_required,
            "required_output_license": required_output_license,
            "valid_from_utc": valid_from_utc,
            "expires_at_utc": expires_at_utc,
            "review_at_utc": review_at_utc,
            "revocable": revocable,
            "evidence_set_hash": evidence_set_hash,
            "terms_hash": terms_hash,
            "supersedes_rights_record_id": supersedes_rights_record_id,
        }
        record_hash = _hash(body)
        rights_record_id = _hash({"original_id": original_id, "revision": revision, "record_hash": record_hash})
        self.connection.execute("BEGIN")
        try:
            self.connection.execute(
                """INSERT INTO image_rights_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    rights_record_id, original_id, revision, rights_status, basis_type, rights_holder,
                    license_name, license_version, license_url, _canonical_json(platforms), _canonical_json(purposes),
                    territory, int(commercial_use_allowed), modification_policy, int(attribution_required),
                    attribution_text, int(share_alike_required), required_output_license, valid_from_utc,
                    expires_at_utc, review_at_utc, int(revocable), evidence_set_hash, terms_hash,
                    supersedes_rights_record_id, record_hash,
                ),
            )
            for item, snapshot_sha, evidence_hash in evidence_rows:
                evidence_id = _hash({"rights_record_id": rights_record_id, "evidence_hash": evidence_hash})
                self.connection.execute(
                    """INSERT INTO image_rights_evidence VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        evidence_id, rights_record_id, item.evidence_kind, snapshot_sha, len(item.snapshot_bytes),
                        item.canonical_uri, item.acquired_at_utc, item.note, evidence_hash,
                    ),
                )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return rights_record_id

    def register_derivative(
        self,
        derivative_bytes: bytes,
        *,
        parent_sha256: str,
        rights_record_id_at_creation: str,
        derivative_kind: str,
        transform: dict,
    ) -> str:
        if not derivative_bytes:
            raise ValueError("derivative bytes must be non-empty")
        root_original_id = self._root_original_id(parent_sha256)
        record = self.connection.execute(
            "SELECT original_id FROM image_rights_records WHERE rights_record_id=?", (rights_record_id_at_creation,)
        ).fetchone()
        if record is None or record["original_id"] != root_original_id:
            raise ValueError("derivative rights record does not belong to root original")
        derivative_sha = sha256(derivative_bytes).hexdigest()
        transform_json = _canonical_json(transform)
        transform_hash = _hash(transform)
        derivation_hash = _hash({
            "derivative_sha256": derivative_sha,
            "parent_sha256": parent_sha256,
            "root_original_id": root_original_id,
            "rights_record_id_at_creation": rights_record_id_at_creation,
            "derivative_kind": derivative_kind,
            "transform_hash": transform_hash,
        })
        derivative_id = _hash({"derivation_hash": derivation_hash, "stage": IMAGE_RIGHTS_MODEL_VERSION})
        existing = self.connection.execute(
            "SELECT derivative_id, derivation_hash FROM image_derivatives WHERE derivative_sha256=?", (derivative_sha,)
        ).fetchone()
        if existing:
            if existing["derivation_hash"] != derivation_hash:
                raise ValueError("same derivative bytes already registered with different lineage")
            return str(existing["derivative_id"])
        self.connection.execute(
            """INSERT INTO image_derivatives VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                derivative_id, derivative_sha, parent_sha256, root_original_id, rights_record_id_at_creation,
                derivative_kind, transform_json, transform_hash, derivation_hash,
            ),
        )
        self.connection.commit()
        return derivative_id

    def asset_sha256_for_original(self, original_id: str) -> str:
        row = self.connection.execute(
            "SELECT original_sha256 FROM image_originals WHERE original_id=?", (original_id,)
        ).fetchone()
        if row is None:
            raise ValueError("original does not exist")
        return str(row[0])

    def current_rights_record_id(self, original_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT rights_record_id FROM image_rights_records WHERE original_id=? ORDER BY revision DESC LIMIT 1",
            (original_id,),
        ).fetchone()
        return None if row is None else str(row[0])

    def _root_original_id(self, asset_sha256: str) -> str:
        original = self.connection.execute(
            "SELECT original_id FROM image_originals WHERE original_sha256=?", (asset_sha256,)
        ).fetchone()
        if original:
            return str(original[0])
        derivative = self.connection.execute(
            "SELECT root_original_id FROM image_derivatives WHERE derivative_sha256=?", (asset_sha256,)
        ).fetchone()
        if derivative:
            return str(derivative[0])
        raise ValueError("asset is not registered")

    def evaluate(self, asset_sha256: str, rights_record_id: str, request: UsageRequest) -> RightsEligibility:
        if request.platform not in ACTIVE_NATIVE_PLATFORMS:
            raise ValueError("usage request platform is not active")
        intended = _parse_utc(request.intended_at_utc)
        root_original_id = self._root_original_id(asset_sha256)
        original = self.connection.execute(
            "SELECT * FROM image_originals WHERE original_id=?", (root_original_id,)
        ).fetchone()
        record = self.connection.execute(
            "SELECT * FROM image_rights_records WHERE rights_record_id=?", (rights_record_id,)
        ).fetchone()
        if record is None or record["original_id"] != root_original_id:
            raise ValueError("rights record does not belong to asset root original")
        current_id = self.current_rights_record_id(root_original_id)
        reasons: list[str] = []
        status = EligibilityStatus.ELIGIBLE_RENDER_QA

        if current_id != rights_record_id:
            status = EligibilityStatus.HOLD_STALE_RIGHTS
            reasons.append("RIGHTS_RECORD_NOT_CURRENT")
        else:
            rights_status = str(record["rights_status"])
            if rights_status == RightsStatus.BLOCKED.value:
                status = EligibilityStatus.BLOCKED
                reasons.append("RIGHTS_BLOCKED")
            elif rights_status == RightsStatus.FAIR_USE_REVIEW.value:
                status = EligibilityStatus.HOLD_HUMAN_REVIEW
                reasons.append("FAIR_USE_REQUIRES_HUMAN_REVIEW")
            elif rights_status not in AUTO_ELIGIBLE_RIGHTS:
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("RIGHTS_STATUS_NOT_AUTO_ELIGIBLE")

        evidence_hashes = tuple(
            sorted(
                row[0]
                for row in self.connection.execute(
                    "SELECT evidence_hash FROM image_rights_evidence WHERE rights_record_id=?", (rights_record_id,)
                ).fetchall()
            )
        )
        if _hash(evidence_hashes) != record["evidence_set_hash"]:
            status = EligibilityStatus.BLOCKED
            reasons.append("EVIDENCE_SET_HASH_MISMATCH")

        if status == EligibilityStatus.ELIGIBLE_RENDER_QA:
            if record["valid_from_utc"] and intended < _parse_utc(str(record["valid_from_utc"])):
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("RIGHTS_NOT_YET_VALID")
            if record["expires_at_utc"] and intended > _parse_utc(str(record["expires_at_utc"])):
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("RIGHTS_EXPIRED")
            if record["review_at_utc"] and intended > _parse_utc(str(record["review_at_utc"])):
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("RIGHTS_REVIEW_OVERDUE")

        if status == EligibilityStatus.ELIGIBLE_RENDER_QA:
            platforms = _tuple_from_json(str(record["permitted_platforms_json"]))
            purposes = _tuple_from_json(str(record["permitted_purposes_json"]))
            if request.platform not in platforms:
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("PLATFORM_NOT_GRANTED")
            if request.purpose not in purposes:
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("PURPOSE_NOT_GRANTED")
            if str(record["territory"]) not in {"*", request.territory}:
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("TERRITORY_NOT_GRANTED")
            if request.commercial_context and not bool(record["commercial_use_allowed"]):
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("COMMERCIAL_USE_NOT_GRANTED")

        if status == EligibilityStatus.ELIGIBLE_RENDER_QA and request.modifications_required:
            policy = str(record["modification_policy"])
            requested = set(request.modifications_required)
            if policy == ModificationPolicy.NO_MODIFICATIONS.value:
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("MODIFICATIONS_NOT_GRANTED")
            elif policy == ModificationPolicy.CROP_RESIZE_ONLY.value and not requested.issubset({"CROP", "RESIZE"}):
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("MODIFICATION_OUTSIDE_GRANT")

        if status == EligibilityStatus.ELIGIBLE_RENDER_QA:
            if bool(record["attribution_required"]) and not str(record["attribution_text"]).strip():
                status = EligibilityStatus.HOLD_RIGHTS
                reasons.append("ATTRIBUTION_TEXT_MISSING")
            if bool(record["share_alike_required"]):
                required = str(record["required_output_license"] or "")
                if not request.output_license or request.output_license != required:
                    status = EligibilityStatus.HOLD_RIGHTS
                    reasons.append("SHAREALIKE_OUTPUT_LICENSE_MISMATCH")

        subject = str(original["subject_clearance_status"])
        if subject == SubjectClearanceStatus.BLOCKED.value:
            status = EligibilityStatus.BLOCKED
            reasons.append("SUBJECT_CLEARANCE_BLOCKED")
        elif subject in {SubjectClearanceStatus.PENDING.value, SubjectClearanceStatus.REQUIRED.value} and status != EligibilityStatus.BLOCKED:
            status = EligibilityStatus.HOLD_RIGHTS
            reasons.append("SUBJECT_CLEARANCE_NOT_COMPLETE")

        if original["media_class"] == MediaClass.PROFILE_PHOTO.value and request.purpose == SOCIAL_EDITORIAL_PURPOSE:
            status = EligibilityStatus.BLOCKED
            reasons.append("PROFILE_PHOTO_NOT_SOCIAL_EDITORIAL_MEDIA")

        if not reasons and status == EligibilityStatus.ELIGIBLE_RENDER_QA:
            reasons.append("RIGHTS_SCOPE_EVIDENCE_AND_CLEARANCE_PASS")

        body = {
            "schema_version": IMAGE_RIGHTS_MODEL_VERSION,
            "asset_sha256": asset_sha256,
            "root_original_id": root_original_id,
            "rights_record_id": rights_record_id,
            "rights_record_hash": record["record_hash"],
            "request": asdict(request),
            "status": status.value,
            "reason_codes": tuple(reasons),
            "attribution_text": str(record["attribution_text"]),
            "eligible": status == EligibilityStatus.ELIGIBLE_RENDER_QA,
            "publish_eligible": False,
        }
        return RightsEligibility(
            eligibility_hash=_hash(body),
            asset_sha256=asset_sha256,
            root_original_id=root_original_id,
            rights_record_id=rights_record_id,
            rights_record_hash=str(record["record_hash"]),
            platform=request.platform,
            purpose=request.purpose,
            status=status.value,
            reason_codes=tuple(reasons),
            attribution_text=str(record["attribution_text"]),
            eligible=status == EligibilityStatus.ELIGIBLE_RENDER_QA,
        )


def bind_rights_bound_visual_input(
    bundle: NativeAdaptationBundle,
    registry: RightsRegistry,
    *,
    asset_sha256: str,
    rights_record_id: str,
    intended_at_utc: str,
    territory: str,
    modifications_required: tuple[str, ...] = ("CROP", "RESIZE"),
    commercial_context: bool = True,
    purpose: str = SOCIAL_EDITORIAL_PURPOSE,
    output_license: str | None = None,
) -> RightsBoundVisualInput:
    _validate_native_bundle(bundle)
    root_original_id = registry._root_original_id(asset_sha256)
    record = registry.connection.execute(
        "SELECT record_hash FROM image_rights_records WHERE rights_record_id=?", (rights_record_id,)
    ).fetchone()
    if record is None:
        raise ValueError("rights record does not exist")

    if not bundle.rights_input_ready or bundle.status != NativeBundleStatus.READY_ALL_ACTIVE_LANES.value:
        eligibility: tuple[RightsEligibility, ...] = ()
        status = VisualBindingStatus.HOLD_INPUT_NOT_READY
    else:
        eligibility = tuple(
            registry.evaluate(
                asset_sha256,
                rights_record_id,
                UsageRequest(
                    platform=platform,
                    purpose=purpose,
                    intended_at_utc=intended_at_utc,
                    modifications_required=modifications_required,
                    commercial_context=commercial_context,
                    territory=territory,
                    output_license=output_license,
                ),
            )
            for platform in bundle.active_platforms
        )
        if all(item.eligible for item in eligibility):
            status = VisualBindingStatus.READY_RIGHTS_BOUND_VISUAL_INPUT
        elif any(item.status == EligibilityStatus.BLOCKED.value for item in eligibility):
            status = VisualBindingStatus.BLOCKED
        else:
            status = VisualBindingStatus.HOLD_RIGHTS

    eligible_platforms = tuple(item.platform for item in eligibility if item.eligible)
    blocked_platforms = tuple(item.platform for item in eligibility if not item.eligible)
    visual_input_ready = status == VisualBindingStatus.READY_RIGHTS_BOUND_VISUAL_INPUT
    body = {
        "schema_version": IMAGE_RIGHTS_MODEL_VERSION,
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "asset_sha256": asset_sha256,
        "root_original_id": root_original_id,
        "rights_record_id": rights_record_id,
        "rights_record_hash": str(record["record_hash"]),
        "eligibility": [item.to_dict() for item in eligibility],
        "eligible_platforms": eligible_platforms,
        "blocked_platforms": blocked_platforms,
        "status": status.value,
        "visual_input_ready": visual_input_ready,
        "state": "RIGHTS_BOUND_VISUAL_INPUT_ONLY",
        "rights_authority": True,
        "fact_authority": False,
        "visual_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    binding_id = _hash({
        "bundle_id": bundle.bundle_id,
        "bundle_hash": bundle.bundle_hash,
        "asset_sha256": asset_sha256,
        "rights_record_id": rights_record_id,
        "stage": IMAGE_RIGHTS_MODEL_VERSION,
    })
    return RightsBoundVisualInput(
        binding_id=binding_id,
        binding_hash=_hash(body),
        model_version=IMAGE_RIGHTS_MODEL_VERSION,
        bundle_id=bundle.bundle_id,
        bundle_hash=bundle.bundle_hash,
        asset_sha256=asset_sha256,
        root_original_id=root_original_id,
        rights_record_id=rights_record_id,
        rights_record_hash=str(record["record_hash"]),
        eligibility=eligibility,
        eligible_platforms=eligible_platforms,
        blocked_platforms=blocked_platforms,
        status=status.value,
        visual_input_ready=visual_input_ready,
    )
