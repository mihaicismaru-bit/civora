from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import re
import sqlite3
from pathlib import Path
from typing import Iterable

from .control import EXPECTED_ACTIVE, canonical_json

RIGHTS_MODEL_VERSION = "PPOS_IMAGE_RIGHTS_REGISTRY_V1"
RIGHTS_BOUND_VISUAL_INPUT_VERSION = "PPOS_RIGHTS_BOUND_VISUAL_INPUT_V1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

AUTO_ELIGIBLE_RIGHTS = {"OWNED", "LICENSED", "PUBLIC_DOMAIN"}
RIGHTS_STATUSES = AUTO_ELIGIBLE_RIGHTS | {"FAIR_USE_REVIEW", "UNKNOWN", "BLOCKED"}
SUBJECT_CLEARANCE = {"NOT_REQUIRED", "CLEARED", "PENDING", "REQUIRED", "BLOCKED"}
MEDIA_CLASSES = {"CONTEXTUAL_PHOTO", "EVENT_PHOTO", "DOCUMENT_IMAGE", "PROFILE_PHOTO", "ILLUSTRATION"}
SAFE_ACQUISITION_ROUTES = {"FIRST_PARTY_UPLOAD", "DIRECT_LICENSE", "PUBLIC_DOMAIN_SOURCE", "WIKIMEDIA_REVIEWED"}
PROHIBITED_ACQUISITION_ROUTES = {
    "SOCIAL_DOWNLOAD_UNCLEARED", "SEARCH_ENGINE_DOWNLOAD", "PRESS_COPY_UNCLEARED", "MAP_SCREENSHOT_AS_PHOTO"
}
MODIFICATION_POLICIES = {"ALLOWED", "NO_DERIVATIVES", "UNKNOWN"}
PUBLIC_DOMAIN_BASES = {"PUBLIC_DOMAIN_DETERMINATION", "CC0_DEDICATION"}


class RightsError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceSnapshot:
    evidence_kind: str
    snapshot_sha256: str
    snapshot_size: int
    canonical_uri: str
    acquired_at: str
    note: str = ""

    @property
    def evidence_hash(self) -> str:
        return _hash({
            "evidence_kind": self.evidence_kind,
            "snapshot_sha256": self.snapshot_sha256,
            "snapshot_size": self.snapshot_size,
            "canonical_uri": self.canonical_uri,
            "acquired_at": _iso(self.acquired_at),
            "note": self.note,
        })


@dataclass(frozen=True)
class UsageRequest:
    platform: str
    purpose: str
    intended_at: str
    modifications_required: bool
    commercial_context: bool
    territory: str
    output_license: str | None = None

    def canonical(self) -> dict:
        return {
            "platform": self.platform,
            "purpose": self.purpose,
            "intended_at": _iso(self.intended_at),
            "modifications_required": bool(self.modifications_required),
            "commercial_context": bool(self.commercial_context),
            "territory": self.territory,
            "output_license": self.output_license,
        }


@dataclass(frozen=True)
class RightsEligibility:
    status: str
    reasons: tuple[str, ...]
    asset_sha256: str
    root_original_id: str | None
    rights_record_id: str
    eligibility_hash: str
    render_qa_eligible: bool
    publish_eligible: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False


@dataclass(frozen=True)
class RightsBoundVisualInput:
    binding_id: str
    binding_hash: str
    model_version: str
    asset_sha256: str
    root_original_id: str
    original_sha256: str
    provenance_hash: str
    source_revision_id: str
    source_hash: str
    source_url: str
    creator_name: str
    media_class: str
    rights_record_id: str
    rights_record_hash: str
    rights_status: str
    evidence_set_hash: str
    eligibility_hash: str
    platform: str
    purpose: str
    territory: str
    attribution_required: bool
    attribution_text: str | None
    license_name: str | None
    license_version: str | None
    license_url: str | None
    state: str = "RIGHTS_BOUND_VISUAL_INPUT_ONLY"
    visual_render_input_authority: bool = True
    story_fit_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    publish_eligible: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _validate_sha(value: str, name: str) -> None:
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise RightsError(f"{name} must be lowercase sha256")


