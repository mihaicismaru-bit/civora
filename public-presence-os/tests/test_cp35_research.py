from __future__ import annotations
from hashlib import sha256
import json
import pytest

from public_presence_os.radar import RadarObservation, RadarSourceClass, RadarKind, materialize_signal
from public_presence_os.research import *

NOW="2026-09-06T01:00:00Z"
CAP="2026-09-06T01:05:00Z"


def h(text):
    return sha256(text.encode()).hexdigest()


def signal(source_class=RadarSourceClass.PRIMARY_PUBLIC, synthetic=False):
    url="synthetic://fixture/local" if synthetic else "https://example.org/news/1"
    return materialize_signal(RadarObservation(
        external_ref="item-1", source_url=url, source_class=source_class, kind=RadarKind.ARTICLE,
        observed_at_utc=NOW,title="Local update",excerpt="Short discovery excerpt",topic="transport",locality="Valcea",synthetic=synthetic
    ))


def ev(authority=EvidenceAuthority.PRIMARY_SOURCE,url="https://example.org/news/1",synthetic=False,eid="ev-1",captured=CAP):
    return ResearchEvidence(
        evidence_id=eid,source_url=url,authority=authority,kind=EvidenceKind.DETAIL_PAGE,
        captured_at_utc=captured,content_sha256=h(eid),synthetic=synthetic
    )


def test_primary_without_evidence_holds():
    p=build_research_packet(signal())
    assert p.research_status=="HOLD_PRIMARY_EVIDENCE"
    assert not p.evidence_bound and not p.scoring_input_ready
    assert "PRIMARY_DETAIL_BODY_OR_DOCUMENT" in p.evidence_requirements


def test_secondary_without_evidence_holds_for_confirmation():
    p=build_research_packet(signal(RadarSourceClass.SECONDARY_DISCOVERY))
    assert p.research_status=="HOLD_PRIMARY_CONFIRMATION"
    assert p.unresolved_questions[0]=="WHICH_PRIMARY_SOURCE_CONFIRMS_THIS_DISCOVERY_SIGNAL?"


def test_primary_matching_host_evidence_binds():
    p=build_research_packet(signal(),[ev(url="https://example.org/detail/abc")])
    assert p.research_status=="EVIDENCE_BOUND"
    assert p.evidence_bound and p.scoring_input_ready


def test_primary_other_host_does_not_bind():
    p=build_research_packet(signal(),[ev(url="https://other.example/detail/abc")])
    assert p.research_status=="HOLD_PRIMARY_EVIDENCE"


def test_secondary_can_bind_independent_primary():
    p=build_research_packet(signal(RadarSourceClass.SECONDARY_DISCOVERY),[ev(url="https://authority.example/doc")])
    assert p.research_status=="EVIDENCE_BOUND"


def test_secondary_same_host_primary_is_not_independent():
    p=build_research_packet(signal(RadarSourceClass.SECONDARY_DISCOVERY),[ev(url="https://example.org/primary-looking")])
    assert p.research_status=="HOLD_PRIMARY_CONFIRMATION"
    assert not p.scoring_input_ready


def test_secondary_context_only_does_not_bind():
    p=build_research_packet(signal(RadarSourceClass.SECONDARY_DISCOVERY),[
        ev(authority=EvidenceAuthority.SECONDARY_CONTEXT,url="https://context.example/story")
    ])
    assert p.research_status=="HOLD_PRIMARY_CONFIRMATION"


def test_synthetic_fixture_never_becomes_production_evidence():
    s=signal(RadarSourceClass.MANUAL_SYNTHETIC,synthetic=True)
    p=build_research_packet(s,[ev(authority=EvidenceAuthority.SECONDARY_CONTEXT,url="synthetic://fixture/evidence",synthetic=True)])
    assert p.research_status=="SYNTHETIC_NON_EVIDENCE"
    assert not p.evidence_bound and not p.scoring_input_ready
    assert p.unresolved_questions==("WHICH_REAL_PRIMARY_SOURCE_REPLACES_THIS_SYNTHETIC_FIXTURE?",)


def test_synthetic_cannot_bind_real_evidence():
    s=signal(RadarSourceClass.MANUAL_SYNTHETIC,synthetic=True)
    with pytest.raises(ValueError):
        build_research_packet(s,[ev(url="https://example.org/real")])


