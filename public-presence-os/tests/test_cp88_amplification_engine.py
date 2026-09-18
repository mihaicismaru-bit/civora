import copy
import json
from pathlib import Path

import pytest

from public_presence_os.amplification_engine import (
    AmplificationCandidate,
    AmplificationHold,
    AmplificationState,
    compile_amplification_engine,
    evaluate_candidate,
    process_batch,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "amplification_engine_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def contract():
    return compile_amplification_engine(load_policy())


def candidate(**overrides):
    base = dict(
        platform="THREADS",
        candidate_kind="OWN_POST",
        source_ref="threads-post-100",
        conversation_ref="threads-conversation-100",
        topic="finantare europeana pentru IMM",
        observed_at_utc="2026-09-17T18:00:00Z",
        provenance_ref="fixture:cp88:001",
        relevance_score=90,
        substance_score=86,
        novelty_score=78,
        followup_value_score=84,
        explanation_value_score=70,
        material_delta_score=80,
        thread_quality_score=0,
        conversation_depth=0,
        correction_need_score=0,
        thread_takeaway="",
        material_new_information=True,
        source_is_public=True,
    )
    base.update(overrides)
    return AmplificationCandidate(**base)


def test_cp88_contract_keeps_cp58_and_zero_live_authority():
    c = contract()
    assert c.checkpoint == "CP88"
    assert c.parent_activation_checkpoint == "CP87"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP89_GROWTH_ANALYTICS_VIRALITY_LEARNING"
    assert c.global_kill_switch_engaged is True
    assert c.posting_authority is False
    assert c.external_write_allowed is False
    assert c.network_allowed is False
    assert c.live_probe_allowed is False
    assert c.oauth_allowed is False
    assert c.account_connection_allowed is False
    assert c.control_plane_promoted is False
    assert c.deploy_allowed is False
    assert c.paid_service_allowed is False
    assert c.external_metrics == "UNKNOWN"


def test_cp88_own_post_selects_distinct_second_post_when_material():
    state = AmplificationState()
    result = evaluate_candidate(contract(), state, candidate())
    assert result.decision_state == "SELECTED_OFFLINE"
    assert result.recommended_action == "SECOND_POST"
    assert result.external_write_allowed is False
    assert result.external_write_attempted is False
    assert result.network_fetch_performed is False
    assert result.posting_authority is False
    assert result.automated_targeting_allowed is False


def test_cp88_strong_comment_thread_becomes_future_content_idea():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            candidate_kind="COMMENT_THREAD",
            source_ref="thread-comment-chain-1",
            conversation_ref="conversation-1",
            provenance_ref="fixture:thread:1",
            thread_quality_score=88,
            conversation_depth=6,
            thread_takeaway="IMM-urile confundă frecvent eligibilitatea cu punctajul; merită un explainer cu exemple.",
            explanation_value_score=72,
        ),
    )
    assert result.decision_state == "SELECTED_OFFLINE"
    assert result.recommended_action == "CONTENT_IDEA"
    assert result.content_idea is not None
    assert result.content_idea.status == "FUTURE_CONTENT_IDEA_OFFLINE_ONLY"
    assert "eligibilitatea" in result.content_idea.seed


def test_cp88_strong_thread_can_select_explainer():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            candidate_kind="COMMENT_THREAD",
            provenance_ref="fixture:thread:2",
            source_ref="thread-comment-chain-2",
            conversation_ref="conversation-2",
            thread_quality_score=90,
            conversation_depth=8,
            thread_takeaway="Explică diferența dintre grant, ajutor de minimis și intensitatea ajutorului.",
            explanation_value_score=92,
            material_delta_score=85,
        ),
    )
    assert result.recommended_action == "EXPLAINER"
    assert result.content_idea is not None


def test_cp88_material_correction_is_prioritized():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            provenance_ref="fixture:correction:1",
            correction_need_score=95,
            material_delta_score=90,
            novelty_score=60,
            followup_value_score=60,
        ),
    )
    assert result.decision_state == "SELECTED_OFFLINE"
    assert result.recommended_action == "CORRECTION"


