#!/usr/bin/env python3
"""Deterministic non-clickbait Hook Engine for LOCAL NEWS OS.

The engine consumes only atomized, source-preserving content plus CHANNEL_CONFIG.
It never reads raw story prose, invents urgency/exclusivity, fabricates engagement
claims, or rewrites quotes. It selects one safe source atom and may add only a
small neutral platform frame. Unsafe/sensational candidates are skipped; if no
safe atom remains the engine fails closed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PLATFORM_PROFILES: dict[str, dict[str, Any]] = {
    "facebook": {"prefix": "Pe scurt — ", "max_chars": 300, "order": ["headline", "dek", "fact", "paragraph", "quote"]},
    "instagram": {"prefix": "De știut — ", "max_chars": 220, "order": ["headline", "dek", "fact", "quote", "paragraph"]},
    "tiktok": {"prefix": "", "max_chars": 140, "order": ["headline", "fact", "dek", "quote", "paragraph"]},
    "youtube": {"prefix": "", "max_chars": 100, "order": ["headline", "fact", "dek", "paragraph", "quote"]},
    "threads": {"prefix": "Pe scurt — ", "max_chars": 260, "order": ["headline", "dek", "fact", "paragraph", "quote"]},
    "linkedin": {"prefix": "Context local — ", "max_chars": 280, "order": ["dek", "headline", "fact", "paragraph", "quote"]},
    "whatsapp": {"prefix": "Vâlcea — ", "max_chars": 220, "order": ["headline", "dek", "fact", "paragraph", "quote"]},
    "telegram": {"prefix": "De știut — ", "max_chars": 220, "order": ["headline", "dek", "fact", "paragraph", "quote"]},
}

CLICKBAIT_PHRASES = (
    "nu o să crezi",
    "n-o să crezi",
    "nu vei crede",
    "șocant",
    "socant",
    "senzațional",
    "senzational",
    "bombă:",
    "bomba:",
    "a rupt internetul",
    "explodează internetul",
    "explodeaza internetul",
    "toată lumea vorbește",
    "toata lumea vorbeste",
    "trebuie să vezi",
    "trebuie sa vezi",
    "nu rata",
    "click aici",
    "doar noi știm",
    "doar noi stim",
    "ce nu vor să știi",
    "ce nu vor sa stii",
)

UNVERIFIED_EXCLUSIVITY = (
    "exclusiv:",
    "în exclusivitate",
    "in exclusivitate",
    "doar la noi",
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _letters(text: str) -> list[str]:
    return [char for char in text if char.isalpha()]


def _all_caps_like(text: str) -> bool:
    letters = _letters(text)
    if len(letters) < 16:
        return False
    upper = sum(1 for char in letters if char.isupper())
    return upper / len(letters) >= 0.88


def _unsafe_text(text: str) -> list[str]:
    lowered = text.casefold()
    reasons: list[str] = []
    if any(phrase in lowered for phrase in CLICKBAIT_PHRASES):
        reasons.append("CLICKBAIT_PHRASE")
    if any(phrase in lowered for phrase in UNVERIFIED_EXCLUSIVITY):
        reasons.append("UNVERIFIED_EXCLUSIVITY")
    if "!!" in text or "???" in text or text.count("!") + text.count("?") >= 4:
        reasons.append("EXCESSIVE_PUNCTUATION")
    if _all_caps_like(text):
        reasons.append("EXCESSIVE_ALL_CAPS")
    return reasons


def _hard_blocks(atom_bundle: dict[str, Any], channel: dict[str, Any], fit: dict[str, Any] | None) -> list[str]:
    blocks: list[str] = []
    if atom_bundle.get("blocked") is True:
        blocks.append("ATOM_BUNDLE_BLOCKED")
    bundle_instance = _clean(atom_bundle.get("instance_id"))
    channel_instance = _clean(channel.get("instance_id"))
    if not bundle_instance:
        blocks.append("MISSING_INSTANCE_ID")
    if not _clean(atom_bundle.get("story_id")):
        blocks.append("MISSING_STORY_ID")
    if not _clean(channel.get("channel_id")):
        blocks.append("MISSING_CHANNEL_ID")
    if bundle_instance and channel_instance and bundle_instance != channel_instance:
        blocks.append("INSTANCE_MISMATCH")
    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")

    exclusions = {
        _clean(value)
        for value in channel.get("editorial_mix", {}).get("exclusions", [])
        if _clean(value)
    }
    risks = {_clean(value) for value in atom_bundle.get("risk_flags", []) if _clean(value)}
    hits = sorted(exclusions & risks)
    if hits:
        blocks.append("CHANNEL_EXCLUSION:" + ",".join(hits))

    if fit is not None:
        if fit.get("blocked") is True or _clean(fit.get("recommendation")) == "blocked":
            blocks.append("CHANNEL_FIT_BLOCKED")
        fit_story = _clean(fit.get("story_id"))
        fit_channel = _clean(fit.get("channel_id"))
        if fit_story and fit_story != _clean(atom_bundle.get("story_id")):
            blocks.append("FIT_STORY_MISMATCH")
        if fit_channel and fit_channel != _clean(channel.get("channel_id")):
            blocks.append("FIT_CHANNEL_MISMATCH")
        if _clean(fit.get("recommendation")) == "skip":
            blocks.append("CHANNEL_FIT_SKIP")
    return blocks


def _candidate_atoms(atom_bundle: dict[str, Any], order: list[str]) -> list[dict[str, Any]]:
    rank = {atom_type: index for index, atom_type in enumerate(order)}
    atoms: list[dict[str, Any]] = []
    for atom in atom_bundle.get("atoms", []):
        if not isinstance(atom, dict):
            continue
        text = _clean(atom.get("text"))
        atom_type = _clean(atom.get("atom_type"))
        if not text or atom_type not in rank:
            continue
        atoms.append(atom)
    return sorted(atoms, key=lambda atom: (rank[_clean(atom.get("atom_type"))], int(atom.get("ordinal", 0))))


def build_hook(
    atom_bundle: dict[str, Any],
    channel: dict[str, Any],
    fit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one auditable first-line/frame hook from atomized source material."""
    if not isinstance(atom_bundle, dict) or not isinstance(channel, dict):
        raise TypeError("atom_bundle and channel must be mappings")
    if fit is not None and not isinstance(fit, dict):
        raise TypeError("fit must be a mapping when provided")

    instance_id = _clean(atom_bundle.get("instance_id")) or _clean(channel.get("instance_id"))
    story_id = _clean(atom_bundle.get("story_id"))
    channel_id = _clean(channel.get("channel_id")) or _clean(channel.get("platform"))
    platform = _clean(channel.get("platform")).lower()
    profile = PLATFORM_PROFILES.get(platform, {"prefix": "Pe scurt — ", "max_chars": 240, "order": ["headline", "dek", "fact", "paragraph", "quote"]})

    blocks = _hard_blocks(atom_bundle, channel, fit)
    base: dict[str, Any] = {
        "schema_version": "1.0",
        "instance_id": instance_id or None,
        "story_id": story_id or None,
        "channel_id": channel_id or None,
        "platform": platform or None,
        "atom_bundle_fingerprint_sha256": _clean(atom_bundle.get("source_fingerprint_sha256")) or _digest(atom_bundle),
        "blocked": bool(blocks),
        "hard_blocks": blocks,
        "rejected_candidates": [],
        "hook": None,
    }
    if blocks:
        return base

    correction = atom_bundle.get("correction") is True
    prefix = "Corecție — " if correction else str(profile["prefix"])
    max_chars = int(profile["max_chars"])

    for atom in _candidate_atoms(atom_bundle, list(profile["order"])):
        source_text = _clean(atom.get("text"))
        unsafe = _unsafe_text(source_text)
        if unsafe:
            base["rejected_candidates"].append({"atom_id": atom.get("atom_id"), "reasons": unsafe})
            continue
        hook_text = prefix + source_text
        if len(hook_text) > max_chars:
            base["rejected_candidates"].append({"atom_id": atom.get("atom_id"), "reasons": ["HOOK_TOO_LONG"]})
            continue

        strategy = "correction_source_atom" if correction else ("direct_source_atom" if not prefix else "neutral_frame_plus_source_atom")
        hook_id = "hook:" + _digest(
            {
                "channel_id": channel_id,
                "story_id": story_id,
                "atom_id": atom.get("atom_id"),
                "strategy": strategy,
                "text": hook_text,
            }
        )[:24]
        base["hook"] = {
            "hook_id": hook_id,
            "text": hook_text,
            "strategy": strategy,
            "source_atom_id": atom.get("atom_id"),
            "source_atom_type": atom.get("atom_type"),
            "source_text": source_text,
            "generated_frame": prefix,
            "source_preserving": True,
            "verbatim_source_required": atom.get("mutation_policy") == "verbatim_only",
            "max_chars": max_chars,
            "clickbait_guard": "PASS",
            "invented_claims_allowed": False,
        }
        return base

    base["blocked"] = True
    base["hard_blocks"].append("NO_SAFE_HOOK_ATOM")
    return base


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("atom_bundle", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("--fit", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = build_hook(_load(args.atom_bundle), _load(args.channel), _load(args.fit) if args.fit else None)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
