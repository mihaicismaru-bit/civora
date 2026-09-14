import copy
import json
from pathlib import Path

import pytest

from public_presence_os.growth_capability_matrix import (
    ACTIVE_PLATFORMS, CAPABILITY_KINDS, EXPECTED_ROWS, GrowthCapabilityMatrixHold,
    build_manual_action_packet, capability_lookup, compile_growth_capability_matrix, validate_policy,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "growth_capability_matrix_policy.json"


def load_policy():
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_cp83_exact_21_row_cartesian_matrix_and_control_hold():
    contract = compile_growth_capability_matrix(load_policy())
    assert len(contract.rows) == EXPECTED_ROWS == 21
    assert {(r.platform, r.capability) for r in contract.rows} == {(p, c) for p in ACTIVE_PLATFORMS for c in CAPABILITY_KINDS}
    assert contract.checkpoint == "CP83"
    assert contract.parent_activation_checkpoint == "CP82"
    assert contract.parent_control_checkpoint == "CP58"
    assert contract.next_unit == "CP84_ENGAGEMENT_RADAR"
    assert contract.global_kill_switch_engaged is True
    assert contract.account_connected is False
    assert contract.network_allowed is False
    assert contract.oauth_attempted is False
    assert contract.live_probe_allowed is False
    assert contract.external_write_allowed is False
    assert contract.publish_allowed is False
    assert contract.deploy_allowed is False
    assert contract.control_plane_promoted is False


def test_cp83_follow_is_manual_only_everywhere():
    contract = compile_growth_capability_matrix(load_policy())
    for platform in ACTIVE_PLATFORMS:
        row = capability_lookup(contract, platform, "FOLLOW")
        assert row.classification == "MANUAL_ONLY"
        assert row.automation_mode == "MANUAL_ACTION_PACKET"
        assert row.manual_action_packet is True
        assert row.broad_outbound_allowed is False


def test_cp83_arbitrary_meta_outbound_commenting_is_not_assumed():
    contract = compile_growth_capability_matrix(load_policy())
    fb = capability_lookup(contract, "FACEBOOK_PAGE", "OUTBOUND_COMMENT")
    ig = capability_lookup(contract, "INSTAGRAM_PROFESSIONAL", "OUTBOUND_COMMENT")
    th = capability_lookup(contract, "THREADS", "OUTBOUND_COMMENT")
    assert fb.classification == "MANUAL_ONLY"
    assert ig.classification == "MANUAL_ONLY"
    assert "HOLD_CAPABILITY_UNVERIFIED" in fb.blockers
    assert "HOLD_CAPABILITY_UNVERIFIED" in ig.blockers
    assert th.classification == "PASS_OFFLINE_CONTRACT"
    assert "specific readable post/reply" in th.scope
    assert "HOLD_LIVE_PERMISSION" in th.blockers
    assert all(r.broad_outbound_allowed is False for r in (fb, ig, th))


def test_cp83_unknown_capability_fails_closed():
    contract = compile_growth_capability_matrix(load_policy())
    with pytest.raises(GrowthCapabilityMatrixHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        capability_lookup(contract, "THREADS", "DIRECT_MESSAGE")
    with pytest.raises(GrowthCapabilityMatrixHold, match="HOLD_CAPABILITY_UNVERIFIED"):
        capability_lookup(contract, "LINKEDIN", "INBOUND_REPLY")


def test_cp83_unavailable_external_metrics_remain_unknown():
    contract = compile_growth_capability_matrix(load_policy())
    assert all(row.external_metrics == "UNKNOWN" for row in contract.rows)


def test_cp83_manual_action_packet_is_deterministic_and_zero_write():
    contract = compile_growth_capability_matrix(load_policy())
    a = build_manual_action_packet(contract, "INSTAGRAM_PROFESSIONAL", "OUTBOUND_COMMENT", "ctx-001")
    b = build_manual_action_packet(contract, "INSTAGRAM_PROFESSIONAL", "OUTBOUND_COMMENT", "ctx-001")
    assert a == b
    assert a["automation_attempted"] is False
    assert a["external_write_attempted"] is False
    assert a["requires_human_review"] is True
    assert a["kill_switch"] == "ENGAGED"
    assert len(a["packet_sha256"]) == 64


def test_cp83_manual_packet_rejected_for_api_candidate():
    contract = compile_growth_capability_matrix(load_policy())
    with pytest.raises(GrowthCapabilityMatrixHold, match="HOLD_CP83_MANUAL_PACKET_NOT_REQUIRED"):
        build_manual_action_packet(contract, "THREADS", "INBOUND_REPLY", "ctx-002")


@pytest.mark.parametrize("mutator,reason", [
    (lambda p: p.__setitem__("global_kill_switch", "DISENGAGED"), "HOLD_CP83_KILL_SWITCH_NOT_ENGAGED"),
    (lambda p: p["authority"].__setitem__("network_allowed", True), "HOLD_CP83_LIVE_AUTHORITY_DRIFT"),
    (lambda p: p["growth_safety"].__setitem__("mass_commenting_forbidden", False), "HOLD_CP83_GROWTH_SAFETY_WEAKENED"),
    (lambda p: p["capability_matrix"][0].__setitem__("broad_outbound_allowed", True), "HOLD_CP83_BROAD_OUTBOUND_FORBIDDEN"),
    (lambda p: p["capability_matrix"][0].__setitem__("external_metrics", 17), "HOLD_CP83_EXTERNAL_METRIC_FABRICATED"),
])
def test_cp83_policy_weakening_fails_closed(mutator, reason):
    policy = copy.deepcopy(load_policy())
    mutator(policy)
    with pytest.raises(GrowthCapabilityMatrixHold, match=reason):
        validate_policy(policy)
