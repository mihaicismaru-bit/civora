from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

import pytest
from PIL import ImageFont

import public_presence_os.visual as visual
from public_presence_os.approval import validate_qa_report
from public_presence_os.identity_runtime import (
    IDENTITY_PASS_STATUS,
    audit_visual_v2,
    exact_font_binding_holds,
    render_visual_v2,
    runtime_contract_holds,
)
from public_presence_os.identity_v2 import (
    CANONICAL_FONT_HASHES,
    CANONICAL_FONT_ROWS,
    EXPECTED_FONT_BINDING_HASH,
    EXPECTED_IDENTITY_PROFILE_HASH,
    FONT_PROFILE_SCOPE,
    IDENTITY_NAME,
)
from public_presence_os.master_draft import build_master_draft_brief
from public_presence_os.native_adapt import build_native_adaptation_bundle
from public_presence_os.qa import VisualQARequest, audit_visual
from public_presence_os.radar import RadarKind, RadarObservation, RadarSourceClass, materialize_signal
from public_presence_os.research import EvidenceAuthority, EvidenceKind, ResearchEvidence, build_research_packet
from public_presence_os.scoring import score_research_packet
from public_presence_os.visual import FontBinding, FontBindingSet, VisualHold, VisualRenderRequest, render_visual

ROOT = Path(__file__).resolve().parents[1]


