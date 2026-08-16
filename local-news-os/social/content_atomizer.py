#!/usr/bin/env python3
"""Deterministic, dependency-free content atomizer for LOCAL NEWS OS.

The atomizer converts one normalized STORY_OBJECT into immutable source atoms that
later channel-specific hook/format engines may select and transform under their
own editorial gates. It does not write social copy, infer missing facts, create
engagement claims, or mutate quoted/factual source material.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


BLOCKED_GATES = {"BLOCK", "BLOCKED"}


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _clean_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _hard_blocks(story: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if not _clean_text(story.get("instance_id")):
        blocks.append("MISSING_INSTANCE_ID")
    if not _clean_text(story.get("story_id") or story.get("id")):
        blocks.append("MISSING_STORY_ID")
    gate = _clean_text(story.get("material_fact_gate") or "PASS").upper()
    if gate.startswith("FAIL") or gate.startswith("HOLD") or gate in BLOCKED_GATES:
        blocks.append("MATERIAL_FACT_GATE")
    return blocks


def _source_identity_payload(story: dict[str, Any]) -> dict[str, Any]:
    """Return only source/editorial fields that can legitimately affect atom output.

    Operational scores, observed/predictive analytics and arbitrary upstream metadata
    are deliberately excluded. This keeps product/dedupe identity stable when such
    non-content fields are attached to the same verified fact kernel.
    """
    return {
        "instance_id": _clean_text(story.get("instance_id")) or None,
        "story_id": _clean_text(story.get("story_id") or story.get("id")) or None,
        "material_fact_gate": _clean_text(story.get("material_fact_gate") or "PASS").upper(),
        "headline": copy.deepcopy(story.get("headline")),
        "dek": copy.deepcopy(story.get("dek")),
        "paragraphs": copy.deepcopy(_as_list(story.get("paragraphs"))),
        "facts": copy.deepcopy(_as_list(story.get("facts"))),
        "quotes": copy.deepcopy(_as_list(story.get("quotes"))),
        "topics": [str(v).strip() for v in _as_list(story.get("topics")) if str(v).strip()],
        "risk_flags": [str(v).strip() for v in _as_list(story.get("risk_flags")) if str(v).strip()],
        "correction": story.get("correction") is True,
    }


def _atom_id(story_id: str, atom_type: str, ordinal: int, payload: Any) -> str:
    digest = _digest(
        {
            "story_id": story_id,
            "atom_type": atom_type,
            "ordinal": ordinal,
            "payload": payload,
        }
    )[:20]
    return f"{story_id}:{atom_type}:{ordinal}:{digest}"


def _atom(
    *,
    instance_id: str,
    story_id: str,
    atom_type: str,
    ordinal: int,
    source_field: str,
    payload: Any,
    text: str | None = None,
    verbatim_only: bool = False,
    source_ref: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "atom_id": _atom_id(story_id, atom_type, ordinal, payload),
        "instance_id": instance_id,
        "story_id": story_id,
        "atom_type": atom_type,
        "ordinal": ordinal,
        "source_field": source_field,
        "payload": copy.deepcopy(payload),
        "payload_sha256": _digest(payload),
        "mutation_policy": "verbatim_only" if verbatim_only else "source_preserving",
    }
    if text is not None:
        item["text"] = text
    if source_ref:
        item["source_ref"] = source_ref
    return item


def atomize_story(story: dict[str, Any]) -> dict[str, Any]:
    """Convert a normalized story into source-preserving content atoms.

    Recognized input fields are deliberately narrow: headline, dek, paragraphs,
    facts and quotes. Unknown fields are not converted into prose. Structured
    fact payloads are copied byte-semantically via canonical JSON and never
    rendered into invented sentences.
    """
    if not isinstance(story, dict):
        raise TypeError("STORY_OBJECT must be a mapping")

    blocks = _hard_blocks(story)
    instance_id = _clean_text(story.get("instance_id"))
    story_id = _clean_text(story.get("story_id") or story.get("id"))
    gate = _clean_text(story.get("material_fact_gate") or "PASS").upper()
    source_fingerprint = _digest(_source_identity_payload(story))

    base = {
        "schema_version": "1.0",
        "instance_id": instance_id or None,
        "story_id": story_id or None,
        "source_fingerprint_sha256": source_fingerprint,
        "material_fact_gate": gate,
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "topics": [str(v).strip() for v in _as_list(story.get("topics")) if str(v).strip()],
        "risk_flags": [str(v).strip() for v in _as_list(story.get("risk_flags")) if str(v).strip()],
        "correction": story.get("correction") is True,
        "atoms": [],
    }
    if blocks:
        return base

    atoms: list[dict[str, Any]] = []

    headline = _clean_text(story.get("headline"))
    if headline:
        atoms.append(
            _atom(
                instance_id=instance_id,
                story_id=story_id,
                atom_type="headline",
                ordinal=0,
                source_field="headline",
                payload=headline,
                text=headline,
            )
        )

    dek = _clean_text(story.get("dek"))
    if dek:
        atoms.append(
            _atom(
                instance_id=instance_id,
                story_id=story_id,
                atom_type="dek",
                ordinal=0,
                source_field="dek",
                payload=dek,
                text=dek,
            )
        )

    for index, value in enumerate(_as_list(story.get("paragraphs"))):
        text = _clean_text(value)
        if not text:
            continue
        atoms.append(
            _atom(
                instance_id=instance_id,
                story_id=story_id,
                atom_type="paragraph",
                ordinal=index,
                source_field="paragraphs",
                payload=text,
                text=text,
            )
        )

    for index, value in enumerate(_as_list(story.get("facts"))):
        if isinstance(value, dict):
            payload = copy.deepcopy(value)
            text = _clean_text(value.get("text") or value.get("statement")) or None
            source_ref = _clean_text(value.get("fact_id") or value.get("id")) or None
            atoms.append(
                _atom(
                    instance_id=instance_id,
                    story_id=story_id,
                    atom_type="fact",
                    ordinal=index,
                    source_field="facts",
                    payload=payload,
                    text=text,
                    source_ref=source_ref,
                )
            )
        else:
            text = _clean_text(value)
            if text:
                atoms.append(
                    _atom(
                        instance_id=instance_id,
                        story_id=story_id,
                        atom_type="fact",
                        ordinal=index,
                        source_field="facts",
                        payload=text,
                        text=text,
                    )
                )

    for index, value in enumerate(_as_list(story.get("quotes"))):
        if isinstance(value, dict):
            quote_text = _clean_text(value.get("text") or value.get("quote"))
            if not quote_text:
                continue
            payload = copy.deepcopy(value)
            source_ref = _clean_text(value.get("quote_id") or value.get("id")) or None
        else:
            quote_text = _clean_text(value)
            if not quote_text:
                continue
            payload = quote_text
            source_ref = None
        atoms.append(
            _atom(
                instance_id=instance_id,
                story_id=story_id,
                atom_type="quote",
                ordinal=index,
                source_field="quotes",
                payload=payload,
                text=quote_text,
                verbatim_only=True,
                source_ref=source_ref,
            )
        )

    base["atoms"] = atoms
    base["atom_count"] = len(atoms)
    base["atom_types"] = sorted({str(item["atom_type"]) for item in atoms})
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story", type=Path, help="normalized STORY_OBJECT JSON")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = atomize_story(_load(args.story))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