def test_production_signal_cannot_bind_synthetic_evidence():
    with pytest.raises(ValueError):
        build_research_packet(signal(),[
            ev(authority=EvidenceAuthority.SECONDARY_CONTEXT,url="synthetic://fixture/context",synthetic=True)
        ])


def test_synthetic_evidence_cannot_claim_primary_authority():
    s=signal(RadarSourceClass.MANUAL_SYNTHETIC,synthetic=True)
    with pytest.raises(ValueError):
        build_research_packet(s,[ev(url="synthetic://fixture/evidence",synthetic=True)])


def test_invalid_sha_rejected():
    s=signal()
    bad=ResearchEvidence("ev-1","https://example.org/x",EvidenceAuthority.PRIMARY_SOURCE,EvidenceKind.DOCUMENT,CAP,"BAD",False)
    with pytest.raises(ValueError): build_research_packet(s,[bad])


def test_evidence_before_signal_rejected():
    with pytest.raises(ValueError):
        build_research_packet(signal(),[ev(captured="2026-09-06T00:59:59Z")])


def test_non_https_production_evidence_rejected():
    with pytest.raises(ValueError):
        build_research_packet(signal(),[ev(url="http://example.org/x")])


def test_userinfo_rejected():
    with pytest.raises(ValueError):
        build_research_packet(signal(),[ev(url="https://user@example.org/x")])


def test_exact_duplicate_evidence_is_deduped():
    e=ev()
    p=build_research_packet(signal(),[e,e])
    assert len(p.evidence_refs)==1


def test_conflicting_duplicate_evidence_id_rejected():
    with pytest.raises(ValueError):
        build_research_packet(signal(),[ev(eid="same"),ev(eid="same",url="https://example.org/other")])


def test_evidence_order_does_not_change_hash():
    a=ev(eid="a",captured="2026-09-06T01:05:00Z")
    b=ev(eid="b",captured="2026-09-06T01:06:00Z")
    p1=build_research_packet(signal(),[b,a])
    p2=build_research_packet(signal(),[a,b])
    assert p1.research_packet_hash==p2.research_packet_hash
    assert p1.packet_id==p2.packet_id


def test_radar_observation_revision_changes_packet_identity():
    s1=signal()
    s2=materialize_signal(RadarObservation(
        external_ref="item-1",source_url="https://example.org/news/1",source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ARTICLE,observed_at_utc="2026-09-06T01:01:00Z",title="Local update",
        excerpt="Changed excerpt",topic="transport",locality="Valcea"
    ))
    p1=build_research_packet(s1)
    p2=build_research_packet(s2)
    assert p1.signal_id==p2.signal_id
    assert p1.radar_observation_hash!=p2.radar_observation_hash
    assert p1.packet_id!=p2.packet_id
    assert p1.research_packet_hash!=p2.research_packet_hash


def test_authority_is_always_fail_closed():
    p=build_research_packet(signal(),[ev()])
    assert not any((p.fact_authority,p.scoring_authority,p.draft_authority,p.publish_authority,p.network_fetch_performed))
    assert p.state=="RESEARCH_PACKET_ONLY"


def test_packet_serialization_is_deterministic():
    p=build_research_packet(signal(),[ev()])
    a=research_packets_json((p,))
    b=research_packets_json((p,))
    assert a==b
    d=json.loads(a)[0]
    assert d["research_packet_hash"]==p.research_packet_hash


def test_only_radar_signal_is_accepted():
    with pytest.raises(ValueError): build_research_packet(object())


def test_mutated_authorizing_radar_signal_rejected():
    s=signal()
    bad=s.__class__(**(s.to_dict()|{"fact_authority":True}))
    with pytest.raises(ValueError): build_research_packet(bad)


def test_tampered_radar_content_rejected_even_if_authority_flags_remain_false():
    s=signal()
    bad=s.__class__(**(s.to_dict()|{"title":"Tampered title"}))
    with pytest.raises(ValueError): build_research_packet(bad)


def test_tampered_radar_identity_rejected():
    s=signal()
    bad=s.__class__(**(s.to_dict()|{"signal_id":"0"*64}))
    with pytest.raises(ValueError): build_research_packet(bad)


def test_evidence_batch_limit():
    items=[ev(eid=f"e-{i}") for i in range(MAX_EVIDENCE+1)]
    with pytest.raises(ValueError): build_research_packet(signal(),items)
