from __future__ import annotations

from dataclasses import replace
from hashlib import sha256

from .control import canonical_json
from .identity_v2 import (
    CANONICAL_FONT_HASHES,
    CANONICAL_FONT_ROWS,
    EXPECTED_FONT_BINDING_HASH,
    EXPECTED_IDENTITY_PROFILE_HASH,
    FONT_PROFILE_SCOPE,
    GRID as IDENTITY_GRID,
    IDENTITY_NAME,
    MARGINALIA_HOOKS as IDENTITY_MARGINALIA_HOOKS,
    PALETTE as IDENTITY_PALETTE,
    PROCEDURAL_MICROCOPY as IDENTITY_PROCEDURAL_MICROCOPY,
    VISUAL_RENDER_SCHEMA_VERSION,
)
from .qa import (
    QA_MODEL_VERSION,
    VisualQAReport,
    VisualQARequest,
    VisualQAVerdict,
    audit_visual,
)
from .visual import (
    FONT_ROLE_CONTRACT,
    GRID as RENDER_GRID,
    MARGINALIA_HOOKS as RENDER_MARGINALIA_HOOKS,
    PALETTE as RENDER_PALETTE,
    PROCEDURAL_MICROCOPY as RENDER_PROCEDURAL_MICROCOPY,
    VISUAL_MODEL_VERSION,
    FontBindingSet,
    RenderedVisual,
    VisualAssetManifest,
    VisualHold,
    VisualRenderRequest,
    render_visual,
)

IDENTITY_RUNTIME_VERSION = "PPOS_VISUAL_IDENTITY_RUNTIME_V1"
IDENTITY_RUNTIME_CHECKPOINT = "CP49"
IDENTITY_PASS_STATUS = "PASS_EDITORIAL_LEDGER_V2_EXACT_BINDING"
IDENTITY_HOLD_STATUS = "HOLD_EDITORIAL_LEDGER_V2_EXACT_BINDING_REQUIRED"
LEGACY_IDENTITY_HOLD = "HOLD_IDENTITY_EQUIVALENCE"


def _hash(value) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def runtime_contract_holds() -> tuple[str, ...]:
    """Verify that the CP40 renderer grammar still matches the CP48 V2 contract."""
    holds: list[str] = []
    if VISUAL_MODEL_VERSION != VISUAL_RENDER_SCHEMA_VERSION:
        holds.append("HOLD_IDENTITY_RENDER_SCHEMA_DRIFT")
    if RENDER_PALETTE != IDENTITY_PALETTE:
        holds.append("HOLD_IDENTITY_PALETTE_DRIFT")
    if RENDER_GRID != IDENTITY_GRID:
        holds.append("HOLD_IDENTITY_GRID_DRIFT")
    if tuple(RENDER_MARGINALIA_HOOKS) != tuple(IDENTITY_MARGINALIA_HOOKS):
        holds.append("HOLD_IDENTITY_MARGINALIA_DRIFT")
    if tuple(RENDER_PROCEDURAL_MICROCOPY) != tuple(IDENTITY_PROCEDURAL_MICROCOPY):
        holds.append("HOLD_IDENTITY_MICROCOPY_DRIFT")

    canonical_roles = {
        row["role"]: (row["family"], row["style"])
        for row in CANONICAL_FONT_ROWS
    }
    if FONT_ROLE_CONTRACT != canonical_roles:
        holds.append("HOLD_IDENTITY_FONT_ROLE_CONTRACT_DRIFT")
    return tuple(sorted(set(holds)))


def exact_font_binding_holds(fonts: FontBindingSet) -> tuple[str, ...]:
    holds: list[str] = list(runtime_contract_holds())
    try:
        rows = fonts.verified_rows()
    except VisualHold as exc:
        return tuple(sorted(set(holds + [exc.reason])))

    if fonts.profile_scope != FONT_PROFILE_SCOPE:
        holds.append("HOLD_IDENTITY_FONT_PROFILE_SCOPE_MISMATCH")

    canonical_by_role = {row["role"]: row for row in CANONICAL_FONT_ROWS}
    if {row["role"] for row in rows} != set(canonical_by_role):
        holds.append("HOLD_IDENTITY_FONT_ROLE_SET_MISMATCH")

    for row in rows:
        canonical = canonical_by_role.get(row["role"])
        if canonical is None:
            continue
        if row["family"] != canonical["family"]:
            holds.append(f"HOLD_IDENTITY_FONT_{row['role']}_FAMILY_MISMATCH")
        if row["style"] != canonical["style"]:
            holds.append(f"HOLD_IDENTITY_FONT_{row['role']}_STYLE_MISMATCH")
        if row["sha256"] != canonical["sha256"]:
            holds.append(f"HOLD_IDENTITY_FONT_{row['role']}_HASH_MISMATCH")

    try:
        if fonts.binding_hash != EXPECTED_FONT_BINDING_HASH:
            holds.append("HOLD_IDENTITY_FONT_BINDING_HASH_MISMATCH")
    except VisualHold as exc:
        holds.append(exc.reason)
    return tuple(sorted(set(holds)))


