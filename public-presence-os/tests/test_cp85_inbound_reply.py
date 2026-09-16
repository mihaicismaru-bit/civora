import copy
import json
from pathlib import Path

import pytest

from public_presence_os.growth_capability_matrix import compile_growth_capability_matrix
from public_presence_os.inbound_reply import (
    CLASSIFICATIONS,
    SURFACE_KINDS,
    InboundObservation,
    InboundReplyHold,
    classify_inbound,
    compile_inbound_reply_engine,
    process_batch,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "inbound_reply_policy.json"
CP83_POLICY_PATH = ROOT / "config" / "growth_capability_matrix_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def contract():
    cp83 = compile_growth_capability_matrix(
        json.loads(CP83_POLICY_PATH.read_text(encoding="utf-8"))
    )
    return compile_inbound_reply_engine(load_policy(), cp83)


def observation(**overrides):
    base = dict(
        platform="INSTAGRAM_PROFESSIONAL",
        surface_kind="OWN_CONTENT_COMMENT",
        provenance_kind="SYNTHETIC_FIXTURE",
        provenance_ref="fixture:ig:comment:001",
        inbound_ref="ig-comment-001",
        conversation_ref="ig-thread-001",
        own_content_ref="ig-own-post-001",
        source_url="synthetic://instagram/comment/001",
        author_public_id="@public_account",
        text="Care este termenul exact pentru înscriere?",
        observed_at_utc="2026-09-15T10:30:00Z",
        own_content_published_at_utc="2026-09-15T09:00:00Z",
        evidence_tags=("QUESTION_SIGNAL",),
        response_evidence=("Înscrierea se încheie la 30 septembrie, ora 23:59.",),
    )
    base.update(overrides)
    return InboundObservation(**base)


def test_cp85_contract_is_bound_to_cp83_and_keeps_cp58_live_hold():
    c = contract()
    assert c.checkpoint == "CP85"
    assert c.parent_activation_checkpoint == "CP84"
    assert c.parent_capability_checkpoint == "CP83"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP86_OUTBOUND_VALUE_ADD_ENGAGEMENT_ENGINE"
    assert c.global_kill_switch_engaged is True
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
    assert len(c.routes) == 9
    assert {(r.platform, r.surface_kind) for r in c.routes} == {
        (platform, surface) for platform in (
            "FACEBOOK_PAGE", "INSTAGRAM_PROFESSIONAL", "THREADS"
        ) for surface in SURFACE_KINDS
    }


def test_cp85_instagram_question_builds_fact_bound_draft_human_review_only():
    candidate = classify_inbound(
        contract(), observation(), now_utc="2026-09-15T11:00:00Z"
    )
    assert candidate.classification == "QUESTION"
    assert candidate.sla_label == "HOT_0_2H"
    assert candidate.decision == "DRAFT_READY_HUMAN_REVIEW"
    assert candidate.next_state == "DRAFT_READY_HUMAN_REVIEW"
    assert candidate.response_candidate == (
        "Pe scurt: Înscrierea se încheie la 30 septembrie, ora 23:59."
    )
    assert candidate.human_review_required is True
    assert candidate.posting_authority is False
    assert candidate.external_write_allowed is False
    assert candidate.external_write_attempted is False
    assert candidate.network_fetch_performed is False
    assert candidate.external_metrics == "UNKNOWN"


@pytest.mark.parametrize(
    "tags,expected",
    [
        (("QUESTION_SIGNAL",), "QUESTION"),
        (("SUBSTANTIVE_AGREEMENT_SIGNAL",), "AGREEMENT_WITH_SUBSTANCE"),
        (("CORRECTION_SIGNAL",), "CORRECTION"),
        (("COUNTERPOINT_SIGNAL",), "COUNTERPOINT"),
        (("PUBLIC_EXPERTISE_SIGNAL",), "EXPERT_LEAD"),
        (("COMMUNITY_RELEVANCE_SIGNAL",), "COMMUNITY_SIGNAL"),
        (("LOW_VALUE_SIGNAL",), "LOW_VALUE"),
        (("SPAM_SIGNAL",), "ABUSE_SPAM"),
    ],
)
def test_cp85_exact_canonical_classifications(tags, expected):
    assert expected in CLASSIFICATIONS
    candidate = classify_inbound(
        contract(),
        observation(
            evidence_tags=tags,
            response_evidence=("Context verificat, relevant pentru răspuns.",),
        ),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.classification == expected


def test_cp85_precedence_is_fail_safe_abuse_then_correction_then_question():
    c = contract()
    abuse = classify_inbound(
        c,
        observation(evidence_tags=("QUESTION_SIGNAL", "SPAM_SIGNAL")),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert abuse.classification == "ABUSE_SPAM"
    correction = classify_inbound(
        c,
        observation(
            inbound_ref="ig-comment-002",
            evidence_tags=("QUESTION_SIGNAL", "CORRECTION_SIGNAL"),
        ),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert correction.classification == "CORRECTION"


def test_cp85_low_value_and_abuse_are_terminal_no_reply():
    c = contract()
    low = classify_inbound(
        c,
        observation(evidence_tags=("LOW_VALUE_SIGNAL",), response_evidence=()),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert low.decision == "NO_REPLY_LOW_VALUE"
    assert low.next_state == "NO_REPLY_LOW_VALUE"
    assert low.response_candidate is None

    abuse = classify_inbound(
        c,
        observation(
            inbound_ref="ig-comment-abuse",
            evidence_tags=("ABUSE_SIGNAL",),
            response_evidence=(),
        ),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert abuse.decision == "NO_REPLY_ABUSE_SPAM"
    assert abuse.next_state == "NO_REPLY_ABUSE_SPAM"
    assert abuse.response_candidate is None


def test_cp85_no_fact_bound_context_means_hold_not_hallucinated_reply():
    candidate = classify_inbound(
        contract(),
        observation(response_evidence=()),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.decision == "HOLD_EDITORIAL_CONTEXT_REQUIRED"
    assert candidate.next_state == "HOLD_EDITORIAL_CONTEXT_REQUIRED"
    assert candidate.response_candidate is None
    assert "NO_FACT_BOUND_RESPONSE_EVIDENCE" in candidate.decision_reasons


def test_cp85_facebook_inbound_remains_capability_hold_not_fake_automation():
    candidate = classify_inbound(
        contract(),
        observation(
            platform="FACEBOOK_PAGE",
            provenance_ref="fixture:fb:comment:001",
            inbound_ref="fb-comment-001",
            conversation_ref="fb-thread-001",
            own_content_ref="fb-own-post-001",
            source_url="synthetic://facebook/comment/001",
        ),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.cp83_classification == "HOLD_LIVE_PERMISSION"
    assert candidate.automation_ingest_eligible is False
    assert candidate.decision == "NO_REPLY_CAPABILITY_HOLD"
    assert candidate.next_state == "NO_REPLY_CAPABILITY_HOLD"
    assert candidate.response_candidate is None
    assert "HOLD_CAPABILITY_UNVERIFIED" in candidate.blockers


def test_cp85_facebook_mention_is_manual_only_and_never_claimed_supported():
    candidate = classify_inbound(
        contract(),
        observation(
            platform="FACEBOOK_PAGE",
            surface_kind="ACCOUNT_MENTION",
            provenance_ref="fixture:fb:mention:001",
            inbound_ref="fb-mention-001",
            conversation_ref="fb-mention-thread-001",
            own_content_ref="account-mention",
            source_url="synthetic://facebook/mention/001",
        ),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.capability == "MENTION_DISCOVERY"
    assert candidate.cp83_classification == "MANUAL_ONLY"
    assert candidate.automation_ingest_eligible is False
    assert candidate.decision == "NO_REPLY_CAPABILITY_HOLD"


def test_cp85_threads_and_instagram_mentions_bind_to_verified_offline_contract():
    c = contract()
    for platform in ("INSTAGRAM_PROFESSIONAL", "THREADS"):
        candidate = classify_inbound(
            c,
            observation(
                platform=platform,
                surface_kind="ACCOUNT_MENTION",
                provenance_ref=f"fixture:{platform}:mention:001",
                inbound_ref=f"{platform}-mention-001",
                conversation_ref=f"{platform}-mention-thread-001",
                own_content_ref="account-mention",
                source_url=f"synthetic://{platform.lower()}/mention/001",
            ),
            now_utc="2026-09-15T11:00:00Z",
        )
        assert candidate.capability == "MENTION_DISCOVERY"
        assert candidate.cp83_classification == "PASS_OFFLINE_CONTRACT"
        assert candidate.automation_ingest_eligible is True
        assert candidate.decision == "DRAFT_READY_HUMAN_REVIEW"
        assert candidate.posting_authority is False


@pytest.mark.parametrize(
    "now,expected",
    [
        ("2026-09-15T11:00:00Z", "HOT_0_2H"),
        ("2026-09-15T13:00:00Z", "PRIORITY_2_4H"),
        ("2026-09-15T13:00:01Z", "STANDARD_AFTER_4H"),
    ],
)
def test_cp85_sla_edges_are_2h_and_4h_hard_boundaries(now, expected):
    candidate = classify_inbound(contract(), observation(), now_utc=now)
    assert candidate.sla_label == expected


def test_cp85_identical_batch_duplicates_dedupe_and_conflicts_fail_closed():
    c = contract()
    a = observation()
    assert len(process_batch(c, [a, a], now_utc="2026-09-15T11:00:00Z")) == 1
    b = observation(text="Conflicting payload under the same inbound identity.")
    with pytest.raises(InboundReplyHold, match="HOLD_CP85_CONFLICTING_DUPLICATE"):
        process_batch(c, [a, b], now_utc="2026-09-15T11:00:00Z")


def test_cp85_terminal_no_reply_state_cannot_resurrect():
    candidate = classify_inbound(
        contract(),
        observation(prior_state="NO_REPLY_LOW_VALUE"),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.decision == "NO_REPLY_TERMINAL_ALREADY_CLOSED"
    assert candidate.next_state == "NO_REPLY_TERMINAL_ALREADY_CLOSED"
    assert candidate.response_candidate is None
    assert candidate.automation_ingest_eligible is False


@pytest.mark.parametrize(
    "flag",
    [
        "sensitive_trait_inference_used",
        "sensitive_relationship_profiling_used",
        "political_microtargeting_used",
        "synthetic_conversation_farming_used",
    ],
)
def test_cp85_prohibited_growth_safety_signals_force_no_reply(flag):
    candidate = classify_inbound(
        contract(),
        observation(**{flag: True}),
        now_utc="2026-09-15T11:00:00Z",
    )
    assert candidate.decision == "NO_REPLY_SAFETY"
    assert candidate.next_state == "NO_REPLY_ABUSE_SPAM"
    assert candidate.response_candidate is None
    assert candidate.posting_authority is False


def test_cp85_unknown_platform_surface_or_evidence_fails_closed():
    c = contract()
    with pytest.raises(InboundReplyHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        classify_inbound(
            c, observation(platform="LINKEDIN"), now_utc="2026-09-15T11:00:00Z"
        )
    with pytest.raises(InboundReplyHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        classify_inbound(
            c, observation(surface_kind="DIRECT_MESSAGE"), now_utc="2026-09-15T11:00:00Z"
        )
    with pytest.raises(InboundReplyHold, match="HOLD_CP85_UNKNOWN_CLASSIFICATION_EVIDENCE"):
        classify_inbound(
            c,
            observation(evidence_tags=("FOLLOWER_COUNT_SIGNAL",)),
            now_utc="2026-09-15T11:00:00Z",
        )


def test_cp85_provenance_gate_prevents_false_api_support():
    c = contract()
    with pytest.raises(InboundReplyHold, match="HOLD_CP85_PROVENANCE_NOT_ALLOWED_FOR_ROUTE"):
        classify_inbound(
            c,
            observation(
                platform="FACEBOOK_PAGE",
                provenance_kind="OFFLINE_API_FIXTURE",
                source_url="https://example.org/fb/offline-api-fixture",
            ),
            now_utc="2026-09-15T11:00:00Z",
        )


def test_cp85_public_observation_requires_https_and_synthetic_requires_synthetic_url():
    c = contract()
    with pytest.raises(InboundReplyHold, match="HOLD_CP85_PUBLIC_SOURCE_HTTPS_REQUIRED"):
        classify_inbound(
            c,
            observation(
                provenance_kind="PUBLIC_URL_OBSERVATION",
                source_url="http://example.org/insecure",
            ),
            now_utc="2026-09-15T11:00:00Z",
        )
    with pytest.raises(InboundReplyHold, match="HOLD_CP85_SYNTHETIC_FIXTURE_URL_REQUIRED"):
        classify_inbound(
            c,
            observation(source_url="https://example.org/not-synthetic"),
            now_utc="2026-09-15T11:00:00Z",
        )


def test_cp85_batch_prioritizes_hot_drafts_without_creating_write_authority():
    c = contract()
    hot = observation(inbound_ref="hot", conversation_ref="hot")
    old = observation(
        inbound_ref="old",
        conversation_ref="old",
        own_content_published_at_utc="2026-09-14T09:00:00Z",
    )
    ranked = process_batch(c, [old, hot], now_utc="2026-09-15T11:00:00Z")
    assert ranked[0].inbound_ref == "hot"
    assert all(
        item.posting_authority is False
        and item.external_write_allowed is False
        and item.external_write_attempted is False
        for item in ranked
    )


@pytest.mark.parametrize(
    "mutator,reason",
    [
        (
            lambda p: p.__setitem__("global_kill_switch", "DISENGAGED"),
            "HOLD_CP85_KILL_SWITCH_NOT_ENGAGED",
        ),
        (
            lambda p: p["authority"].__setitem__("network_allowed", True),
            "HOLD_CP85_LIVE_AUTHORITY_DRIFT",
        ),
        (
            lambda p: p["growth_safety"].__setitem__("mass_commenting_forbidden", False),
            "HOLD_CP85_GROWTH_SAFETY_WEAKENED",
        ),
        (
            lambda p: p["response"].__setitem__("human_review_required", False),
            "HOLD_CP85_RESPONSE_SAFETY_WEAKENED",
        ),
        (
            lambda p: p["ingress_routes"][0].__setitem__("automation_ingest_eligible", True),
            "HOLD_CP85_UNVERIFIED_ROUTE_CANNOT_AUTOMATE",
        ),
    ],
)
def test_cp85_policy_weakening_fails_closed(mutator, reason):
    policy = copy.deepcopy(load_policy())
    mutator(policy)
    with pytest.raises(InboundReplyHold, match=reason):
        validate_policy(policy)