def test_cp88_quote_repost_never_becomes_api_write_and_threads_yields_manual_packet():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            candidate_kind="PUBLIC_CONVERSATION",
            source_ref="threads-public-post-1",
            provenance_ref="fixture:quote:threads",
            quote_repost_requested=True,
            rights_context_passed=True,
            context_integrity_passed=True,
        ),
    )
    assert result.decision_state == "MANUAL_ACTION_PACKET"
    assert result.recommended_action == "QUOTE_REPOST"
    packet = result.manual_action_packet
    assert packet is not None
    assert packet.capability_classification == "MANUAL_ONLY"
    assert packet.automation_mode == "MANUAL_ACTION_PACKET"
    assert packet.execution_status == "MANUAL_ONLY_NOT_AUTHORITY"
    assert packet.external_write_attempted is False
    assert packet.network_attempted is False


def test_cp88_instagram_quote_repost_is_manual_packet_with_capability_hold():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            platform="INSTAGRAM_PROFESSIONAL",
            candidate_kind="PUBLIC_CONVERSATION",
            source_ref="ig-public-media-1",
            provenance_ref="fixture:quote:ig",
            quote_repost_requested=True,
            rights_context_passed=True,
            context_integrity_passed=True,
        ),
    )
    packet = result.manual_action_packet
    assert packet is not None
    assert packet.capability_classification == "UNSUPPORTED"
    assert packet.live_gate == "HOLD_CAPABILITY_UNVERIFIED"
    assert result.external_write_attempted is False


def test_cp88_quote_repost_requires_rights_and_context_checks():
    with pytest.raises(AmplificationHold, match="HOLD_CP88_QUOTE_REPOST_RIGHTS_CONTEXT_REQUIRED"):
        evaluate_candidate(
            contract(),
            AmplificationState(),
            candidate(
                candidate_kind="PUBLIC_CONVERSATION",
                provenance_ref="fixture:quote:no-rights",
                quote_repost_requested=True,
                rights_context_passed=False,
                context_integrity_passed=True,
            ),
        )


def test_cp88_weak_or_nonmaterial_candidate_becomes_no_action():
    result = evaluate_candidate(
        contract(),
        AmplificationState(),
        candidate(
            provenance_ref="fixture:weak:1",
            relevance_score=45,
            substance_score=40,
            novelty_score=30,
            followup_value_score=40,
            explanation_value_score=30,
            material_delta_score=20,
        ),
    )
    assert result.decision_state == "NO_ACTION"
    assert result.recommended_action is None
    assert result.reason == "MATERIAL_DELTA_BELOW_THRESHOLD"


def test_cp88_exact_replay_is_idempotent_and_does_not_duplicate_state():
    c = contract()
    state = AmplificationState()
    first = evaluate_candidate(c, state, candidate())
    before = state.to_dict()
    replay = evaluate_candidate(c, state, candidate())
    assert replay.idempotent_replay is True
    assert replay.event_id == first.event_id
    assert state.to_dict() == before


def test_cp88_conflicting_duplicate_provenance_fails_closed():
    c = contract()
    state = AmplificationState()
    evaluate_candidate(c, state, candidate())
    with pytest.raises(AmplificationHold, match="HOLD_CP88_CONFLICTING_DUPLICATE_PROVENANCE"):
        evaluate_candidate(c, state, candidate(novelty_score=79))


def test_cp88_repetitive_self_amplification_is_blocked_across_distinct_receipts():
    c = contract()
    state = AmplificationState()
    evaluate_candidate(c, state, candidate(provenance_ref="fixture:repeat:1"))
    with pytest.raises(AmplificationHold, match="HOLD_CP88_DUPLICATE_OR_REPETITIVE_AMPLIFICATION"):
        evaluate_candidate(c, state, candidate(provenance_ref="fixture:repeat:2"))


def test_cp88_duplicate_thread_idea_is_blocked():
    c = contract()
    state = AmplificationState()
    base = dict(
        candidate_kind="COMMENT_THREAD",
        source_ref="thread-source",
        conversation_ref="thread-conversation",
        thread_quality_score=90,
        conversation_depth=5,
        explanation_value_score=70,
        thread_takeaway="Aceeași idee utilă pentru un articol viitor.",
    )
    evaluate_candidate(c, state, candidate(provenance_ref="fixture:idea:1", **base))
    with pytest.raises(AmplificationHold, match="HOLD_CP88_DUPLICATE_CONTENT_IDEA"):
        evaluate_candidate(
            c,
            state,
            candidate(
                provenance_ref="fixture:idea:2",
                source_ref="different-thread-source",
                conversation_ref="different-thread-conversation",
                **{k: v for k, v in base.items() if k not in {"source_ref", "conversation_ref"}},
            ),
        )


