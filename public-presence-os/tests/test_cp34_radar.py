import pytest
from pathlib import Path
from public_presence_os.radar import *
from public_presence_os.control import load_json
from public_presence_os.rehearsal import run_synthetic_rehearsal

ROOT=Path(__file__).resolve().parents[1]


def primary(**kw):
    base=dict(
        external_ref="official-001",
        source_url="https://Example.COM/news/item#fragment",
        source_class=RadarSourceClass.PRIMARY_PUBLIC,
        kind=RadarKind.ANNOUNCEMENT,
        observed_at_utc="2026-09-06T00:30:00Z",
        title="  Funding   update  ",
        excerpt=" A bounded discovery excerpt. ",
        topic="funding",
        locality="Romania",
        synthetic=False,
    )
    base.update(kw)
    return RadarObservation(**base)


def test_materialize_is_deterministic_and_discovery_only():
    a=materialize_signal(primary()); b=materialize_signal(primary())
    assert a==b
    assert a.state=="DISCOVERY_ONLY"
    assert a.fact_authority is False
    assert a.publish_authority is False
    assert a.network_fetch_performed is False
    assert a.source_url=="https://example.com/news/item"
    assert a.title=="Funding update"


def test_content_change_keeps_signal_identity_but_changes_observation_hash():
    a=materialize_signal(primary(excerpt="one")); b=materialize_signal(primary(excerpt="two"))
    assert a.signal_id==b.signal_id
    assert a.observation_hash!=b.observation_hash


def test_ref_change_changes_signal_identity():
    assert materialize_signal(primary()).signal_id!=materialize_signal(primary(external_ref="official-002")).signal_id


def test_batch_deduplicates_exact_replay():
    x=primary()
    assert len(ingest_observations([x,x]))==1


def test_batch_preserves_distinct_revisions():
    signals=ingest_observations([primary(excerpt="one"),primary(excerpt="two")])
    assert len(signals)==2
    assert signals[0].signal_id==signals[1].signal_id


def test_batch_is_deterministic_across_input_order():
    a=primary(external_ref="a",observed_at_utc="2026-09-06T00:30:00Z")
    b=primary(external_ref="b",observed_at_utc="2026-09-06T00:20:00Z")
    assert ingest_observations([a,b])==ingest_observations([b,a])


def test_batch_limit():
    with pytest.raises(ValueError):
        ingest_observations([primary(external_ref=f"x{i}") for i in range(MAX_BATCH+1)])


@pytest.mark.parametrize("bad",["http://example.com/x","ftp://example.com/x","https:///x",""])
def test_public_sources_require_https(bad):
    with pytest.raises(ValueError): materialize_signal(primary(source_url=bad))


def test_url_userinfo_rejected():
    with pytest.raises(ValueError): materialize_signal(primary(source_url="https://user@example.com/x"))


def test_synthetic_source_contract():
    o=RadarObservation(
        external_ref="fixture-1",source_url="synthetic://fixture/radar/1",
        source_class=RadarSourceClass.MANUAL_SYNTHETIC,kind=RadarKind.OTHER,
        observed_at_utc="2026-09-06T00:00:00Z",title="Fixture",excerpt="",
        topic="test",locality="test",synthetic=True,
    )
    s=materialize_signal(o)
    assert s.synthetic is True
    assert s.source_url=="synthetic://fixture/radar/1"


def test_synthetic_cannot_masquerade_as_public():
    with pytest.raises(ValueError): materialize_signal(primary(synthetic=True))


def test_manual_synthetic_cannot_use_https():
    o=RadarObservation(
        external_ref="fixture-1",source_url="https://example.com/fake",
        source_class=RadarSourceClass.MANUAL_SYNTHETIC,kind=RadarKind.OTHER,
        observed_at_utc="2026-09-06T00:00:00Z",title="Fixture",excerpt="",
        topic="test",locality="test",synthetic=True,
    )
    with pytest.raises(ValueError): materialize_signal(o)


@pytest.mark.parametrize("stamp",["2026-09-06T00:00:00+03:00","2026-09-06","bad",""])
def test_timestamp_must_be_z_utc(stamp):
    with pytest.raises(ValueError): materialize_signal(primary(observed_at_utc=stamp))


def test_field_limits():
    with pytest.raises(ValueError): materialize_signal(primary(title="x"*281))
    with pytest.raises(ValueError): materialize_signal(primary(excerpt="x"*2001))
    with pytest.raises(ValueError): materialize_signal(primary(topic="x"*81))


def test_ref_characters_fail_closed():
    with pytest.raises(ValueError): materialize_signal(primary(external_ref="<script>"))


def test_json_output_contains_no_authority():
    text=signals_json(ingest_observations([primary()]))
    assert '"fact_authority": false' in text
    assert '"publish_authority": false' in text
    assert '"network_fetch_performed": false' in text


def test_priority_map_preserves_m01_lock_and_progresses_forward():
    p=load_json(ROOT/"config"/"reimplementation_priority.json")
    assert p["order"][0]["module_id"]=="M01_RADAR"
    assert p["order"][0]["state"]=="CP34_MINIMAL_EXECUTABLE_SLICE"
    assert p["order"][1]["module_id"]=="M02_RESEARCH"
    assert p["order"][1]["state"] in {"NEXT","CP35_MINIMAL_EXECUTABLE_SLICE"}


def test_module_registry_preserves_cp34_m01_state():
    r=load_json(ROOT/"config"/"module_registry.json")
    m={x["id"]:x for x in r["modules"]}
    assert m["M01_RADAR"]["status"]=="CP34_MINIMAL_EXECUTABLE_SLICE"


def test_rehearsal_keeps_m01_executable_as_later_stages_arrive():
    r=run_synthetic_rehearsal(ROOT)
    stages={s.module_id:s.state for s in r.stages}
    assert stages["M01_RADAR"]=="PASS_EXECUTABLE_SOURCE"
    assert "M01_RADAR:EXECUTABLE_SOURCE_UNAVAILABLE" not in r.blockers
    assert sum(1 for x in r.blockers if x.endswith(":EXECUTABLE_SOURCE_UNAVAILABLE")) <= 13