def h(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def make_bundle():
    source_url = "https://example.gov.ro/news/49"
    signal = materialize_signal(RadarObservation(
        external_ref="story-49",
        source_url=source_url,
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc="2026-09-06T15:20:00Z",
        title="Local announcement",
        excerpt="Specific public detail.",
        topic="transport",
        locality="Valcea",
        synthetic=False,
    ))
    packet = build_research_packet(signal, [ResearchEvidence(
        evidence_id="ev49",
        source_url=source_url,
        authority=EvidenceAuthority.PRIMARY_SOURCE,
        kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc="2026-09-06T15:25:00Z",
        content_sha256=h("evidence-49"),
    )])
    return build_native_adaptation_bundle(
        build_master_draft_brief(packet, score_research_packet(packet))
    )


def make_exact_fonts(tmp_path: Path, monkeypatch) -> FontBindingSet:
    by_role = {row["role"]: row for row in CANONICAL_FONT_ROWS}
    paths = {}
    for role in by_role:
        path = tmp_path / f"{role.lower()}.font-fixture"
        path.write_bytes(("cp49-test-fixture-" + role).encode("utf-8"))
        paths[role] = path

    digest_by_path = {
        str(paths[role]): by_role[role]["sha256"]
        for role in by_role
    }
    monkeypatch.setattr(visual, "sha256_file", lambda path: digest_by_path[str(path)])
    monkeypatch.setattr(visual, "_font", lambda binding, size: ImageFont.load_default(size=size))

    def binding(role: str) -> FontBinding:
        row = by_role[role]
        return FontBinding(
            role=role,
            family=row["family"],
            style=row["style"],
            path=str(paths[role]),
            expected_sha256=row["sha256"],
        )

    return FontBindingSet(
        display=binding("DISPLAY"),
        editorial=binding("EDITORIAL"),
        editorial_italic=binding("EDITORIAL_ITALIC"),
        marginalia=binding("MARGINALIA"),
        profile_scope=FONT_PROFILE_SCOPE,
    )


def test_cp49_runtime_contract_matches_cp48_identity():
    assert runtime_contract_holds() == ()


def test_cp49_exact_binding_activates_v2_render_and_qa(tmp_path, monkeypatch):
    fonts = make_exact_fonts(tmp_path, monkeypatch)
    assert exact_font_binding_holds(fonts) == ()
    assert fonts.binding_hash == EXPECTED_FONT_BINDING_HASH

    bundle = make_bundle()
    request = VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", fonts)
    rendered = render_visual_v2(request)
    again = render_visual_v2(request)
    assert rendered == again
    assert rendered.manifest.identity_name == IDENTITY_NAME
    assert rendered.manifest.identity_profile_hash == EXPECTED_IDENTITY_PROFILE_HASH
    assert rendered.manifest.font_binding_hash == EXPECTED_FONT_BINDING_HASH
    assert rendered.manifest.canonical_identity_equivalent is True
    assert rendered.manifest.network_fetch_performed is False
    assert rendered.manifest.real_account_connection_performed is False
    assert rendered.manifest.queue_authority is False
    assert rendered.manifest.publish_authority is False

    base_report = audit_visual(VisualQARequest(rendered=rendered, bundle=bundle))
    assert base_report.holds == ("HOLD_IDENTITY_EQUIVALENCE",)

    report = audit_visual_v2(VisualQARequest(rendered=rendered, bundle=bundle))
    assert report.identity_equivalence_status == IDENTITY_PASS_STATUS
    assert report.holds == ()
    assert report.verdict == "PASS_VISUAL_QA"
    assert report.approval_input_ready is True
    validate_qa_report(report)


def test_cp49_v2_entrypoint_refuses_noncanonical_local_font_binding(tmp_path, monkeypatch):
    monkeypatch.setattr(visual, "_font", lambda binding, size: ImageFont.load_default(size=size))
    paths = []
    for role in ("display", "editorial", "italic", "mono"):
        path = tmp_path / f"{role}.fixture"
        path.write_bytes(role.encode("utf-8"))
        paths.append(path)

    def bind(role, family, style, path):
        digest = sha256(path.read_bytes()).hexdigest()
        return FontBinding(role, family, style, str(path), digest)

    fonts = FontBindingSet(
        display=bind("DISPLAY", "Inter Display", "SemiBold", paths[0]),
        editorial=bind("EDITORIAL", "Noto Serif", "Regular", paths[1]),
        editorial_italic=bind("EDITORIAL_ITALIC", "Noto Serif", "Italic", paths[2]),
        marginalia=bind("MARGINALIA", "Noto Sans Mono", "Medium", paths[3]),
    )
    with pytest.raises(VisualHold, match="HOLD_IDENTITY_"):
        render_visual_v2(VisualRenderRequest(make_bundle(), "FACEBOOK_PAGE", "TEXT_CARD", fonts))


def test_cp49_mutable_expected_hash_override_is_forbidden(tmp_path, monkeypatch):
    fonts = make_exact_fonts(tmp_path, monkeypatch)
    forged = dict(CANONICAL_FONT_HASHES)
    forged["DISPLAY"] = "0" * 64
    with pytest.raises(VisualHold, match="HOLD_IDENTITY_EXPECTATION_OVERRIDE_FORBIDDEN"):
        render_visual_v2(VisualRenderRequest(
            make_bundle(),
            "FACEBOOK_PAGE",
            "TEXT_CARD",
            fonts,
            expected_canonical_font_hashes=forged,
        ))


def test_cp49_qa_holds_if_v2_manifest_identity_is_tampered(tmp_path, monkeypatch):
    fonts = make_exact_fonts(tmp_path, monkeypatch)
    bundle = make_bundle()
    rendered = render_visual_v2(VisualRenderRequest(bundle, "FACEBOOK_PAGE", "TEXT_CARD", fonts))
    tampered = replace(rendered, manifest=replace(rendered.manifest, identity_name="EDITORIAL_LEDGER_V1"))
    report = audit_visual_v2(VisualQARequest(rendered=tampered, bundle=bundle))
    assert "HOLD_IDENTITY_NAME_MISMATCH" in report.holds
    assert report.verdict == "HOLD_VISUAL_QA"
    assert report.approval_input_ready is False


def test_cp49_policy_and_registry_are_local_only_and_exact_binding():
    policy = json.loads((ROOT / "config" / "identity_runtime_policy.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "config" / "module_registry.json").read_text(encoding="utf-8"))
    runtime = json.loads((ROOT / "config" / "runtime_policy.json").read_text(encoding="utf-8"))

    assert policy["checkpoint"] == "CP49"
    assert policy["identity_name"] == IDENTITY_NAME
    assert policy["expected_font_binding_hash"] == EXPECTED_FONT_BINDING_HASH
    assert policy["expected_identity_profile_hash"] == EXPECTED_IDENTITY_PROFILE_HASH
    assert policy["activation_state"] == "LOCAL_RUNTIME_ACTIVE_EXACT_BINDING_ONLY"
    assert policy["historical_cp29_byte_equivalence_asserted"] is False
    assert policy["legacy_identity_hold_supersession"]["only_when_exact_v2_manifest_passes"] is True
    for key in (
        "queue_authority",
        "publisher_authority",
        "network_fetch_allowed",
        "real_account_connection_allowed",
        "public_publish_allowed",
        "deploy_allowed",
    ):
        assert policy["authority"][key] is False

    assert registry["checkpoint"] == "CP50"
    by_id = {row["id"]: row["status"] for row in registry["modules"]}
    assert by_id["M06_VISUAL"] == "CP49_IDENTITY_V2_RUNTIME_ACTIVE_EXACT_BINDING"
    assert by_id["M07_QA"] == "CP49_IDENTITY_V2_EXACT_QA_GATE_ACTIVE"
    assert by_id["M18_VISUAL_IDENTITY"] == "CP49_V2_RUNTIME_ACTIVE_LOCAL_ONLY"

    assert runtime["global_kill_switch_engaged"] is True
    assert runtime["network_enabled"] is False
    assert runtime["publish_enabled"] is False
    assert runtime["real_accounts_connected"] is False
    assert runtime["deploy_enabled"] is False