@pytest.mark.parametrize("flag,reason", [
    ("sensitive_trait_data_present", "HOLD_CP88_SENSITIVE_TRAIT_SIGNAL_FORBIDDEN"),
    ("sensitive_trait_inference_requested", "HOLD_CP88_SENSITIVE_TRAIT_SIGNAL_FORBIDDEN"),
    ("sensitive_relationship_profiling_requested", "HOLD_CP88_SENSITIVE_RELATIONSHIP_PROFILING_FORBIDDEN"),
    ("political_microtargeting_requested", "HOLD_CP88_POLITICAL_MICROTARGETING_FORBIDDEN"),
    ("synthetic_conversation_farming_requested", "HOLD_CP88_SYNTHETIC_CONVERSATION_FARMING_FORBIDDEN"),
    ("conflict_fabrication_requested", "HOLD_CP88_CONFLICT_FABRICATION_FORBIDDEN"),
])
def test_cp88_forbidden_growth_signals_fail_closed(flag, reason):
    with pytest.raises(AmplificationHold, match=reason):
        evaluate_candidate(
            contract(),
            AmplificationState(),
            candidate(provenance_ref=f"fixture:forbidden:{flag}", **{flag: True}),
        )


def test_cp88_unknown_platform_fails_closed_as_capability_unverified():
    with pytest.raises(AmplificationHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        evaluate_candidate(
            contract(),
            AmplificationState(),
            candidate(platform="LINKEDIN", provenance_ref="fixture:linkedin"),
        )


def test_cp88_policy_weakening_fails_closed():
    p = copy.deepcopy(load_policy())
    p["safety"]["repetitive_self_amplification_forbidden"] = False
    with pytest.raises(AmplificationHold, match="HOLD_CP88_SAFETY_POLICY_WEAKENED"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["authority"]["external_write_allowed"] = True
    with pytest.raises(AmplificationHold, match="HOLD_CP88_LIVE_AUTHORITY_DRIFT"):
        validate_policy(p)

    p = copy.deepcopy(load_policy())
    p["global_kill_switch"] = "DISENGAGED"
    with pytest.raises(AmplificationHold, match="HOLD_CP88_KILL_SWITCH_NOT_ENGAGED"):
        validate_policy(p)


def test_cp88_quote_repost_baseline_cannot_be_upgraded_without_new_verified_capability():
    p = copy.deepcopy(load_policy())
    p["quote_repost_capability_baseline"]["THREADS"]["classification"] = "PASS_OFFLINE_CONTRACT"
    with pytest.raises(AmplificationHold, match="HOLD_CP88_QUOTE_REPOST_BASELINE_DRIFT"):
        validate_policy(p)


def test_cp88_unknown_external_metrics_cannot_be_fabricated():
    p = copy.deepcopy(load_policy())
    p["unknown_external_metric_value"] = 0
    with pytest.raises(AmplificationHold, match="HOLD_CP88_UNKNOWN_METRIC_DRIFT"):
        validate_policy(p)


def test_cp88_batch_limit_is_hard_ceiling_and_batch_is_atomic_on_failure():
    c = contract()
    too_many = tuple(
        candidate(provenance_ref=f"fixture:batch:{i}", source_ref=f"source-{i}")
        for i in range(c.max_batch + 1)
    )
    with pytest.raises(AmplificationHold, match="HOLD_CP88_BATCH_LIMIT_EXCEEDED"):
        process_batch(c, AmplificationState(), too_many)

    state = AmplificationState()
    batch = (
        candidate(provenance_ref="fixture:atomic:1", source_ref="atomic-source-1"),
        candidate(
            provenance_ref="fixture:atomic:2",
            source_ref="atomic-source-2",
            sensitive_trait_inference_requested=True,
        ),
    )
    with pytest.raises(AmplificationHold):
        process_batch(c, state, batch)
    assert state.to_dict() == {
        "receipts": {},
        "source_action_fingerprints": [],
        "idea_fingerprints": [],
    }