def _parse_dt(value: str | None) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RightsError(f"invalid timestamp: {value}") from exc
    if dt.tzinfo is None:
        raise RightsError("timestamps must include timezone")
    return dt.astimezone(timezone.utc)


def _iso(value: str | None) -> str | None:
    dt = _parse_dt(value)
    return dt.isoformat().replace("+00:00", "Z") if dt is not None else None


def evidence_set_hash(snapshots: Iterable[EvidenceSnapshot]) -> str:
    hashes = sorted(snapshot.evidence_hash for snapshot in tuple(snapshots))
    if not hashes:
        raise RightsError("rights evidence set cannot be empty")
    return _hash({"evidence_hashes": hashes, "schema_version": RIGHTS_MODEL_VERSION})


def terms_hash(value: dict) -> str:
    return _hash({"terms": value, "schema_version": RIGHTS_MODEL_VERSION})


class RightsRegistry:
    def __init__(self, connection: sqlite3.Connection):
        self.db = connection
        self.db.row_factory = sqlite3.Row
        self.migrate()

    @classmethod
    def memory(cls) -> "RightsRegistry":
        return cls(sqlite3.connect(":memory:"))

    @classmethod
    def open(cls, path: str | Path) -> "RightsRegistry":
        return cls(sqlite3.connect(str(path)))

    def close(self) -> None:
        self.db.close()

    def migrate(self) -> None:
        self.db.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS image_source_revisions (
              source_revision_id TEXT PRIMARY KEY,
              source_id TEXT NOT NULL,
              revision INTEGER NOT NULL CHECK(revision >= 1),
              source_class TEXT NOT NULL,
              display_name TEXT NOT NULL,
              source_url TEXT NOT NULL,
              discovery_role TEXT NOT NULL,
              reuse_default TEXT NOT NULL,
              license_or_basis TEXT,
              restrictions_json TEXT NOT NULL,
              status TEXT NOT NULL,
              verified_at TEXT NOT NULL,
              source_hash TEXT NOT NULL UNIQUE,
              supersedes_source_revision_id TEXT REFERENCES image_source_revisions(source_revision_id),
              UNIQUE(source_id, revision)
            );
            CREATE TABLE IF NOT EXISTS image_originals (
              original_id TEXT PRIMARY KEY,
              original_sha256 TEXT NOT NULL UNIQUE,
              mime_type TEXT NOT NULL,
              byte_size INTEGER NOT NULL CHECK(byte_size > 0),
              media_class TEXT NOT NULL,
              creator_name TEXT NOT NULL,
              creator_identity_status TEXT NOT NULL,
              acquisition_route TEXT NOT NULL,
              acquisition_source_revision_id TEXT NOT NULL REFERENCES image_source_revisions(source_revision_id),
              discovery_source_revision_id TEXT REFERENCES image_source_revisions(source_revision_id),
              source_url TEXT NOT NULL,
              capture_at TEXT,
              capture_location TEXT,
              subject_clearance_status TEXT NOT NULL,
              metadata_json TEXT NOT NULL,
              provenance_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS image_rights_records (
              rights_record_id TEXT PRIMARY KEY,
              original_id TEXT NOT NULL REFERENCES image_originals(original_id),
              revision INTEGER NOT NULL CHECK(revision >= 1),
              rights_status TEXT NOT NULL,
              basis_type TEXT NOT NULL,
              rights_holder TEXT NOT NULL,
              license_name TEXT,
              license_version TEXT,
              license_url TEXT,
              permitted_platforms_json TEXT NOT NULL,
              permitted_purposes_json TEXT NOT NULL,
              territory TEXT NOT NULL,
              commercial_use_allowed INTEGER NOT NULL CHECK(commercial_use_allowed IN (0,1)),
              modification_policy TEXT NOT NULL,
              attribution_required INTEGER NOT NULL CHECK(attribution_required IN (0,1)),
              attribution_text TEXT,
              share_alike_required INTEGER NOT NULL CHECK(share_alike_required IN (0,1)),
              required_output_license TEXT,
              valid_from TEXT NOT NULL,
              expires_at TEXT,
              review_at TEXT,
              revocable INTEGER NOT NULL CHECK(revocable IN (0,1)),
              evidence_set_hash TEXT NOT NULL,
              terms_hash TEXT NOT NULL,
              supersedes_rights_record_id TEXT REFERENCES image_rights_records(rights_record_id),
              record_hash TEXT NOT NULL UNIQUE,
              UNIQUE(original_id, revision)
            );
            CREATE TABLE IF NOT EXISTS image_rights_evidence (
              evidence_id TEXT PRIMARY KEY,
              rights_record_id TEXT NOT NULL REFERENCES image_rights_records(rights_record_id),
              evidence_kind TEXT NOT NULL,
              snapshot_sha256 TEXT NOT NULL,
              snapshot_size INTEGER NOT NULL CHECK(snapshot_size > 0),
              canonical_uri TEXT NOT NULL,
              acquired_at TEXT NOT NULL,
              note TEXT NOT NULL,
              evidence_hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS image_derivatives (
              derivative_id TEXT PRIMARY KEY,
              derivative_sha256 TEXT NOT NULL UNIQUE,
              parent_sha256 TEXT NOT NULL,
              root_original_id TEXT NOT NULL REFERENCES image_originals(original_id),
              rights_record_id_at_creation TEXT NOT NULL REFERENCES image_rights_records(rights_record_id),
              derivative_kind TEXT NOT NULL,
              transform_json TEXT NOT NULL,
              transform_hash TEXT NOT NULL,
              derivation_hash TEXT NOT NULL UNIQUE
            );
            """
        )
        for table in (
            "image_source_revisions", "image_originals", "image_rights_records",
            "image_rights_evidence", "image_derivatives"
        ):
            self.db.executescript(
                f"""
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_update
                BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
                CREATE TRIGGER IF NOT EXISTS {table}_append_only_delete
                BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT, 'append-only table'); END;
                """
            )
        self.db.commit()

    def register_source_revision(
        self, *, source_id: str, revision: int, source_class: str, display_name: str,
        source_url: str, discovery_role: str, reuse_default: str, license_or_basis: str | None,
        restrictions: dict, status: str, verified_at: str, supersedes_source_revision_id: str | None = None,
    ) -> dict:
        if not source_id or revision < 1 or not source_url:
            raise RightsError("source identity, revision and url are required")
        body = {
            "schema_version": RIGHTS_MODEL_VERSION,
            "source_id": source_id,
            "revision": revision,
            "source_class": source_class,
            "display_name": display_name,
            "source_url": source_url,
            "discovery_role": discovery_role,
            "reuse_default": reuse_default,
            "license_or_basis": license_or_basis,
            "restrictions": restrictions,
            "status": status,
            "verified_at": _iso(verified_at),
            "supersedes_source_revision_id": supersedes_source_revision_id,
        }
        source_hash = _hash(body)
        source_revision_id = _hash({"source_id": source_id, "revision": revision, "source_hash": source_hash})
        self.db.execute(
            "INSERT INTO image_source_revisions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (source_revision_id, source_id, revision, source_class, display_name, source_url,
             discovery_role, reuse_default, license_or_basis, canonical_json(restrictions), status,
             body["verified_at"], source_hash, supersedes_source_revision_id)
        )
        self.db.commit()
        return {"source_revision_id": source_revision_id, "source_hash": source_hash}

    def register_original(
        self, *, original_sha256: str, mime_type: str, byte_size: int, media_class: str,
        creator_name: str, creator_identity_status: str, acquisition_route: str,
        acquisition_source_revision_id: str, source_url: str,
        discovery_source_revision_id: str | None = None, capture_at: str | None = None,
        capture_location: str | None = None, subject_clearance_status: str = "NOT_REQUIRED",
        metadata: dict | None = None,
    ) -> dict:
        _validate_sha(original_sha256, "original_sha256")
        if acquisition_route in PROHIBITED_ACQUISITION_ROUTES or acquisition_route not in SAFE_ACQUISITION_ROUTES:
            raise RightsError("acquisition route is not authorized")
        if media_class not in MEDIA_CLASSES:
            raise RightsError("unsupported media class")
        if subject_clearance_status not in SUBJECT_CLEARANCE:
            raise RightsError("unsupported subject clearance state")
        if not mime_type.startswith("image/") or byte_size <= 0:
            raise RightsError("original must be a non-empty image")
        source = self.db.execute(
            "SELECT * FROM image_source_revisions WHERE source_revision_id=?", (acquisition_source_revision_id,)
        ).fetchone()
        if source is None or source["status"] != "ACTIVE" or source["discovery_role"] == "DISCOVERY_ONLY":
            raise RightsError("acquisition source is not authorized for reuse evidence")
        if discovery_source_revision_id is not None:
            discovery = self.db.execute(
                "SELECT 1 FROM image_source_revisions WHERE source_revision_id=?", (discovery_source_revision_id,)
            ).fetchone()
            if discovery is None:
                raise RightsError("discovery source is unknown")
        body = {
            "schema_version": RIGHTS_MODEL_VERSION,
            "original_sha256": original_sha256,
            "mime_type": mime_type,
            "byte_size": byte_size,
            "media_class": media_class,
            "creator_name": creator_name,
            "creator_identity_status": creator_identity_status,
            "acquisition_route": acquisition_route,
            "acquisition_source_revision_id": acquisition_source_revision_id,
            "discovery_source_revision_id": discovery_source_revision_id,
            "source_url": source_url,
            "capture_at": _iso(capture_at),
            "capture_location": capture_location,
            "subject_clearance_status": subject_clearance_status,
            "metadata": metadata or {},
        }
        provenance_hash = _hash(body)
        original_id = _hash({"original_sha256": original_sha256, "provenance_hash": provenance_hash})
        self.db.execute(
            "INSERT INTO image_originals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (original_id, original_sha256, mime_type, byte_size, media_class, creator_name,
             creator_identity_status, acquisition_route, acquisition_source_revision_id,
             discovery_source_revision_id, source_url, body["capture_at"], capture_location,
             subject_clearance_status, canonical_json(metadata or {}), provenance_hash)
        )
        self.db.commit()
        return {"original_id": original_id, "provenance_hash": provenance_hash}

    def register_rights_record(
        self, *, original_id: str, revision: int, rights_status: str, basis_type: str,
        rights_holder: str, permitted_platforms: Iterable[str], permitted_purposes: Iterable[str],
        territory: str, commercial_use_allowed: bool, modification_policy: str,
        attribution_required: bool, attribution_text: str | None, share_alike_required: bool,
        required_output_license: str | None, valid_from: str, evidence_set_hash_value: str,
        terms_hash_value: str, license_name: str | None = None, license_version: str | None = None,
        license_url: str | None = None, expires_at: str | None = None, review_at: str | None = None,
        revocable: bool = True, supersedes_rights_record_id: str | None = None,
    ) -> dict:
        if rights_status not in RIGHTS_STATUSES:
            raise RightsError("unsupported rights status")
        if modification_policy not in MODIFICATION_POLICIES:
            raise RightsError("unsupported modification policy")
        _validate_sha(evidence_set_hash_value, "evidence_set_hash")
        _validate_sha(terms_hash_value, "terms_hash")
        if self.db.execute("SELECT 1 FROM image_originals WHERE original_id=?", (original_id,)).fetchone() is None:
            raise RightsError("unknown original")
        platforms = tuple(sorted(set(permitted_platforms)))
        purposes = tuple(sorted(set(permitted_purposes)))
        if rights_status in AUTO_ELIGIBLE_RIGHTS and (not platforms or not purposes or not territory):
            raise RightsError("automatic rights require explicit platform, purpose and territory grants")
        if rights_status == "LICENSED":
            if not license_name or not license_url:
                raise RightsError("licensed rights require license identity and url")
        if rights_status == "PUBLIC_DOMAIN" and basis_type not in PUBLIC_DOMAIN_BASES:
            raise RightsError("public domain requires an explicit determination or CC0 dedication")
        if attribution_required and not (attribution_text or "").strip():
            raise RightsError("attribution text required")
        if share_alike_required and not (required_output_license or "").strip():
            raise RightsError("share-alike requires output license")
        _parse_dt(valid_from); _parse_dt(expires_at); _parse_dt(review_at)
        current = self._current_rights(original_id)
        if revision == 1:
            if current is not None or supersedes_rights_record_id is not None:
                raise RightsError("revision 1 cannot supersede an existing record")
        else:
            if current is None or supersedes_rights_record_id != current["rights_record_id"] or revision != current["revision"] + 1:
                raise RightsError("rights revisions must supersede the current record sequentially")
        body = {
            "schema_version": RIGHTS_MODEL_VERSION,
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
            "commercial_use_allowed": bool(commercial_use_allowed),
            "modification_policy": modification_policy,
            "attribution_required": bool(attribution_required),
            "attribution_text": attribution_text,
            "share_alike_required": bool(share_alike_required),
            "required_output_license": required_output_license,
            "valid_from": _iso(valid_from),
            "expires_at": _iso(expires_at),
            "review_at": _iso(review_at),
            "revocable": bool(revocable),
            "evidence_set_hash": evidence_set_hash_value,
            "terms_hash": terms_hash_value,
            "supersedes_rights_record_id": supersedes_rights_record_id,
        }
        record_hash = _hash(body)
        rights_record_id = _hash({"original_id": original_id, "revision": revision, "record_hash": record_hash})
        self.db.execute(
            "INSERT INTO image_rights_records VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (rights_record_id, original_id, revision, rights_status, basis_type, rights_holder,
             license_name, license_version, license_url, canonical_json(platforms), canonical_json(purposes),
             territory, int(bool(commercial_use_allowed)), modification_policy, int(bool(attribution_required)),
             attribution_text, int(bool(share_alike_required)), required_output_license, body["valid_from"],
             body["expires_at"], body["review_at"], int(bool(revocable)), evidence_set_hash_value,
             terms_hash_value, supersedes_rights_record_id, record_hash)
        )
        self.db.commit()
        return {"rights_record_id": rights_record_id, "record_hash": record_hash}

    def register_evidence(self, rights_record_id: str, snapshot: EvidenceSnapshot) -> dict:
        if self.db.execute("SELECT 1 FROM image_rights_records WHERE rights_record_id=?", (rights_record_id,)).fetchone() is None:
            raise RightsError("unknown rights record")
        _validate_sha(snapshot.snapshot_sha256, "snapshot_sha256")
        if snapshot.snapshot_size <= 0 or not snapshot.canonical_uri:
            raise RightsError("evidence must be a non-empty snapshot with canonical uri")
        acquired = _iso(snapshot.acquired_at)
        evidence_hash_value = snapshot.evidence_hash
        evidence_id = _hash({"rights_record_id": rights_record_id, "evidence_hash": evidence_hash_value})
        self.db.execute(
            "INSERT INTO image_rights_evidence VALUES (?,?,?,?,?,?,?,?,?)",
            (evidence_id, rights_record_id, snapshot.evidence_kind, snapshot.snapshot_sha256,
             snapshot.snapshot_size, snapshot.canonical_uri, acquired, snapshot.note, evidence_hash_value)
        )
        self.db.commit()
        return {"evidence_id": evidence_id, "evidence_hash": evidence_hash_value}

    def register_derivative(
        self, *, derivative_sha256: str, parent_sha256: str, rights_record_id_at_creation: str,
        derivative_kind: str, transform: dict,
    ) -> dict:
        _validate_sha(derivative_sha256, "derivative_sha256")
        _validate_sha(parent_sha256, "parent_sha256")
        root = self._root_for_asset(parent_sha256)
        if root is None:
            raise RightsError("parent asset not found")
        current = self._current_rights(root["original_id"])
        if current is None or current["rights_record_id"] != rights_record_id_at_creation:
            raise RightsError("derivative must bind the current root rights record")
        transform_json = canonical_json(transform)
        transform_hash = _hash({"transform": transform, "schema_version": RIGHTS_MODEL_VERSION})
        body = {
            "schema_version": RIGHTS_MODEL_VERSION,
            "derivative_sha256": derivative_sha256,
            "parent_sha256": parent_sha256,
            "root_original_id": root["original_id"],
            "rights_record_id_at_creation": rights_record_id_at_creation,
            "derivative_kind": derivative_kind,
            "transform_hash": transform_hash,
        }
        derivation_hash = _hash(body)
        derivative_id = _hash({"derivative_sha256": derivative_sha256, "derivation_hash": derivation_hash})
        self.db.execute(
            "INSERT INTO image_derivatives VALUES (?,?,?,?,?,?,?,?,?)",
            (derivative_id, derivative_sha256, parent_sha256, root["original_id"],
             rights_record_id_at_creation, derivative_kind, transform_json, transform_hash, derivation_hash)
        )
        self.db.commit()
        return {"derivative_id": derivative_id, "derivation_hash": derivation_hash}

    def _current_rights(self, original_id: str):
        return self.db.execute(
            "SELECT * FROM image_rights_records WHERE original_id=? ORDER BY revision DESC LIMIT 1", (original_id,)
        ).fetchone()

    def _root_for_asset(self, asset_sha256: str):
        original = self.db.execute(
            "SELECT original_id, original_sha256 FROM image_originals WHERE original_sha256=?", (asset_sha256,)
        ).fetchone()
        if original is not None:
            return original
        return self.db.execute(
            "SELECT d.root_original_id AS original_id, o.original_sha256 AS original_sha256 "
            "FROM image_derivatives d JOIN image_originals o ON o.original_id=d.root_original_id "
            "WHERE d.derivative_sha256=?", (asset_sha256,)
        ).fetchone()

    def _evidence_set_for_record(self, rights_record_id: str) -> str | None:
        rows = self.db.execute(
            "SELECT evidence_hash FROM image_rights_evidence WHERE rights_record_id=? ORDER BY evidence_hash", (rights_record_id,)
        ).fetchall()
        if not rows:
            return None
        return _hash({"evidence_hashes": [r["evidence_hash"] for r in rows], "schema_version": RIGHTS_MODEL_VERSION})

    def evaluate(self, asset_sha256: str, rights_record_id: str, usage: UsageRequest) -> RightsEligibility:
        _validate_sha(asset_sha256, "asset_sha256")
        usage_body = usage.canonical()
        reasons: list[str] = []
        root = self._root_for_asset(asset_sha256)
        record = self.db.execute(
            "SELECT * FROM image_rights_records WHERE rights_record_id=?", (rights_record_id,)
        ).fetchone()
        status = "ELIGIBLE_RENDER_QA"
        if root is None:
            status = "BLOCKED"; reasons.append("ASSET_NOT_REGISTERED")
        if record is None:
            status = "BLOCKED"; reasons.append("RIGHTS_RECORD_NOT_REGISTERED")
        if root is not None and record is not None and record["original_id"] != root["original_id"]:
            status = "BLOCKED"; reasons.append("RIGHTS_RECORD_ROOT_MISMATCH")
        if root is not None and record is not None:
            current = self._current_rights(root["original_id"])
            if current is None:
                status = "HOLD_RIGHTS"; reasons.append("NO_CURRENT_RIGHTS")
            elif current["rights_status"] == "BLOCKED":
                status = "BLOCKED"; reasons.append("CURRENT_RIGHTS_BLOCKED")
            elif current["rights_record_id"] != rights_record_id:
                status = "HOLD_STALE_RIGHTS"; reasons.append("RIGHTS_RECORD_SUPERSEDED")
        if record is not None and status not in {"BLOCKED", "HOLD_STALE_RIGHTS"}:
            actual_evidence = self._evidence_set_for_record(rights_record_id)
            if actual_evidence != record["evidence_set_hash"]:
                status = "HOLD_RIGHTS"; reasons.append("EVIDENCE_SET_HASH_MISMATCH")
            rs = record["rights_status"]
            if rs == "FAIR_USE_REVIEW":
                status = "HOLD_HUMAN_REVIEW"; reasons.append("FAIR_USE_REQUIRES_HUMAN_REVIEW")
            elif rs == "UNKNOWN":
                status = "HOLD_RIGHTS"; reasons.append("RIGHTS_UNKNOWN")
            elif rs == "BLOCKED":
                status = "BLOCKED"; reasons.append("RIGHTS_BLOCKED")
            elif rs not in AUTO_ELIGIBLE_RIGHTS:
                status = "HOLD_RIGHTS"; reasons.append("RIGHTS_NOT_AUTO_ELIGIBLE")
        if record is not None and status == "ELIGIBLE_RENDER_QA":
            intended = _parse_dt(usage.intended_at)
            valid_from = _parse_dt(record["valid_from"])
            expires_at = _parse_dt(record["expires_at"])
            review_at = _parse_dt(record["review_at"])
            if intended is None:
                status = "HOLD_RIGHTS"; reasons.append("INTENDED_AT_REQUIRED")
            elif valid_from and intended < valid_from:
                status = "HOLD_RIGHTS"; reasons.append("RIGHTS_NOT_YET_VALID")
            elif expires_at and intended > expires_at:
                status = "HOLD_RIGHTS"; reasons.append("RIGHTS_EXPIRED")
            elif review_at and intended > review_at:
                status = "HOLD_STALE_RIGHTS"; reasons.append("RIGHTS_REVIEW_OVERDUE")
        if record is not None and status == "ELIGIBLE_RENDER_QA":
            platforms = set(json.loads(record["permitted_platforms_json"]))
            purposes = set(json.loads(record["permitted_purposes_json"]))
            if usage.platform not in EXPECTED_ACTIVE:
                status = "HOLD_RIGHTS"; reasons.append("PLATFORM_NOT_ACTIVE")
            elif usage.platform not in platforms:
                status = "HOLD_RIGHTS"; reasons.append("PLATFORM_NOT_GRANTED")
            if usage.purpose not in purposes:
                status = "HOLD_RIGHTS"; reasons.append("PURPOSE_NOT_GRANTED")
            if record["territory"] not in {"WORLDWIDE", usage.territory}:
                status = "HOLD_RIGHTS"; reasons.append("TERRITORY_NOT_GRANTED")
            if usage.commercial_context and not bool(record["commercial_use_allowed"]):
                status = "HOLD_RIGHTS"; reasons.append("COMMERCIAL_USE_NOT_GRANTED")
            if usage.modifications_required and record["modification_policy"] != "ALLOWED":
                status = "HOLD_RIGHTS"; reasons.append("MODIFICATION_NOT_GRANTED")
            if bool(record["attribution_required"]) and not (record["attribution_text"] or "").strip():
                status = "HOLD_RIGHTS"; reasons.append("ATTRIBUTION_TEXT_MISSING")
            if bool(record["share_alike_required"]) and usage.output_license != record["required_output_license"]:
                status = "HOLD_RIGHTS"; reasons.append("SHARE_ALIKE_OUTPUT_LICENSE_MISMATCH")
        if root is not None and status == "ELIGIBLE_RENDER_QA":
            original = self.db.execute("SELECT * FROM image_originals WHERE original_id=?", (root["original_id"],)).fetchone()
            clearance = original["subject_clearance_status"]
            if clearance == "BLOCKED":
                status = "BLOCKED"; reasons.append("SUBJECT_CLEARANCE_BLOCKED")
            elif clearance in {"PENDING", "REQUIRED"}:
                status = "HOLD_HUMAN_REVIEW"; reasons.append("SUBJECT_CLEARANCE_REQUIRES_REVIEW")
            if original["media_class"] == "PROFILE_PHOTO" and usage.purpose == "SOCIAL_EDITORIAL":
                status = "BLOCKED"; reasons.append("PROFILE_PHOTO_NOT_EDITORIAL_MEDIA")
        payload = {
            "schema_version": RIGHTS_MODEL_VERSION,
            "asset_sha256": asset_sha256,
            "root_original_id": root["original_id"] if root is not None else None,
            "rights_record_id": rights_record_id,
            "usage": usage_body,
            "status": status,
            "reasons": tuple(reasons),
        }
        return RightsEligibility(
            status=status,
            reasons=tuple(reasons),
            asset_sha256=asset_sha256,
            root_original_id=root["original_id"] if root is not None else None,
            rights_record_id=rights_record_id,
            eligibility_hash=_hash(payload),
            render_qa_eligible=status == "ELIGIBLE_RENDER_QA",
        )

    def bind_visual_input(self, asset_sha256: str, rights_record_id: str, usage: UsageRequest) -> RightsBoundVisualInput:
        eligibility = self.evaluate(asset_sha256, rights_record_id, usage)
        if not eligibility.render_qa_eligible or eligibility.root_original_id is None:
            raise RightsError(f"asset is not render-QA eligible: {eligibility.status}")
        original = self.db.execute(
            "SELECT * FROM image_originals WHERE original_id=?", (eligibility.root_original_id,)
        ).fetchone()
        source = self.db.execute(
            "SELECT * FROM image_source_revisions WHERE source_revision_id=?", (original["acquisition_source_revision_id"],)
        ).fetchone()
        record = self.db.execute(
            "SELECT * FROM image_rights_records WHERE rights_record_id=?", (rights_record_id,)
        ).fetchone()
        body = {
            "schema_version": RIGHTS_BOUND_VISUAL_INPUT_VERSION,
            "asset_sha256": asset_sha256,
            "root_original_id": eligibility.root_original_id,
            "original_sha256": original["original_sha256"],
            "provenance_hash": original["provenance_hash"],
            "source_revision_id": source["source_revision_id"],
            "source_hash": source["source_hash"],
            "source_url": original["source_url"],
            "creator_name": original["creator_name"],
            "media_class": original["media_class"],
            "rights_record_id": rights_record_id,
            "rights_record_hash": record["record_hash"],
            "rights_status": record["rights_status"],
            "evidence_set_hash": record["evidence_set_hash"],
            "eligibility_hash": eligibility.eligibility_hash,
            "platform": usage.platform,
            "purpose": usage.purpose,
            "territory": usage.territory,
            "attribution_required": bool(record["attribution_required"]),
            "attribution_text": record["attribution_text"],
            "license_name": record["license_name"],
            "license_version": record["license_version"],
            "license_url": record["license_url"],
            "state": "RIGHTS_BOUND_VISUAL_INPUT_ONLY",
            "visual_render_input_authority": True,
            "story_fit_authority": False,
            "queue_authority": False,
            "publish_authority": False,
            "publish_eligible": False,
            "network_fetch_performed": False,
            "real_account_connection_performed": False,
        }
        binding_hash = _hash(body)
        binding_id = _hash({
            "asset_sha256": asset_sha256,
            "rights_record_id": rights_record_id,
            "eligibility_hash": eligibility.eligibility_hash,
            "platform": usage.platform,
            "purpose": usage.purpose,
            "stage": RIGHTS_BOUND_VISUAL_INPUT_VERSION,
        })
        return RightsBoundVisualInput(binding_id=binding_id, binding_hash=binding_hash, model_version=RIGHTS_BOUND_VISUAL_INPUT_VERSION,
            asset_sha256=asset_sha256, root_original_id=eligibility.root_original_id, original_sha256=original["original_sha256"],
            provenance_hash=original["provenance_hash"], source_revision_id=source["source_revision_id"], source_hash=source["source_hash"],
            source_url=original["source_url"], creator_name=original["creator_name"], media_class=original["media_class"],
            rights_record_id=rights_record_id, rights_record_hash=record["record_hash"], rights_status=record["rights_status"],
            evidence_set_hash=record["evidence_set_hash"], eligibility_hash=eligibility.eligibility_hash, platform=usage.platform,
            purpose=usage.purpose, territory=usage.territory, attribution_required=bool(record["attribution_required"]),
            attribution_text=record["attribution_text"], license_name=record["license_name"], license_version=record["license_version"],
            license_url=record["license_url"])

    def integrity_check(self) -> str:
        return self.db.execute("PRAGMA integrity_check").fetchone()[0]
