from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit, urlunsplit

from .native_adapt import (
    ACTIVE_NATIVE_PLATFORMS,
    NATIVE_ADAPT_MODEL_VERSION,
    NativeAdaptationBundle,
)

RIGHTS_MODEL_VERSION = "PPOS_RIGHTS_BOUND_VISUAL_INPUT_V1"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")


class RightsStatus(str, Enum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    FAIR_USE_REVIEW = "FAIR_USE_REVIEW"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class RightsBasis(str, Enum):
    OWNERSHIP = "OWNERSHIP"
    LICENSE_GRANT = "LICENSE_GRANT"
    PUBLIC_DOMAIN_DETERMINATION = "PUBLIC_DOMAIN_DETERMINATION"
    CC0_DEDICATION = "CC0_DEDICATION"
    FAIR_USE_REVIEW = "FAIR_USE_REVIEW"
    UNKNOWN = "UNKNOWN"
    REVOCATION = "REVOCATION"


class AcquisitionRoute(str, Enum):
    OWNED_CAPTURE = "OWNED_CAPTURE"
    LICENSED_DIRECT_DOWNLOAD = "LICENSED_DIRECT_DOWNLOAD"
    PUBLIC_DOMAIN_DIRECT_DOWNLOAD = "PUBLIC_DOMAIN_DIRECT_DOWNLOAD"


class SubjectClearance(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    CLEARED = "CLEARED"
    PENDING = "PENDING"
    REQUIRED = "REQUIRED"
    BLOCKED = "BLOCKED"


class MediaClass(str, Enum):
    CONTEXTUAL_PHOTO = "CONTEXTUAL_PHOTO"
    PROFILE_PHOTO = "PROFILE_PHOTO"


class ModificationPolicy(str, Enum):
    ALLOWED = "ALLOWED"
    NOT_ALLOWED = "NOT_ALLOWED"
    UNKNOWN = "UNKNOWN"


class RightsDecisionStatus(str, Enum):
    ELIGIBLE_RENDER_QA = "ELIGIBLE_RENDER_QA"
    HOLD_RIGHTS = "HOLD_RIGHTS"
    HOLD_HUMAN_REVIEW = "HOLD_HUMAN_REVIEW"
    HOLD_STALE_RIGHTS = "HOLD_STALE_RIGHTS"
    BLOCKED = "BLOCKED"


class RightsPackageStatus(str, Enum):
    READY_REQUIRED_VISUAL_LANES = "READY_REQUIRED_VISUAL_LANES"
    HOLD_REQUIRED_VISUAL_LANES = "HOLD_REQUIRED_VISUAL_LANES"
    BLOCKED_REQUIRED_VISUAL_LANES = "BLOCKED_REQUIRED_VISUAL_LANES"


AUTO_ELIGIBLE = {
    RightsStatus.OWNED.value,
    RightsStatus.LICENSED.value,
    RightsStatus.PUBLIC_DOMAIN.value,
}
REQUIRED_VISUAL_PLATFORMS = ("INSTAGRAM_PROFESSIONAL",)
PROHIBITED_ACQUISITION_ROUTES = {
    "SOCIAL_DOWNLOAD_UNCLEARED",
    "SEARCH_ENGINE_DOWNLOAD",
    "PRESS_COPY_UNCLEARED",
    "MAP_SCREENSHOT_AS_PHOTO",
}


@dataclass(frozen=True)
class ImageOriginalSpec:
    original_sha256: str
    mime_type: str
    byte_size: int
    media_class: MediaClass
    creator_name: str
    creator_identity_status: str
    acquisition_route: AcquisitionRoute
    acquisition_source_url: str
    acquired_at_utc: str
    discovery_source_url: str = ""
    capture_at_utc: str = ""
    capture_location: str = ""
    subject_clearance_status: SubjectClearance = SubjectClearance.NOT_APPLICABLE
    metadata_sha256: str = ""


@dataclass(frozen=True)
class ImageOriginal:
    original_id: str
    original_sha256: str
    provenance_hash: str
    mime_type: str
    byte_size: int
    media_class: str
    creator_name: str
    creator_identity_status: str
    acquisition_route: str
    acquisition_source_url: str
    acquired_at_utc: str
    discovery_source_url: str
    capture_at_utc: str
    capture_location: str
    subject_clearance_status: str
    metadata_sha256: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RightsEvidenceSpec:
    evidence_id: str
    evidence_kind: str
    snapshot_sha256: str
    snapshot_size: int
    canonical_uri: str
    acquired_at_utc: str
    note: str = ""


@dataclass(frozen=True)
class RightsEvidence:
    evidence_id: str
    evidence_kind: str
    snapshot_sha256: str
    snapshot_size: int
    canonical_uri: str
    acquired_at_utc: str
    note: str
    evidence_hash: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RightsRecordSpec:
    revision: int
    rights_status: RightsStatus
    basis_type: RightsBasis
    rights_holder: str
    permitted_platforms: tuple[str, ...]
    permitted_purposes: tuple[str, ...]
    territory: str
    commercial_use_allowed: bool | None
    modification_policy: ModificationPolicy
    attribution_required: bool
    attribution_text: str
    valid_from_utc: str
    expires_at_utc: str = ""
    review_at_utc: str = ""
    license_name: str = ""
    license_version: str = ""
    license_url: str = ""
    share_alike_required: bool = False
    required_output_license: str = ""
    revocable: bool = True
    supersedes_rights_record_id: str = ""


@dataclass(frozen=True)
class RightsRecord:
    rights_record_id: str
    record_hash: str
    original_id: str
    revision: int
    rights_status: str
    basis_type: str
    rights_holder: str
    license_name: str
    license_version: str
    license_url: str
    permitted_platforms: tuple[str, ...]
    permitted_purposes: tuple[str, ...]
    territory: str
    commercial_use_allowed: bool | None
    modification_policy: str
    attribution_required: bool
    attribution_text: str
    share_alike_required: bool
    required_output_license: str
    valid_from_utc: str
    expires_at_utc: str
    review_at_utc: str
    revocable: bool
    evidence_set_hash: str
    supersedes_rights_record_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class UsageRequest:
    platform: str
    purpose: str
    intended_at_utc: str
    rights_record_id: str
    modifications_required: bool
    commercial_context: bool
    territory: str
    output_license: str = ""


@dataclass(frozen=True)
class RightsLaneDecision:
    platform: str
    purpose: str
    status: str
    reasons: tuple[str, ...]
    rights_record_id: str
    rights_record_hash: str
    evidence_set_hash: str
    eligibility_hash: str
    eligible_render_qa: bool
    publish_eligible: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    api_write_allowed: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class RightsBoundVisualInput:
    rights_input_id: str
    rights_input_hash: str
    model_version: str
    native_bundle_id: str
    native_bundle_hash: str
    original_id: str
    original_sha256: str
    provenance_hash: str
    current_rights_record_id: str
    current_rights_record_hash: str
    evidence_set_hash: str
    lane_decisions: tuple[RightsLaneDecision, ...]
    required_visual_platforms: tuple[str, ...]
    package_status: str
    visual_input_ready: bool
    state: str = "RIGHTS_BOUND_VISUAL_INPUT_ONLY"
    rights_authority: bool = True
    fact_authority: bool = False
    visual_authority: bool = False
    approval_authority: bool = False
    queue_authority: bool = False
    publish_authority: bool = False
    api_write_allowed: bool = False
    network_fetch_performed: bool = False
    real_account_connection_performed: bool = False

    def to_dict(self) -> dict:
        value = asdict(self)
        value["lane_decisions"] = [v.to_dict() for v in self.lane_decisions]
        return value


def _canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_sha(value: str, field: str) -> str:
    if not HEX64.fullmatch(value or ""):
        raise ValueError(f"{field} must be lowercase sha256")
    return value


def _utc(value: str, field: str, *, optional: bool = False) -> str:
    if optional and not value:
        return ""
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must use Z UTC")
    try:
        dt = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} is invalid") from exc
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"{field} must be UTC")
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _uri(value: str, field: str, *, allow_local: bool = True, optional: bool = False) -> str:
    if optional and not value:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    parsed = urlsplit(value.strip())
    allowed = {"https"} | ({"local"} if allow_local else set())
    if parsed.scheme not in allowed or not parsed.netloc:
        raise ValueError(f"{field} requires {'https or local' if allow_local else 'https'} URI")
    if "@" in parsed.netloc:
        raise ValueError(f"{field} userinfo is not allowed")
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path or "/", parsed.query, ""))