def exact_manifest_identity_holds(manifest: VisualAssetManifest) -> tuple[str, ...]:
    holds: list[str] = list(runtime_contract_holds())
    if manifest.identity_name != IDENTITY_NAME:
        holds.append("HOLD_IDENTITY_NAME_MISMATCH")
    if manifest.font_binding_hash != EXPECTED_FONT_BINDING_HASH:
        holds.append("HOLD_IDENTITY_FONT_BINDING_HASH_MISMATCH")
    if manifest.identity_profile_hash != EXPECTED_IDENTITY_PROFILE_HASH:
        holds.append("HOLD_IDENTITY_PROFILE_HASH_MISMATCH")
    if manifest.canonical_identity_equivalent is not True:
        holds.append("HOLD_IDENTITY_EXACT_BINDING_FLAG_FALSE")
    return tuple(sorted(set(holds)))


def _runtime_render_key(manifest: VisualAssetManifest) -> str:
    return _hash({
        "renderer_version": manifest.renderer_version,
        "model_version": manifest.model_version,
        "bundle_hash": manifest.bundle_hash,
        "adaptation_hash": manifest.adaptation_hash,
        "platform": manifest.platform,
        "mode": manifest.mode,
        "identity_profile_hash": EXPECTED_IDENTITY_PROFILE_HASH,
        "renderer_env_hash": manifest.renderer_env_hash,
        "rights_binding_hash": manifest.rights_binding_hash,
        "source_media_sha256": manifest.source_media_sha256,
    })


def render_visual_v2(request: VisualRenderRequest) -> RenderedVisual:
    """Canonical CP49 M06 entrypoint. It has local render authority only."""
    supplied = request.expected_canonical_font_hashes
    if supplied is not None and dict(supplied) != CANONICAL_FONT_HASHES:
        raise VisualHold("HOLD_IDENTITY_EXPECTATION_OVERRIDE_FORBIDDEN")

    holds = exact_font_binding_holds(request.fonts)
    if holds:
        raise VisualHold(holds[0])

    base_request = replace(
        request,
        expected_canonical_font_hashes=dict(CANONICAL_FONT_HASHES),
    )
    rendered = render_visual(base_request)
    manifest = rendered.manifest
    if manifest.font_binding_hash != EXPECTED_FONT_BINDING_HASH:
        raise VisualHold("HOLD_IDENTITY_FONT_BINDING_HASH_MISMATCH")
    if manifest.canonical_identity_equivalent is not True:
        raise VisualHold(IDENTITY_HOLD_STATUS)

    render_key = _runtime_render_key(manifest)
    activated_manifest = replace(
        manifest,
        asset_id="ma_" + render_key[:24],
        render_key=render_key,
        identity_name=IDENTITY_NAME,
        identity_profile_hash=EXPECTED_IDENTITY_PROFILE_HASH,
        canonical_identity_equivalent=True,
        font_binding_hash=EXPECTED_FONT_BINDING_HASH,
    )
    return RenderedVisual(
        manifest=activated_manifest,
        svg_bytes=rendered.svg_bytes,
        png_bytes=rendered.png_bytes,
    )


def _qa_report_body(report: VisualQAReport) -> dict:
    return {
        "schema_version": QA_MODEL_VERSION,
        "engine_version": report.engine_version,
        "asset_id": report.asset_id,
        "render_key": report.render_key,
        "platform": report.platform,
        "mode": report.mode,
        "bundle_id": report.bundle_id,
        "bundle_hash": report.bundle_hash,
        "adaptation_id": report.adaptation_id,
        "adaptation_hash": report.adaptation_hash,
        "svg_sha256": report.svg_sha256,
        "png_sha256": report.png_sha256,
        "width": report.width,
        "height": report.height,
        "integrity_status": report.integrity_status,
        "text_integrity_status": report.text_integrity_status,
        "svg_safety_status": report.svg_safety_status,
        "png_status": report.png_status,
        "rights_status": report.rights_status,
        "alt_text": report.alt_text,
        "alt_text_status": report.alt_text_status,
        "photo_relevance_status": report.photo_relevance_status,
        "subject_safe_zone_status": report.subject_safe_zone_status,
        "identity_equivalence_status": report.identity_equivalence_status,
        "holds": tuple(report.holds),
        "verdict": report.verdict,
        "approval_input_ready": report.approval_input_ready,
        "state": "VISUAL_QA_ONLY",
        "visual_qa_authority": True,
        "queue_authority": False,
        "publish_authority": False,
        "publish_eligible": False,
        "network_fetch_performed": False,
        "real_account_connection_performed": False,
    }


def audit_visual_v2(request: VisualQARequest) -> VisualQAReport:
    """Canonical CP49 M07 entrypoint with an exact V2 identity gate."""
    base = audit_visual(request)
    holds = set(base.holds)
    holds.discard(LEGACY_IDENTITY_HOLD)

    identity_holds = exact_manifest_identity_holds(request.rendered.manifest)
    if identity_holds:
        holds.update(identity_holds)
        identity_status = IDENTITY_HOLD_STATUS
    else:
        identity_status = IDENTITY_PASS_STATUS

    canonical_holds = tuple(sorted(holds))
    verdict = VisualQAVerdict.HOLD.value if canonical_holds else VisualQAVerdict.PASS.value
    approval_ready = verdict == VisualQAVerdict.PASS.value and not canonical_holds

    updated = replace(
        base,
        report_id="",
        report_hash="",
        identity_equivalence_status=identity_status,
        holds=canonical_holds,
        verdict=verdict,
        approval_input_ready=approval_ready,
    )
    report_hash = _hash(_qa_report_body(updated))
    return replace(
        updated,
        report_id="vqr_" + report_hash[:24],
        report_hash=report_hash,
    )
