import copy
import json
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.engagement_radar import (
    EngagementObservation,
    EngagementScoreEvidence,
    compile_engagement_radar,
    score_candidate,
)
from public_presence_os.growth_capability_matrix import compile_growth_capability_matrix
from public_presence_os.outbound_engagement import (
    COMPOSER_MODES,
    OutboundEngagementHold,
    ValueAddProposal,
    compile_outbound_engagement_engine,
    compose_outbound_candidate,
    process_batch,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "outbound_value_add_engagement_policy.json"
CP84_POLICY_PATH = ROOT / "config" / "engagement_radar_policy.json"
CP83_POLICY_PATH = ROOT / "config" / "growth_capability_matrix_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def cp83_contract():
    return compile_growth_capability_matrix(json.loads(CP83_POLICY_PATH.read_text(encoding="utf-8")))


def contract():
    return compile_outbound_engagement_engine(load_policy(), cp83_contract())


def radar_candidate(platform="THREADS", *, eligible=True):
    cp83 = cp83_contract()
    cp84 = compile_engagement_radar(json.loads(CP84_POLICY_PATH.read_text(encoding="utf-8")), cp83)
    scores = EngagementScoreEvidence(
        relevance=90 if eligible else 10,
        expertise_fit=85,
        conversation_momentum=70,
        novelty=75,
        answerability=90,
        reputational_risk=10,
        spam_risk=5,
        expected_relationship_value=80,
    )
    observation = EngagementObservation(
        platform=platform,
        discovery_capability="MENTION_DISCOVERY",
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref=f"fixture:{platform}:conversation:001",
        conversation_ref=f"{platform}-conversation-001",
        source_url=f"synthetic://{platform.lower()}/conversation/001",
        author_public_id="@public_account",
        topic="finantare europeana",
        context="Discutie publica despre un termen procedural si efectul lui practic.",
        observed_at_utc="2026-09-16T10:00:00Z",
        published_at_utc="2026-09-16T09:00:00Z",
        score_evidence=scores,
    )
    return score_candidate(cp84, observation, now_utc="2026-09-16T10:30:00Z")


def proposal(platform="THREADS", **overrides):
    base = dict(
        composer_mode="CLARIFICATION",
        material_value_kind="CLARIFICATION",
        contribution_text="Clarificarea utilă aici este că termenul se verifică în documentul oficial al apelului, nu într-un rezumat secundar.",
        evidence=("Documentul oficial al apelului este sursa de control pentru termen.",),
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref=f"fixture:{platform}:proposal:001",
        target_ref=f"{platform}-conversation-001",
        source_url=f"synthetic://{platform.lower()}/conversation/001",
    )
    base.update(overrides)
    return ValueAddProposal(**base)


def test_cp86_contract_keeps_cp58_and_zero_live_authority():
    c = contract()
    assert c.checkpoint == "CP86"
    assert c.parent_activation_checkpoint == "CP85"
    assert c.parent_radar_checkpoint == "CP84"
    assert c.parent_capability_checkpoint == "CP83"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP87_RELATIONSHIP_GRAPH"
    assert c.global_kill_switch_engaged is True
    assert c.human_review_required is True
    assert c.posting_authority is False
    assert c.external_write_allowed is False
    assert c.external_write_performed is False
    assert c.network_allowed is False
    assert c.network_attempted is False
    assert c.live_probe_allowed is False
    assert c.oauth_attempted is False
    assert c.account_connected is False
    assert c.control_plane_promoted is False
    assert c.deploy_allowed is False
    assert c.external_metrics == "UNKNOWN"
    assert len(c.routes) == 3


def test_cp86_routes_bind_exact_cp83_outbound_capability():
    by_platform = {route.platform: route for route in contract().routes}
    assert by_platform["FACEBOOK_PAGE"].expected_cp83_classification == "MANUAL_ONLY"
    assert by_platform["FACEBOOK_PAGE"].automation_mode == "MANUAL_ACTION_PACKET"
    assert by_platform["INSTAGRAM_PROFESSIONAL"].expected_cp83_classification == "MANUAL_ONLY"
    assert by_platform["INSTAGRAM_PROFESSIONAL"].automation_mode == "MANUAL_ACTION_PACKET"
    assert by_platform["THREADS"].expected_cp83_classification == "PASS_OFFLINE_CONTRACT"
    assert by_platform["THREADS"].automation_mode == "DRY_RUN_API_CANDIDATE"
    assert all(route.specific_target_required for route in by_platform.values())


@pytest.mark.parametrize("mode", COMPOSER_MODES)
def test_cp86_all_canonical_composer_modes_are_supported(mode):
    text = "Ce sursă oficială susține această concluzie?" if mode == "GOOD_QUESTION" else "Aici merită adăugat contextul oficial verificabil."
    item = compose_outbound_candidate(contract(), radar_candidate(), proposal(composer_mode=mode, contribution_text=text))
    assert item.composer_mode == mode
    assert item.decision == "DRY_RUN_API_CANDIDATE_HUMAN_REVIEW"
    assert item.posting_authority is False
    assert item.external_write_allowed is False
    assert item.external_write_attempted is False
    assert item.network_fetch_performed is False


@pytest.mark.parametrize("platform", ["FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL"])
def test_cp86_unverified_external_commenting_becomes_manual_action_packet(platform):
    item = compose_outbound_candidate(contract(), radar_candidate(platform), proposal(platform))
    assert item.cp83_classification == "MANUAL_ONLY"
    assert item.decision == "MANUAL_ACTION_REQUIRED"
    assert item.manual_action_packet is not None
    assert item.manual_action_packet.operator_action_required is True
    assert item.manual_action_packet.automated_dispatch_supported is False
    assert item.manual_action_packet.external_write_attempted is False
    assert "HOLD_CAPABILITY_UNVERIFIED" in item.manual_action_packet.blockers


def test_cp86_threads_is_only_dry_run_candidate_never_live_write():
    item = compose_outbound_candidate(contract(), radar_candidate(), proposal())
    assert item.cp83_classification == "PASS_OFFLINE_CONTRACT"
    assert item.decision == "DRY_RUN_API_CANDIDATE_HUMAN_REVIEW"
    assert item.manual_action_packet is None
    assert "HOLD_LIVE_PERMISSION" in item.blockers
    assert "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED" in item.blockers
    assert item.posting_authority is False
    assert item.external_write_allowed is False


def test_cp86_requires_material_fact_bound_evidence():
    item = compose_outbound_candidate(contract(), radar_candidate(), proposal(evidence=()))
    assert item.decision == "REJECT_NO_FACT_BOUND_EVIDENCE"
    assert item.contribution_text is None
    assert item.external_write_attempted is False


def test_cp86_rejects_noneligible_cp84_candidate():
    item = compose_outbound_candidate(contract(), radar_candidate(eligible=False), proposal())
    assert item.decision == "REJECT_CP84_NOT_ELIGIBLE"
    assert item.contribution_text is None


@pytest.mark.parametrize("flag", [
    "generic_compliment_only", "engagement_bait_used", "repetitive_praise_used",
    "copy_paste_reply_used", "mass_commenting_context", "engagement_pod_context",
    "sensitive_trait_inference_used", "sensitive_relationship_profiling_used",
    "political_microtargeting_used", "synthetic_conversation_farming_used",
])
def test_cp86_growth_safety_signals_reject_engagement(flag):
    item = compose_outbound_candidate(contract(), radar_candidate(), proposal(**{flag: True}))
    assert item.decision == "REJECT_GROWTH_SAFETY"
    assert item.contribution_text is None
    assert item.manual_action_packet is None
    assert item.external_write_attempted is False


def test_cp86_exact_target_binding_blocks_broad_outbound():
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_EXACT_TARGET_MISMATCH"):
        compose_outbound_candidate(contract(), radar_candidate(), proposal(target_ref="some-other-thread"))


def test_cp86_source_binding_and_provenance_fail_closed():
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_SOURCE_BINDING_MISMATCH"):
        compose_outbound_candidate(contract(), radar_candidate(), proposal(source_url="synthetic://threads/conversation/other"))
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_PROVENANCE_NOT_ALLOWED_FOR_ROUTE"):
        compose_outbound_candidate(
            contract(), radar_candidate("FACEBOOK_PAGE"),
            proposal("FACEBOOK_PAGE", provenance_kind="OFFLINE_API_FIXTURE", source_url="https://example.org/facebook/fixture"),
        )


def test_cp86_good_question_requires_concrete_question():
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_GOOD_QUESTION_MUST_BE_CONCRETE_QUESTION"):
        compose_outbound_candidate(contract(), radar_candidate(), proposal(composer_mode="GOOD_QUESTION", contribution_text="Aceasta nu este o întrebare"))


def test_cp86_batch_is_idempotent_and_conflicting_same_target_fails_closed():
    c = contract()
    r = radar_candidate()
    p = proposal()
    assert len(process_batch(c, [(r, p), (r, p)])) == 1
    changed = proposal(contribution_text="Altă formulare material diferită, pe aceeași țintă.")
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_CONFLICTING_DUPLICATE_TARGET"):
        process_batch(c, [(r, p), (r, changed)])


@pytest.mark.parametrize("mutator,reason", [
    (lambda p: p.__setitem__("global_kill_switch", "DISENGAGED"), "HOLD_CP86_KILL_SWITCH_NOT_ENGAGED"),
    (lambda p: p["authority"].__setitem__("external_write_allowed", True), "HOLD_CP86_LIVE_AUTHORITY_DRIFT"),
    (lambda p: p["growth_safety"].__setitem__("mass_commenting_forbidden", False), "HOLD_CP86_GROWTH_SAFETY_WEAKENED"),
    (lambda p: p["candidate_input"].__setitem__("human_review_required", False), "HOLD_CP86_CANDIDATE_SAFETY_WEAKENED"),
    (lambda p: p["outbound_routes"][0].__setitem__("specific_target_required", False), "HOLD_CP86_BROAD_OUTBOUND_FORBIDDEN"),
    (lambda p: p["outbound_routes"][0].__setitem__("automation_mode", "DRY_RUN_API_CANDIDATE"), "HOLD_CP86_MANUAL_PACKET_REQUIRED"),
])
def test_cp86_policy_weakening_fails_closed(mutator, reason):
    p = copy.deepcopy(load_policy())
    mutator(p)
    with pytest.raises(OutboundEngagementHold, match=reason):
        validate_policy(p)


def test_cp86_unknown_platform_and_metric_fabrication_fail_closed():
    unknown = replace(radar_candidate(), platform="LINKEDIN")
    with pytest.raises(OutboundEngagementHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        compose_outbound_candidate(contract(), unknown, proposal())
    p = copy.deepcopy(load_policy())
    p["unknown_external_metric_value"] = 0
    with pytest.raises(OutboundEngagementHold, match="HOLD_CP86_UNKNOWN_METRIC_DRIFT"):
        validate_policy(p)