def _validate_native_bundle(bundle: NativeAdaptationBundle) -> None:
    if not isinstance(bundle, NativeAdaptationBundle):
        raise ValueError("rights input must be a NativeAdaptationBundle")
    if bundle.model_version != NATIVE_ADAPT_MODEL_VERSION:
        raise ValueError("unsupported M05 model version")
    if tuple(bundle.active_platforms) != tuple(ACTIVE_NATIVE_PLATFORMS):
        raise ValueError("M05 active platform set mismatch")
    if bundle.state != "NATIVE_ADAPTATION_ONLY" or not bundle.native_adaptation_authority:
        raise ValueError("rights stage accepts canonical M05 bundles only")
    if bundle.fact_authority or bundle.visual_authority or bundle.queue_authority or bundle.publish_authority:
        raise ValueError("M05 bundle carries forbidden downstream authority")
    if bundle.network_fetch_performed or bundle.real_account_connection_performed:
        raise ValueError("M05 bundle must be local and disconnected")
    if not bundle.rights_input_ready:
        raise ValueError("M05 bundle is not rights_input_ready")
    if tuple(v.platform for v in bundle.adaptations) != tuple(ACTIVE_NATIVE_PLATFORMS):
        raise ValueError("M05 adaptation platform order mismatch")
    for item in bundle.adaptations:
        body = {
            "schema_version": NATIVE_ADAPT_MODEL_VERSION,
            "brief_id": bundle.brief_id,
            "brief_hash": bundle.brief_hash,
            "platform": item.platform,
            "status": item.status,
            "text": item.text,
            "char_count": item.char_count,
            "house_max_chars": item.house_max_chars,
            "content_surface": item.content_surface,
            "visual_requirement": item.visual_requirement,
            "source_url": item.source_url,
            "evidence_ids": item.evidence_ids,
            "support_kinds": item.support_kinds,
            "unknowns": item.unknowns,
            "constraints": item.constraints,
            "adaptation_ready": item.adaptation_ready,
            "api_write_allowed": item.api_write_allowed,
            "queue_authority": item.queue_authority,
            "publish_authority": item.publish_authority,
            "network_fetch_performed": item.network_fetch_performed,
            "real_account_connection_performed": item.real_account_connection_performed,
        }
        expected_id = _hash({
            "brief_id": bundle.brief_id,
            "brief_hash": bundle.brief_hash,
            "platform": item.platform,
            "stage": NATIVE_ADAPT_MODEL_VERSION,
        })
        if item.adaptation_id != expected_id or item.adaptation_hash != _hash(body):
            raise ValueError("M05 adaptation integrity check failed")
        if not item.adaptation_ready:
            raise ValueError("rights-ready M05 bundle contains non-ready lane")
    bundle_body = {
        "schema_version": NATIVE_ADAPT_MODEL_VERSION,
        "brief_id": bundle.brief_id,
        "brief_hash": bundle.brief_hash,
        "source_url": bundle.source_url,
        "source_class": bundle.source_class,
        "topic": bundle.topic,
        "locality": bundle.locality,
        "adaptations": [v.to_dict() for v in bundle.adaptations],
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
    expected_bundle_id = _hash({
        "brief_id": bundle.brief_id,
        "brief_hash": bundle.brief_hash,
        "stage": NATIVE_ADAPT_MODEL_VERSION,
    })
    if bundle.bundle_id != expected_bundle_id or bundle.bundle_hash != _hash(bundle_body):
        raise ValueError("M05 bundle integrity check failed")


def materialize_image_original(spec: ImageOriginalSpec) -> ImageOriginal:
    if not isinstance(spec, ImageOriginalSpec):
        raise ValueError("image original requires ImageOriginalSpec")
    original_sha = _require_sha(spec.original_sha256, "original_sha256")
    if not isinstance(spec.media_class, MediaClass):
        raise ValueError("media_class is invalid")
    if not isinstance(spec.acquisition_route, AcquisitionRoute):
        route = str(spec.acquisition_route)
        if route in PROHIBITED_ACQUISITION_ROUTES:
            raise ValueError("uncleared discovery route cannot acquire an original")
        raise ValueError("acquisition_route is not authorized")
    if not isinstance(spec.subject_clearance_status, SubjectClearance):
        raise ValueError("subject_clearance_status is invalid")
    if spec.byte_size <= 0:
        raise ValueError("byte_size must be positive")
    if not isinstance(spec.mime_type, str) or not spec.mime_type.startswith("image/"):
        raise ValueError("mime_type must be an image MIME type")
    if not spec.creator_name.strip() or not spec.creator_identity_status.strip():
        raise ValueError("creator identity fields are required")
    acquired = _utc(spec.acquired_at_utc, "acquired_at_utc")
    capture = _utc(spec.capture_at_utc, "capture_at_utc", optional=True)
    external_route = spec.acquisition_route in {
        AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD,
        AcquisitionRoute.PUBLIC_DOMAIN_DIRECT_DOWNLOAD,
    }
    acquisition_url = _uri(spec.acquisition_source_url, "acquisition_source_url", allow_local=not external_route)
    discovery_url = _uri(spec.discovery_source_url, "discovery_source_url", allow_local=False, optional=True)
    metadata_sha = ""
    if spec.metadata_sha256:
        metadata_sha = _require_sha(spec.metadata_sha256, "metadata_sha256")
    provenance_body = {
        "original_sha256": original_sha,
        "mime_type": spec.mime_type,
        "byte_size": spec.byte_size,
        "media_class": spec.media_class.value,
        "creator_name": spec.creator_name.strip(),
        "creator_identity_status": spec.creator_identity_status.strip(),
        "acquisition_route": spec.acquisition_route.value,
        "acquisition_source_url": acquisition_url,
        "acquired_at_utc": acquired,
        "discovery_source_url": discovery_url,
        "capture_at_utc": capture,
        "capture_location": spec.capture_location.strip(),
        "subject_clearance_status": spec.subject_clearance_status.value,
        "metadata_sha256": metadata_sha,
    }
    provenance_hash = _hash(provenance_body)
    original_id = _hash({"original_sha256": original_sha, "provenance_hash": provenance_hash})
    return ImageOriginal(
        original_id=original_id,
        original_sha256=original_sha,
        provenance_hash=provenance_hash,
        mime_type=spec.mime_type,
        byte_size=spec.byte_size,
        media_class=spec.media_class.value,
        creator_name=spec.creator_name.strip(),
        creator_identity_status=spec.creator_identity_status.strip(),
        acquisition_route=spec.acquisition_route.value,
        acquisition_source_url=acquisition_url,
        acquired_at_utc=acquired,
        discovery_source_url=discovery_url,
        capture_at_utc=capture,
        capture_location=spec.capture_location.strip(),
        subject_clearance_status=spec.subject_clearance_status.value,
        metadata_sha256=metadata_sha,
    )


def materialize_rights_evidence(spec: RightsEvidenceSpec) -> RightsEvidence:
    if not isinstance(spec, RightsEvidenceSpec):
        raise ValueError("rights evidence requires RightsEvidenceSpec")
    if not ID_RE.fullmatch(spec.evidence_id or ""):
        raise ValueError("evidence_id is invalid")
    snapshot_sha = _require_sha(spec.snapshot_sha256, "snapshot_sha256")
    if spec.snapshot_size <= 0:
        raise ValueError("snapshot_size must be positive")
    uri = _uri(spec.canonical_uri, "canonical_uri", allow_local=True)
    acquired = _utc(spec.acquired_at_utc, "acquired_at_utc")
    if not spec.evidence_kind.strip():
        raise ValueError("evidence_kind is required")
    body = {
        "evidence_id": spec.evidence_id,
        "evidence_kind": spec.evidence_kind.strip(),
        "snapshot_sha256": snapshot_sha,
        "snapshot_size": spec.snapshot_size,
        "canonical_uri": uri,
        "acquired_at_utc": acquired,
        "note": spec.note.strip(),
    }
    return RightsEvidence(**body, evidence_hash=_hash(body))


def evidence_set_hash(evidence) -> str:
    evidence = tuple(evidence)
    if not evidence:
        raise ValueError("rights record requires snapshot evidence")
    by_id: dict[str, RightsEvidence] = {}
    for item in evidence:
        if not isinstance(item, RightsEvidence):
            raise ValueError("evidence set contains invalid item")
        previous = by_id.get(item.evidence_id)
        if previous and previous != item:
            raise ValueError("conflicting rights evidence ID")
        by_id.setdefault(item.evidence_id, item)
    ordered = tuple(sorted(by_id.values(), key=lambda v: (v.evidence_id, v.evidence_hash)))
    return _hash({"evidence_hashes": [v.evidence_hash for v in ordered]})


def _validate_auto_basis(original: ImageOriginal, spec: RightsRecordSpec) -> None:
    if spec.rights_status == RightsStatus.OWNED:
        if spec.basis_type != RightsBasis.OWNERSHIP or original.acquisition_route != AcquisitionRoute.OWNED_CAPTURE.value:
            raise ValueError("OWNED requires ownership basis and owned-capture provenance")
    elif spec.rights_status == RightsStatus.LICENSED:
        if spec.basis_type != RightsBasis.LICENSE_GRANT or original.acquisition_route != AcquisitionRoute.LICENSED_DIRECT_DOWNLOAD.value:
            raise ValueError("LICENSED requires license grant and direct licensed acquisition")
        if spec.commercial_use_allowed is None or spec.modification_policy == ModificationPolicy.UNKNOWN:
            raise ValueError("LICENSED scope must explicitly cover commercial use and modifications")
        if not spec.license_name.strip() or not spec.license_url.strip():
            raise ValueError("LICENSED requires license identity and legal URL")
        _uri(spec.license_url, "license_url", allow_local=False)
    elif spec.rights_status == RightsStatus.PUBLIC_DOMAIN:
        if spec.basis_type not in {RightsBasis.PUBLIC_DOMAIN_DETERMINATION, RightsBasis.CC0_DEDICATION}:
            raise ValueError("PUBLIC_DOMAIN requires an evidence-backed public-domain basis")
        if original.acquisition_route != AcquisitionRoute.PUBLIC_DOMAIN_DIRECT_DOWNLOAD.value:
            raise ValueError("PUBLIC_DOMAIN requires direct public-domain acquisition")


def materialize_rights_record(original: ImageOriginal, spec: RightsRecordSpec, evidence) -> RightsRecord:
    if not isinstance(original, ImageOriginal) or not isinstance(spec, RightsRecordSpec):
        raise ValueError("rights record inputs are invalid")
    if not isinstance(spec.rights_status, RightsStatus) or not isinstance(spec.basis_type, RightsBasis):
        raise ValueError("rights status or basis is invalid")
    if not isinstance(spec.modification_policy, ModificationPolicy):
        raise ValueError("modification policy is invalid")
    if spec.revision < 1:
        raise ValueError("rights revision must be positive")
    if not spec.rights_holder.strip():
        raise ValueError("rights_holder is required")
    platforms = tuple(sorted(dict.fromkeys(spec.permitted_platforms)))
    purposes = tuple(sorted(dict.fromkeys(spec.permitted_purposes)))
    if any(p not in ACTIVE_NATIVE_PLATFORMS for p in platforms):
        raise ValueError("rights record contains a non-active platform")
    if spec.rights_status.value in AUTO_ELIGIBLE and (not platforms or not purposes or not spec.territory.strip()):
        raise ValueError("auto-eligible rights require explicit platform, purpose and territory scope")
    _validate_auto_basis(original, spec)
    if spec.attribution_required and not spec.attribution_text.strip():
        raise ValueError("required attribution text is missing")
    if spec.share_alike_required and not spec.required_output_license.strip():
        raise ValueError("ShareAlike requires an explicit output license")
    valid_from = _utc(spec.valid_from_utc, "valid_from_utc")
    expires = _utc(spec.expires_at_utc, "expires_at_utc", optional=True)
    review = _utc(spec.review_at_utc, "review_at_utc", optional=True)
    if expires and expires < valid_from:
        raise ValueError("rights expiry cannot predate valid_from")
    if review and review < valid_from:
        raise ValueError("rights review cannot predate valid_from")
    ev_hash = evidence_set_hash(evidence)
    record_id = _hash({
        "original_id": original.original_id,
        "revision": spec.revision,
        "stage": RIGHTS_MODEL_VERSION,
    })
    body = {
        "original_id": original.original_id,
        "revision": spec.revision,
        "rights_status": spec.rights_status.value,
        "basis_type": spec.basis_type.value,
        "rights_holder": spec.rights_holder.strip(),
        "license_name": spec.license_name.strip(),
        "license_version": spec.license_version.strip(),
        "license_url": spec.license_url.strip(),
        "permitted_platforms": platforms,
        "permitted_purposes": purposes,
        "territory": spec.territory.strip(),
        "commercial_use_allowed": spec.commercial_use_allowed,
        "modification_policy": spec.modification_policy.value,
        "attribution_required": spec.attribution_required,
        "attribution_text": spec.attribution_text.strip(),
        "share_alike_required": spec.share_alike_required,
        "required_output_license": spec.required_output_license.strip(),
        "valid_from_utc": valid_from,
        "expires_at_utc": expires,
        "review_at_utc": review,
        "revocable": spec.revocable,
        "evidence_set_hash": ev_hash,
        "supersedes_rights_record_id": spec.supersedes_rights_record_id,
    }
    return RightsRecord(
        rights_record_id=record_id,
        record_hash=_hash(body),
        **body,
    )


def _validate_record_chain(original: ImageOriginal, records) -> tuple[RightsRecord, ...]:
    records = tuple(records)
    if not records:
        raise ValueError("at least one rights record is required")
    ordered = tuple(sorted(records, key=lambda v: v.revision))
    for idx, record in enumerate(ordered):
        if not isinstance(record, RightsRecord) or record.original_id != original.original_id:
            raise ValueError("rights record belongs to a different original")
        if record.revision != idx + 1:
            raise ValueError("rights revisions must be contiguous from 1")
        expected_id = _hash({"original_id": original.original_id, "revision": record.revision, "stage": RIGHTS_MODEL_VERSION})
        body = record.to_dict()
        body.pop("rights_record_id")
        body.pop("record_hash")
        if record.rights_record_id != expected_id or record.record_hash != _hash(body):
            raise ValueError("rights record integrity check failed")
        expected_previous = "" if idx == 0 else ordered[idx - 1].rights_record_id
        if record.supersedes_rights_record_id != expected_previous:
            raise ValueError("rights supersession chain is invalid")
    return ordered


def _decision(original: ImageOriginal, current: RightsRecord, ev_hash: str, request: UsageRequest) -> RightsLaneDecision:
    if request.platform not in ACTIVE_NATIVE_PLATFORMS:
        raise ValueError("usage request targets a non-active platform")
    intended = _utc(request.intended_at_utc, "intended_at_utc")
    reasons: list[str] = []
    status: RightsDecisionStatus

    if request.rights_record_id != current.rights_record_id:
        if current.rights_status == RightsStatus.BLOCKED.value or current.basis_type == RightsBasis.REVOCATION.value:
            status = RightsDecisionStatus.BLOCKED
            reasons.append("CURRENT_RIGHTS_REVOKED_OR_BLOCKED")
        else:
            status = RightsDecisionStatus.HOLD_STALE_RIGHTS
            reasons.append("REQUEST_REFERENCES_SUPERSEDED_RIGHTS")
    elif current.evidence_set_hash != ev_hash:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("EVIDENCE_SET_HASH_MISMATCH")
    elif original.subject_clearance_status == SubjectClearance.BLOCKED.value:
        status = RightsDecisionStatus.BLOCKED
        reasons.append("SUBJECT_CLEARANCE_BLOCKED")
    elif original.subject_clearance_status in {SubjectClearance.PENDING.value, SubjectClearance.REQUIRED.value}:
        status = RightsDecisionStatus.HOLD_HUMAN_REVIEW
        reasons.append("SUBJECT_CLEARANCE_NOT_COMPLETE")
    elif original.media_class == MediaClass.PROFILE_PHOTO.value and request.purpose == "SOCIAL_EDITORIAL":
        status = RightsDecisionStatus.BLOCKED
        reasons.append("PROFILE_PHOTO_NOT_SOCIAL_EDITORIAL_MEDIA")
    elif current.rights_status == RightsStatus.BLOCKED.value:
        status = RightsDecisionStatus.BLOCKED
        reasons.append("RIGHTS_STATUS_BLOCKED")
    elif current.rights_status == RightsStatus.FAIR_USE_REVIEW.value:
        status = RightsDecisionStatus.HOLD_HUMAN_REVIEW
        reasons.append("FAIR_USE_REQUIRES_HUMAN_REVIEW")
    elif current.rights_status == RightsStatus.UNKNOWN.value:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("RIGHTS_STATUS_UNKNOWN")
    elif current.rights_status not in AUTO_ELIGIBLE:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("RIGHTS_STATUS_NOT_AUTO_ELIGIBLE")
    elif intended < current.valid_from_utc:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("RIGHTS_NOT_YET_VALID")
    elif current.expires_at_utc and intended > current.expires_at_utc:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("RIGHTS_EXPIRED")
    elif current.review_at_utc and intended > current.review_at_utc:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("RIGHTS_REVIEW_OVERDUE")
    elif request.platform not in current.permitted_platforms:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("PLATFORM_OUTSIDE_GRANT")
    elif request.purpose not in current.permitted_purposes:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("PURPOSE_OUTSIDE_GRANT")
    elif current.territory not in {"*", "WORLDWIDE", request.territory}:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("TERRITORY_OUTSIDE_GRANT")
    elif request.commercial_context and current.commercial_use_allowed is not True:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("COMMERCIAL_USE_NOT_GRANTED")
    elif request.modifications_required and current.modification_policy != ModificationPolicy.ALLOWED.value:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("MODIFICATIONS_NOT_GRANTED")
    elif current.attribution_required and not current.attribution_text:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("ATTRIBUTION_TEXT_MISSING")
    elif current.share_alike_required and request.output_license != current.required_output_license:
        status = RightsDecisionStatus.HOLD_RIGHTS
        reasons.append("SHARE_ALIKE_OUTPUT_LICENSE_MISMATCH")
    else:
        status = RightsDecisionStatus.ELIGIBLE_RENDER_QA
        reasons.extend(("CURRENT_RIGHTS_RECORD", "SNAPSHOT_EVIDENCE_BOUND", "USAGE_SCOPE_EXPLICIT"))

    eligible = status == RightsDecisionStatus.ELIGIBLE_RENDER_QA
    body = {
        "platform": request.platform,
        "purpose": request.purpose,
        "status": status.value,
        "reasons": tuple(reasons),
        "rights_record_id": current.rights_record_id,
        "rights_record_hash": current.record_hash,
        "evidence_set_hash": ev_hash,
        "eligible_render_qa": eligible,
        "publish_eligible": False,
        "queue_authority": False,
        "publish_authority": False,
        "api_write_allowed": False,
    }
    eligibility_hash = _hash({
        "model": RIGHTS_MODEL_VERSION,
        "original_sha256": original.original_sha256,
        "provenance_hash": original.provenance_hash,
        "request": asdict(request),
        **body,
    })
    return RightsLaneDecision(**body, eligibility_hash=eligibility_hash)


def build_rights_bound_visual_input(
    bundle: NativeAdaptationBundle,
    original: ImageOriginal,
    evidence,
    records,
    usage_requests,
) -> RightsBoundVisualInput:
    _validate_native_bundle(bundle)
    if not isinstance(original, ImageOriginal):
        raise ValueError("rights stage requires a materialized image original")
    evidence = tuple(evidence)
    ev_hash = evidence_set_hash(evidence)
    chain = _validate_record_chain(original, records)
    current = chain[-1]
    requests = tuple(usage_requests)
    if {r.platform for r in requests} != set(ACTIVE_NATIVE_PLATFORMS) or len(requests) != len(ACTIVE_NATIVE_PLATFORMS):
        raise ValueError("usage requests must cover each active platform exactly once")
    if any(not isinstance(r, UsageRequest) or not r.purpose.strip() or not r.territory.strip() for r in requests):
        raise ValueError("usage request is invalid")
    decisions = tuple(
        _decision(original, current, ev_hash, request)
        for request in sorted(requests, key=lambda r: ACTIVE_NATIVE_PLATFORMS.index(r.platform))
    )
    required = tuple(d for d in decisions if d.platform in REQUIRED_VISUAL_PLATFORMS)
    ready = bool(required) and all(d.eligible_render_qa for d in required)
    if ready:
        package_status = RightsPackageStatus.READY_REQUIRED_VISUAL_LANES
    elif any(d.status == RightsDecisionStatus.BLOCKED.value for d in required):
        package_status = RightsPackageStatus.BLOCKED_REQUIRED_VISUAL_LANES
    else:
        package_status = RightsPackageStatus.HOLD_REQUIRED_VISUAL_LANES
    body = {
        "schema_version": RIGHTS_MODEL_VERSION,
        "native_bundle_id": bundle.bundle_id,
        "native_bundle_hash": bundle.bundle_hash,
        "original_id": original.original_id,
        "original_sha256": original.original_sha256,
        "provenance_hash": original.provenance_hash,
        "current_rights_record_id": current.rights_record_id,
        "current_rights_record_hash": current.record_hash,
        "evidence_set_hash": ev_hash,
        "lane_decisions": [d.to_dict() for d in decisions],
        "required_visual_platforms": REQUIRED_VISUAL_PLATFORMS,
        "package_status": package_status.value,
        "visual_input_ready": ready,
        "state": "RIGHTS_BOUND_VISUAL_INPUT_ONLY",
        "rights_authority": True,
        "fact_authority": False,
        "visual_authority": False,
        "approval_authority": False,
        "queue_authority": False,
        "publish_authority": False,
        "api_write_allowed": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }
    rights_input_id = _hash({
        "native_bundle_id": bundle.bundle_id,
        "native_bundle_hash": bundle.bundle_hash,
        "original_id": original.original_id,
        "current_rights_record_id": current.rights_record_id,
        "stage": RIGHTS_MODEL_VERSION,
    })
    return RightsBoundVisualInput(
        rights_input_id=rights_input_id,
        rights_input_hash=_hash(body),
        model_version=RIGHTS_MODEL_VERSION,
        native_bundle_id=bundle.bundle_id,
        native_bundle_hash=bundle.bundle_hash,
        original_id=original.original_id,
        original_sha256=original.original_sha256,
        provenance_hash=original.provenance_hash,
        current_rights_record_id=current.rights_record_id,
        current_rights_record_hash=current.record_hash,
        evidence_set_hash=ev_hash,
        lane_decisions=decisions,
        required_visual_platforms=REQUIRED_VISUAL_PLATFORMS,
        package_status=package_status.value,
        visual_input_ready=ready,
    )


def rights_bound_visual_inputs_json(inputs) -> str:
    by_hash: dict[str, RightsBoundVisualInput] = {}
    for item in tuple(inputs):
        if not isinstance(item, RightsBoundVisualInput):
            raise ValueError("rights JSON input contains invalid item")
        by_hash.setdefault(item.rights_input_hash, item)
    ordered = tuple(sorted(by_hash.values(), key=lambda v: (not v.visual_input_ready, v.rights_input_id, v.rights_input_hash)))
    return json.dumps([v.to_dict() for v in ordered], indent=2, ensure_ascii=False, sort_keys=True)
