#!/usr/bin/env python3
"""Acceptance tests for the dependency-free LOCAL NEWS OS content atomizer."""
from __future__ import annotations

import copy

from content_atomizer import atomize_story


def sample_story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "story-001",
        "material_fact_gate": "PASS",
        "headline": "Primăria publică programul pentru weekend",
        "dek": "Programul include două evenimente cu acces liber.",
        "paragraphs": [
            "Primul eveniment începe sâmbătă la ora 18:00.",
            "Al doilea are loc duminică în parcul central.",
        ],
        "facts": [
            {
                "fact_id": "fact-1",
                "text": "Accesul la primul eveniment este liber.",
                "source_ids": ["source-a"],
            },
            {
                "fact_id": "fact-2",
                "value": 18,
                "unit": "hour_local",
                "source_ids": ["source-b"],
            },
        ],
        "quotes": [
            {
                "quote_id": "quote-1",
                "text": "Programul rămâne neschimbat.",
                "speaker": "instituție",
            }
        ],
        "topics": ["local_events", "service_journalism"],
        "risk_flags": [],
        "confidence": 98,
        "analytics": {"views": 999999999},
    }


def test_exact_source_preservation() -> None:
    story = sample_story()
    result = atomize_story(story)
    assert result["blocked"] is False
    by_type: dict[str, list[dict]] = {}
    for atom in result["atoms"]:
        by_type.setdefault(atom["atom_type"], []).append(atom)
    assert by_type["headline"][0]["text"] == story["headline"]
    assert by_type["dek"][0]["text"] == story["dek"]
    assert [x["text"] for x in by_type["paragraph"]] == story["paragraphs"]
    assert by_type["fact"][0]["payload"] == story["facts"][0]
    assert by_type["fact"][1]["payload"] == story["facts"][1]
    assert "text" not in by_type["fact"][1]


def test_quotes_are_verbatim_only() -> None:
    result = atomize_story(sample_story())
    quote = next(atom for atom in result["atoms"] if atom["atom_type"] == "quote")
    assert quote["text"] == "Programul rămâne neschimbat."
    assert quote["mutation_policy"] == "verbatim_only"
    assert quote["source_ref"] == "quote-1"


def test_deterministic_output() -> None:
    first = atomize_story(sample_story())
    second = atomize_story(copy.deepcopy(sample_story()))
    assert first == second


def test_content_change_changes_fingerprint_and_atom_id() -> None:
    before = atomize_story(sample_story())
    changed = sample_story()
    changed["headline"] = "Primăria actualizează programul pentru weekend"
    after = atomize_story(changed)
    assert before["source_fingerprint_sha256"] != after["source_fingerprint_sha256"]
    first_headline = next(x for x in before["atoms"] if x["atom_type"] == "headline")
    second_headline = next(x for x in after["atoms"] if x["atom_type"] == "headline")
    assert first_headline["atom_id"] != second_headline["atom_id"]


def test_non_content_analytics_do_not_change_source_identity() -> None:
    baseline_story = sample_story()
    baseline_story.pop("analytics")
    baseline = atomize_story(baseline_story)

    noisy_story = copy.deepcopy(baseline_story)
    noisy_story["analytics"] = {"views": 888888, "predicted_engagement": 0.99}
    noisy_story["predicted_views"] = 123456789
    noisy_story["virality_probability"] = 0.999
    noisy_story["confidence"] = 12
    noisy = atomize_story(noisy_story)

    assert baseline["source_fingerprint_sha256"] == noisy["source_fingerprint_sha256"]
    assert baseline["atoms"] == noisy["atoms"]


def test_no_instance_contamination() -> None:
    result = atomize_story(sample_story())
    assert result["instance_id"] == "valcea"
    assert all(atom["instance_id"] == "valcea" for atom in result["atoms"])
    assert all(atom["story_id"] == "story-001" for atom in result["atoms"])


def test_blocked_material_gate_yields_no_atoms() -> None:
    story = sample_story()
    story["material_fact_gate"] = "HOLD_REVIEW"
    result = atomize_story(story)
    assert result["blocked"] is True
    assert "MATERIAL_FACT_GATE" in result["hard_blocks"]
    assert result["atoms"] == []


def test_missing_identity_fails_closed() -> None:
    story = sample_story()
    story.pop("instance_id")
    story.pop("story_id")
    result = atomize_story(story)
    assert result["blocked"] is True
    assert "MISSING_INSTANCE_ID" in result["hard_blocks"]
    assert "MISSING_STORY_ID" in result["hard_blocks"]
    assert result["atoms"] == []


def test_unknown_fields_do_not_become_atoms() -> None:
    result = atomize_story(sample_story())
    assert all(atom["source_field"] != "analytics" for atom in result["atoms"])
    assert "999999999" not in str(result["atoms"])


def test_structured_fact_is_not_rendered_into_invented_prose() -> None:
    result = atomize_story(sample_story())
    structured = [
        atom
        for atom in result["atoms"]
        if atom["atom_type"] == "fact" and atom.get("source_ref") == "fact-2"
    ][0]
    assert structured["payload"]["value"] == 18
    assert structured["payload"]["unit"] == "hour_local"
    assert "text" not in structured


def main() -> int:
    tests = [
        test_exact_source_preservation,
        test_quotes_are_verbatim_only,
        test_deterministic_output,
        test_content_change_changes_fingerprint_and_atom_id,
        test_non_content_analytics_do_not_change_source_identity,
        test_no_instance_contamination,
        test_blocked_material_gate_yields_no_atoms,
        test_missing_identity_fails_closed,
        test_unknown_fields_do_not_become_atoms,
        test_structured_fact_is_not_rendered_into_invented_prose,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Content atomizer acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
