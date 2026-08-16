#!/usr/bin/env python3
"""Production runtime orchestrator for LOCAL NEWS OS social publications.

This module composes the dependency-free social core into one deterministic,
fail-closed per-story/per-channel execution path:

CHANNEL FIT -> ATOMIZER -> SAFE HOOK -> NATIVE FORMAT -> REAL VISUALS ->
LINK POLICY -> CADENCE/FATIGUE -> VIRALITY -> OPTIONAL OBSERVED FEEDBACK ->
PUBLICATION STATE.

It deliberately does *not* dispatch network requests or read credential values.
Publishing adapters remain a separate boundary. A successful run returns the
updated channel-local publication ledger so the owning site runtime can persist
it atomically; channels without verified direct publication remain OUTBOX_READY
through the existing publication-state policy.

Website and social channels remain sibling publications. The orchestrator never
copies social output between platforms: every invocation starts from the shared
verified STORY_OBJECT / fact kernel and builds one channel-native product.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import cadence_fatigue
import channel_fit
import content_atomizer
import format_engine
import hook_engine
import observed_feedback_application
import publication_state
import virality_engine
import visual_router

SCHEMA_VERSION = "1.0"
PIPELINE_ORDER = [
    "preflight",
    "channel_fit",
    "content_atomizer",
    "hook_engine",
    "format_engine",
    "visual_router",
    "link_policy",
    "cadence_fatigue",
    "virality_engine",
    "observed_feedback",
    "publication_state",
]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _preflight(story: dict[str, Any], channel: dict[str, Any], inventory: dict[str, Any], history: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    story_id = _clean(story.get("story_id") or story.get("id"))
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()

    if not story_id:
        blocks.append("MISSING_STORY_ID")
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not platform:
        blocks.append("MISSING_PLATFORM")
    if _clean(story.get("instance_id")) != instance_id:
        blocks.append("INSTANCE_MISMATCH")
    if _clean(inventory.get("instance_id")) != instance_id:
        blocks.append("MEDIA_INSTANCE_MISMATCH")
    if _clean(history.get("instance_id")) != instance_id:
        blocks.append("HISTORY_INSTANCE_MISMATCH")
    if _clean(history.get("channel_id")) != channel_id:
        blocks.append("HISTORY_CHANNEL_MISMATCH")
    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_METRICS_POLICY_REQUIRED")
    gate = _clean(story.get("material_fact_gate")).upper()
    if not gate.startswith("PASS"):
        blocks.append("MATERIAL_FACT_GATE")
    if not isinstance(history.get("records"), list):
        blocks.append("INVALID_CADENCE_HISTORY")
    if not isinstance(inventory.get("assets"), list):
        blocks.append("INVALID_MEDIA_INVENTORY")
    return sorted(set(blocks))


def _cadence_candidate(story: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    stage = _clean(story.get("lifecycle_stage")).lower()
    if story.get("correction") is True:
        publication_class = "correction"
    elif stage == "breaking":
        publication_class = "breaking"
    else:
        publication_class = "normal"
    topics = story.get("topics") if isinstance(story.get("topics"), list) else []
    return {
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "story_id": _clean(story.get("story_id") or story.get("id")),
        "publication_class": publication_class,
        "correction_of": _clean(story.get("correction_of")) or None,
        "topic_ids": [_clean(value) for value in topics if _clean(value)],
        "related_group_id": _clean(story.get("related_group_id")) or None,
    }


def _link_binding(channel: dict[str, Any], format_result: dict[str, Any], canonical_url: str | None) -> dict[str, Any]:
    product = format_result.get("product") if isinstance(format_result.get("product"), dict) else {}
    requirement = product.get("link_requirement") if isinstance(product.get("link_requirement"), dict) else {}
    mode = _clean(requirement.get("mode")) or "optional"
    allowed = sorted({_clean(value).casefold() for value in requirement.get("canonical_hosts", []) if _clean(value)}) if isinstance(requirement.get("canonical_hosts"), list) else []
    supplied = _clean(canonical_url)
    result: dict[str, Any] = {
        "mode": mode,
        "required": mode == "required",
        "status": "OPTIONAL_UNBOUND",
        "bound_url": None,
        "canonical_host": None,
        "hard_blocks": [],
        "hold": False,
        "network_validation_performed": False,
    }
    if not supplied:
        if mode == "required":
            result["status"] = "REQUIRED_LINK_PENDING"
            result["hold"] = True
        elif mode == "native_preferred":
            result["status"] = "NATIVE_STANDALONE"
        result["binding_fingerprint_sha256"] = _digest(result)
        return result

    parsed = urlparse(supplied)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host:
        result["status"] = "LINK_BLOCKED"
        result["hard_blocks"] = ["INVALID_CANONICAL_URL"]
    elif allowed and host not in allowed:
        result["status"] = "LINK_BLOCKED"
        result["hard_blocks"] = ["LINK_HOST_NOT_ALLOWED"]
    else:
        result["status"] = "LINK_BOUND"
        result["bound_url"] = supplied
        result["canonical_host"] = host
    result["binding_fingerprint_sha256"] = _digest(result)
    return result


def _stage(stages: list[dict[str, Any]], name: str, status: str, *, reasons: list[str] | None = None, fingerprint: str | None = None) -> None:
    item: dict[str, Any] = {"name": name, "status": status}
    if reasons:
        item["reasons"] = list(reasons)
    if fingerprint:
        item["fingerprint_sha256"] = fingerprint
    stages.append(item)


def _pipeline_fingerprint(
    *,
    story: dict[str, Any],
    channel: dict[str, Any],
    artifacts: dict[str, Any],
    stages: list[dict[str, Any]],
) -> str:
    atom_bundle = artifacts.get("atom_bundle") if isinstance(artifacts.get("atom_bundle"), dict) else {}
    product_result = artifacts.get("format") if isinstance(artifacts.get("format"), dict) else {}
    product = product_result.get("product") if isinstance(product_result.get("product"), dict) else {}
    visual = artifacts.get("visual") if isinstance(artifacts.get("visual"), dict) else {}
    binding = visual.get("binding") if isinstance(visual.get("binding"), dict) else {}
    link = artifacts.get("link_binding") if isinstance(artifacts.get("link_binding"), dict) else {}
    cadence = artifacts.get("cadence") if isinstance(artifacts.get("cadence"), dict) else {}
    virality = artifacts.get("virality") if isinstance(artifacts.get("virality"), dict) else {}
    feedback = artifacts.get("observed_feedback") if isinstance(artifacts.get("observed_feedback"), dict) else {}
    publication = artifacts.get("publication") if isinstance(artifacts.get("publication"), dict) else {}
    record = publication.get("record") if isinstance(publication.get("record"), dict) else {}
    return _digest(
        {
            "instance_id": _clean(channel.get("instance_id")),
            "channel_id": _clean(channel.get("channel_id")),
            "platform": _clean(channel.get("platform")).lower(),
            "story_id": _clean(story.get("story_id") or story.get("id")),
            "source_fingerprint_sha256": atom_bundle.get("source_fingerprint_sha256"),
            "product_id": product.get("product_id"),
            "product_fingerprint_sha256": product.get("product_fingerprint_sha256"),
            "visual_binding_fingerprint_sha256": binding.get("binding_fingerprint_sha256"),
            "link_binding_fingerprint_sha256": link.get("binding_fingerprint_sha256"),
            "cadence_decision_fingerprint_sha256": cadence.get("decision_fingerprint_sha256"),
            "virality_decision_fingerprint_sha256": virality.get("decision_fingerprint_sha256"),
            "observed_feedback_application_fingerprint_sha256": feedback.get("application_fingerprint_sha256"),
            "publication_id": record.get("publication_id"),
            "stage_path": [(row.get("name"), row.get("status")) for row in stages],
        }
    )


def _finish(
    *,
    story: dict[str, Any],
    channel: dict[str, Any],
    stages: list[dict[str, Any]],
    artifacts: dict[str, Any],
    blocked: bool,
    disposition: str,
    hard_blocks: list[str] | None = None,
) -> dict[str, Any]:
    publication = artifacts.get("publication") if isinstance(artifacts.get("publication"), dict) else {}
    record = publication.get("record") if isinstance(publication.get("record"), dict) else {}
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or _clean(story.get("instance_id")) or None,
        "story_id": _clean(story.get("story_id") or story.get("id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "blocked": blocked,
        "hard_blocks": sorted(set(hard_blocks or [])),
        "disposition": disposition,
        "stages": stages,
        "artifacts": artifacts,
        "handoff": {
            "publication_id": record.get("publication_id"),
            "publication_status": record.get("status"),
            "adapter_dispatch_eligible": record.get("status") == "READY",
            "durable_outbox_ready": record.get("status") == "OUTBOX_READY",
            "requires_human_approval": record.get("status") == "AWAITING_APPROVAL",
            "timing_hold": record.get("status") == "HOLD_TIMING",
            "link_hold": disposition == "HOLD_LINK_BINDING",
            "adapter_dispatch_performed": False,
        },
        "guards": {
            "verified_fact_kernel_required": True,
            "channel_native_product_required": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "real_media_provenance_required_when_visual": True,
            "predictive_analytics_used": False,
            "editorial_gates_weakened": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_calls_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }
    result["pipeline_fingerprint_sha256"] = _pipeline_fingerprint(story=story, channel=channel, artifacts=artifacts, stages=stages)
    return result


def orchestrate_channel(
    story: dict[str, Any],
    channel: dict[str, Any],
    media_inventory: dict[str, Any],
    cadence_history: dict[str, Any],
    *,
    now: str,
    ledger: dict[str, Any] | None = None,
    human_approved: bool = False,
    canonical_url: str | None = None,
    series_decision: dict[str, Any] | None = None,
    observed_feedback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one native social publication and register its durable state.

    The function is deterministic for identical inputs. It has no side effects and
    performs no adapter/network dispatch. Callers persist ``artifacts.publication.ledger``
    only after this function returns; repeated calls with that ledger are idempotent.
    Observed feedback is optional and can only contribute a bounded ranking adjustment;
    invalid feedback is ignored without changing the underlying publication decision.
    """
    required = (story, channel, media_inventory, cadence_history)
    if not all(isinstance(value, dict) for value in required):
        raise TypeError("story, channel, media_inventory and cadence_history must be mappings")
    if ledger is not None and not isinstance(ledger, dict):
        raise TypeError("ledger must be a mapping when provided")
    if series_decision is not None and not isinstance(series_decision, dict):
        raise TypeError("series_decision must be a mapping when provided")
    if observed_feedback is not None and not isinstance(observed_feedback, dict):
        raise TypeError("observed_feedback must be a mapping when provided")
    if not _clean(now):
        raise ValueError("now is required and must be timezone-aware")

    stages: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {}

    preflight = _preflight(story, channel, media_inventory, cadence_history)
    if preflight:
        _stage(stages, "preflight", "BLOCKED", reasons=preflight)
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_PREFLIGHT", hard_blocks=preflight)
    _stage(stages, "preflight", "PASS")

    fit = channel_fit.score_story(story, channel)
    artifacts["channel_fit"] = fit
    fit_fp = _digest(fit)
    if fit.get("blocked") is True:
        reasons = [str(value) for value in fit.get("hard_blocks", [])]
        _stage(stages, "channel_fit", "BLOCKED", reasons=reasons, fingerprint=fit_fp)
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_CHANNEL_FIT", hard_blocks=reasons)
    if _clean(fit.get("recommendation")) == "skip":
        _stage(stages, "channel_fit", "SKIP", reasons=["CHANNEL_FIT_SKIP"], fingerprint=fit_fp)
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=False, disposition="SKIPPED_CHANNEL_FIT")
    _stage(stages, "channel_fit", "PASS", fingerprint=fit_fp)

    atoms = content_atomizer.atomize_story(story)
    artifacts["atom_bundle"] = atoms
    if atoms.get("blocked") is True:
        reasons = [str(value) for value in atoms.get("hard_blocks", [])]
        _stage(stages, "content_atomizer", "BLOCKED", reasons=reasons, fingerprint=_clean(atoms.get("source_fingerprint_sha256")))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_ATOMIZER", hard_blocks=reasons)
    _stage(stages, "content_atomizer", "PASS", fingerprint=_clean(atoms.get("source_fingerprint_sha256")))

    hook = hook_engine.build_hook(atoms, channel, fit)
    artifacts["hook"] = hook
    if hook.get("blocked") is True:
        reasons = [str(value) for value in hook.get("hard_blocks", [])]
        _stage(stages, "hook_engine", "BLOCKED", reasons=reasons, fingerprint=_digest(hook))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_HOOK", hard_blocks=reasons)
    _stage(stages, "hook_engine", "PASS", fingerprint=_digest(hook))

    formatted = format_engine.build_native_product(atoms, hook, channel)
    artifacts["format"] = formatted
    if formatted.get("blocked") is True:
        reasons = [str(value) for value in formatted.get("hard_blocks", [])]
        _stage(stages, "format_engine", "BLOCKED", reasons=reasons, fingerprint=_digest(formatted))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_FORMAT", hard_blocks=reasons)
    product = formatted.get("product") if isinstance(formatted.get("product"), dict) else {}
    _stage(stages, "format_engine", "PASS", fingerprint=_clean(product.get("product_fingerprint_sha256")) or _digest(formatted))

    visual = visual_router.bind_visuals(formatted, channel, media_inventory)
    artifacts["visual"] = visual
    binding = visual.get("binding") if isinstance(visual.get("binding"), dict) else {}
    if visual.get("blocked") is True:
        reasons = [str(value) for value in visual.get("hard_blocks", [])]
        _stage(stages, "visual_router", "BLOCKED", reasons=reasons, fingerprint=_clean(binding.get("binding_fingerprint_sha256")) or _digest(visual))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_VISUAL", hard_blocks=reasons)
    _stage(stages, "visual_router", "PASS", fingerprint=_clean(binding.get("binding_fingerprint_sha256")) or _digest(visual))

    link = _link_binding(channel, formatted, canonical_url)
    artifacts["link_binding"] = link
    if link.get("hard_blocks"):
        reasons = [str(value) for value in link.get("hard_blocks", [])]
        _stage(stages, "link_policy", "BLOCKED", reasons=reasons, fingerprint=_clean(link.get("binding_fingerprint_sha256")))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_LINK_POLICY", hard_blocks=reasons)
    if link.get("hold") is True:
        _stage(stages, "link_policy", "HOLD", reasons=["REQUIRED_LINK_PENDING"], fingerprint=_clean(link.get("binding_fingerprint_sha256")))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=False, disposition="HOLD_LINK_BINDING")
    _stage(stages, "link_policy", "PASS", fingerprint=_clean(link.get("binding_fingerprint_sha256")))

    cadence = cadence_fatigue.evaluate_cadence(
        _cadence_candidate(story, channel),
        channel,
        cadence_history,
        now=now,
    )
    artifacts["cadence"] = cadence
    if cadence.get("hard_blocks"):
        reasons = [str(value) for value in cadence.get("hard_blocks", [])]
        _stage(stages, "cadence_fatigue", "BLOCKED", reasons=reasons, fingerprint=_clean(cadence.get("decision_fingerprint_sha256")))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_CADENCE", hard_blocks=reasons)
    cadence_status = "PASS" if cadence.get("eligible") is True else "HOLD"
    _stage(stages, "cadence_fatigue", cadence_status, reasons=[str(value) for value in cadence.get("cadence_blocks", [])], fingerprint=_clean(cadence.get("decision_fingerprint_sha256")))

    virality = virality_engine.score_virality(
        story,
        channel,
        fit,
        hook,
        formatted,
        visual=visual,
        cadence=cadence,
        series=series_decision,
    )
    artifacts["virality"] = virality
    if series_decision is not None:
        artifacts["series_decision"] = series_decision
    if virality.get("blocked") is True:
        reasons = [str(value) for value in virality.get("hard_blocks", [])]
        _stage(stages, "virality_engine", "BLOCKED", reasons=reasons, fingerprint=_clean(virality.get("decision_fingerprint_sha256")))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_VIRALITY", hard_blocks=reasons)
    _stage(stages, "virality_engine", "PASS", fingerprint=_clean(virality.get("decision_fingerprint_sha256")))

    if observed_feedback is not None:
        feedback_bundle = observed_feedback_application.apply_to_virality(
            channel,
            observed_feedback,
            story,
            formatted,
            virality,
            cadence=cadence,
            series=series_decision,
        )
        feedback_application = feedback_bundle["feedback_application"]
        artifacts["observed_feedback"] = feedback_application
        virality = feedback_bundle["virality"]
        artifacts["virality"] = virality
        feedback_status = _clean(feedback_application.get("status"))
        if feedback_bundle.get("effective_applied") is True:
            stage_status = "PASS"
            stage_reasons = [f"BOUNDED_ADJUSTMENT:{float(feedback_application.get('bounded_adjustment_points', 0.0)):+.2f}"]
        elif feedback_status == "IGNORED_INVALID":
            stage_status = "IGNORED"
            stage_reasons = [str(value) for value in feedback_application.get("feedback_blocks", [])]
        else:
            stage_status = "NOOP"
            stage_reasons = [feedback_status] if feedback_status else []
        _stage(
            stages,
            "observed_feedback",
            stage_status,
            reasons=stage_reasons,
            fingerprint=_clean(feedback_application.get("application_fingerprint_sha256")),
        )

    prepared = publication_state.prepare_publication(
        formatted,
        virality,
        channel,
        ledger,
        human_approved=human_approved,
    )
    artifacts["publication"] = prepared
    if prepared.get("blocked") is True:
        reasons = [str(value) for value in prepared.get("hard_blocks", [])]
        _stage(stages, "publication_state", "BLOCKED", reasons=reasons, fingerprint=_digest(prepared))
        return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=True, disposition="BLOCKED_PUBLICATION_STATE", hard_blocks=reasons)
    record = prepared.get("record") if isinstance(prepared.get("record"), dict) else {}
    status = _clean(record.get("status")) or "UNKNOWN"
    _stage(stages, "publication_state", status, fingerprint=_clean(record.get("dedupe_key")) or _digest(prepared))
    return _finish(story=story, channel=channel, stages=stages, artifacts=artifacts, blocked=False, disposition=status)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("media_inventory", type=Path)
    parser.add_argument("cadence_history", type=Path)
    parser.add_argument("--now", required=True, help="timezone-aware ISO-8601 instant")
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--series-decision", type=Path)
    parser.add_argument("--observed-feedback", type=Path)
    parser.add_argument("--canonical-url")
    parser.add_argument("--human-approved", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = orchestrate_channel(
        _load(args.story),
        _load(args.channel),
        _load(args.media_inventory),
        _load(args.cadence_history),
        now=args.now,
        ledger=_load(args.ledger) if args.ledger else None,
        human_approved=args.human_approved,
        canonical_url=args.canonical_url,
        series_decision=_load(args.series_decision) if args.series_decision else None,
        observed_feedback=_load(args.observed_feedback) if args.observed_feedback else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
