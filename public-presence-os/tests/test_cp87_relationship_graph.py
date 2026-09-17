import copy
import json
from pathlib import Path

import pytest

from public_presence_os.relationship_graph import (
    EDGE_TYPES,
    InteractionEvent,
    RelationshipGraphHold,
    RelationshipGraphState,
    apply_interaction,
    compile_relationship_graph,
    process_batch,
    validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "relationship_graph_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def contract():
    return compile_relationship_graph(load_policy())


def event(**overrides):
    base = dict(
        platform="THREADS",
        source_public_id="@our_public_profile",
        peer_public_id="@public_peer",
        interaction_kind="replied_to",
        conversation_ref="threads-conversation-001",
        content_ref="threads-post-001",
        topic="finantare europeana",
        observed_at_utc="2026-09-17T03:00:00Z",
        quality_score=80,
        provenance_ref="fixture:threads:interaction:001",
    )
    base.update(overrides)
    return InteractionEvent(**base)


def test_cp87_contract_keeps_cp58_and_zero_live_authority():
    c = contract()
    assert c.checkpoint == "CP87"
    assert c.parent_activation_checkpoint == "CP86"
    assert c.parent_control_checkpoint == "CP58"
    assert c.next_unit == "CP88_AMPLIFICATION_ENGINE"
    assert c.global_kill_switch_engaged is True
    assert c.continuity_context_only is True
    assert c.sensitive_trait_inference_allowed is False
    assert c.sensitive_relationship_profiling_allowed is False
    assert c.political_microtargeting_allowed is False
    assert c.automated_targeting_allowed is False
    assert c.posting_authority is False
    assert c.external_write_allowed is False
    assert c.network_allowed is False
    assert c.live_probe_allowed is False
    assert c.external_metrics == "UNKNOWN"


def test_cp87_stores_only_canonical_public_nodes_and_edges():
    state = RelationshipGraphState()
    result = apply_interaction(contract(), state, event())
    assert len(state.nodes) == 4
    assert {n.node_type for n in state.nodes.values()} == {"public_account", "conversation", "content"}
    assert set(result.edge_types_present) == {"prior_useful_exchange", "replied_to", "shared_topic"}
    assert set(result.edge_types_present).issubset(set(EDGE_TYPES))
    assert result.external_write_allowed is False
    assert result.external_write_attempted is False
    assert result.network_fetch_performed is False
    assert result.posting_authority is False
    assert result.automated_targeting_allowed is False


def test_cp87_repeated_public_interaction_derives_recurring_edge_and_score():
    c = contract()
    state = RelationshipGraphState()
    first = apply_interaction(c, state, event())
    second = apply_interaction(
        c,
        state,
        event(
            interaction_kind="mentioned",
            content_ref="threads-post-002",
            observed_at_utc="2026-09-17T03:10:00Z",
            quality_score=90,
            provenance_ref="fixture:threads:interaction:002",
        ),
    )
    assert first.interaction_count == 1
    assert second.interaction_count == 2
    assert "recurring_interaction" in second.edge_types_present
    summary = state.relationships[second.pair_id]
    assert summary.quality_mean == 85.0
    assert summary.relationship_score == 72.0
    assert summary.score_basis == "REPEATED_PUBLIC_INTERACTION_QUALITY_ONLY"
    assert summary.permitted_use == "CONTINUITY_CONTEXT_ONLY_NOT_ACTION_AUTHORITY"


def test_cp87_exact_replay_is_idempotent():
    c = contract()
    state = RelationshipGraphState()
    first = apply_interaction(c, state, event())
    before = state.to_dict()
    replay = apply_interaction(c, state, event())
    assert replay.idempotent_replay is True
    assert replay.event_id == first.event_id
    assert replay.state_hash == first.state_hash
    assert state.to_dict() == before
    assert state.relationships[first.pair_id].interaction_count == 1


def test_cp87_conflicting_duplicate_provenance_fails_closed():
    c = contract()
    state = RelationshipGraphState()
    apply_interaction(c, state, event())
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_CONFLICTING_DUPLICATE_PROVENANCE"):
        apply_interaction(c, state, event(quality_score=81))


@pytest.mark.parametrize("flag,reason", [
    ("sensitive_trait_data_present", "HOLD_CP87_SENSITIVE_TRAIT_DATA_FORBIDDEN"),
    ("sensitive_relationship_profiling_requested", "HOLD_CP87_SENSITIVE_RELATIONSHIP_PROFILING_FORBIDDEN"),
    ("political_microtargeting_requested", "HOLD_CP87_POLITICAL_MICROTARGETING_FORBIDDEN"),
])
def test_cp87_sensitive_or_microtargeting_signals_fail_closed(flag, reason):
    c = contract()
    state = RelationshipGraphState()
    with pytest.raises(RelationshipGraphHold, match=reason):
        apply_interaction(c, state, event(**{flag: True}))
    assert state.to_dict() == {"nodes": {}, "edges": {}, "relationships": {}, "receipts": {}}


def test_cp87_arbitrary_extra_metadata_is_forbidden():
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_EXTRA_METADATA_FORBIDDEN"):
        apply_interaction(
            contract(),
            RelationshipGraphState(),
            event(extra_metadata={"political_ideology": "inferred"}),
        )


def test_cp87_requires_public_visibility_and_public_evidence():
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_PUBLIC_EVIDENCE_REQUIRED"):
        apply_interaction(contract(), RelationshipGraphState(), event(public_visibility_confirmed=False))
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_PUBLIC_EVIDENCE_REQUIRED"):
        apply_interaction(contract(), RelationshipGraphState(), event(evidence_is_public=False))


def test_cp87_unknown_platform_and_noncanonical_interaction_fail_closed():
    with pytest.raises(RelationshipGraphHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        apply_interaction(contract(), RelationshipGraphState(), event(platform="LINKEDIN"))
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_INTERACTION_KIND_INVALID"):
        apply_interaction(contract(), RelationshipGraphState(), event(interaction_kind="followed"))


def test_cp87_score_is_quality_and_repetition_only_not_demographics():
    c = contract()
    state = RelationshipGraphState()
    results = process_batch(
        c,
        state,
        (
            event(quality_score=50, provenance_ref="fixture:1"),
            event(quality_score=50, provenance_ref="fixture:2", content_ref="post-2"),
            event(quality_score=50, provenance_ref="fixture:3", content_ref="post-3"),
        ),
    )
    assert results[-1].relationship_score == 48.0
    snapshot = json.dumps(state.to_dict(), sort_keys=True)
    for forbidden in ("political_ideology", "health", "religion", "sexuality", "ethnicity", "demographic"):
        assert forbidden not in snapshot.lower()


def test_cp87_policy_weakening_fails_closed():
    p = copy.deepcopy(load_policy())
    p["privacy"]["sensitive_trait_inference_forbidden"] = False
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_PRIVACY_POLICY_WEAKENED"):
        validate_policy(p)
    p = copy.deepcopy(load_policy())
    p["authority"]["external_write_allowed"] = True
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_LIVE_AUTHORITY_DRIFT"):
        validate_policy(p)
    p = copy.deepcopy(load_policy())
    p["global_kill_switch"] = "DISENGAGED"
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_KILL_SWITCH_NOT_ENGAGED"):
        validate_policy(p)


def test_cp87_unknown_external_metrics_cannot_be_fabricated():
    p = copy.deepcopy(load_policy())
    p["unknown_external_metric_value"] = 0
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_UNKNOWN_METRIC_DRIFT"):
        validate_policy(p)


def test_cp87_batch_limit_is_hard_ceiling():
    c = contract()
    too_many = tuple(
        event(provenance_ref=f"fixture:{i}", content_ref=f"post-{i}")
        for i in range(c.max_batch + 1)
    )
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_BATCH_LIMIT_EXCEEDED"):
        process_batch(c, RelationshipGraphState(), too_many)


def test_cp87_self_relationship_fails_closed():
    with pytest.raises(RelationshipGraphHold, match="HOLD_CP87_SELF_RELATIONSHIP_FORBIDDEN"):
        apply_interaction(
            contract(),
            RelationshipGraphState(),
            event(peer_public_id="@our_public_profile"),
        )
