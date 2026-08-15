#!/usr/bin/env python3
"""End-to-end acceptance harness for LOCAL NEWS OS Social Publication & Virality Engine.

The harness composes the dependency-free social core against the real VÂLCEA CLAR
CHANNEL_CONFIG files and a deterministic in-memory shadow CIVORA instance. It makes
no network calls, reads no credential values, and performs no real publication.
Adapter confirmations and observed metrics are explicit fixtures used only to prove
state transitions, correction propagation, learning boundaries and instance isolation.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import channel_fit
import content_atomizer
import correction_propagation
import format_engine
import hook_engine
import multi_instance_isolation
import observed_metrics
import publication_state
import virality_engine
import visual_router

SCHEMA_VERSION = "1.0"
CHANNEL_PATHS = {
    "facebook": "valcea-clar/social/channels/facebook.json",
    "instagram": "valcea-clar/social/channels/instagram.json",
    "tiktok": "valcea-clar/social/channels/tiktok.json",
}


class AcceptanceError(RuntimeError):
    """Raised when one cross-engine invariant fails."""


def _check(condition: bool, code: str) -> None:
    if not condition:
        raise AcceptanceError(code)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    payload = value if isinstance(value, str) else _canonical(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_json(repo_root: Path, rel: str) -> dict[str, Any]:
    value = json.loads((repo_root / rel).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise AcceptanceError(f"JSON_NOT_OBJECT:{rel}")
    return value


def _fixture_story() -> dict[str, Any]:
    fact_kernel = {
        "subject": "temporary local traffic restriction",
        "place": "Râmnicu Vâlcea",
        "effective_window": "2026-08-17 08:00-18:00 Europe/Bucharest",
        "verified_source": "fixture municipal notice",
        "public_effect": "drivers should use the signed diversion",
    }
    return {
        "instance_id": "valcea",
        "story_id": "e2e-valcea-traffic-20260817",
        "material_fact_gate": "PASS",
        "fact_kernel_sha256": _digest(fact_kernel),
        "headline": "Trafic restricționat temporar luni pe un tronson din Râmnicu Vâlcea",
        "dek": "Restricția este programată între 08:00 și 18:00, iar șoferii vor fi deviați pe ruta semnalizată.",
        "paragraphs": [
            "Măsura este temporară și vizează intervalul anunțat în notificarea verificată.",
            "Semnalizarea din teren indică ruta alternativă pentru traficul local.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat este 08:00–18:00."},
            {"fact_id": "f2", "text": "Traficul este deviat pe ruta semnalizată."},
        ],
        "quotes": [
            {"quote_id": "q1", "text": "Respectați semnalizarea temporară din zonă."},
        ],
        "topics": ["service_journalism", "local_events", "infrastructure", "civic_updates"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo", "carousel", "short"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.95,
        "share_value": 0.82,
        "save_value": 0.72,
        "conversation_value": 0.55,
        "urgency": 0.35,
        "lifecycle_stage": "baseline",
        "handoff_channel_ids": ["valcea-facebook", "valcea-instagram", "valcea-tiktok"],
    }


def _media_inventory(story_id: str) -> dict[str, Any]:
    common = {
        "instance_id": "valcea",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "story_ids": [story_id],
        "source_type": "staff",
        "rights_basis": "owned",
    }
    return {
        "instance_id": "valcea",
        "assets": [
            {
                **common,
                "asset_id": "fixture-photo-a",
                "kind": "photo",
                "sha256": _digest("fixture-real-photo-a"),
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Semnalizare temporară de trafic într-o zonă urbană din Râmnicu Vâlcea.",
            },
            {
                **common,
                "asset_id": "fixture-photo-b",
                "kind": "photo",
                "sha256": _digest("fixture-real-photo-b"),
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Rută alternativă marcată pentru traficul local în timpul restricției.",
            },
            {
                **common,
                "asset_id": "fixture-video-a",
                "kind": "video",
                "sha256": _digest("fixture-real-video-a"),
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Secvență video reală cu semnalizarea temporară și traseul de deviere.",
            },
        ],
    }


def _published_at_for(index: int) -> datetime:
    return datetime(2026, 8, 13 + index, 10, 0, tzinfo=timezone.utc)


def _observation(
    *,
    channel: dict[str, Any],
    publication_id: str,
    remote_publication_id: str,
    story_id: str,
    product_id: str,
    native_format: str,
    index: int,
) -> dict[str, Any]:
    published_at = _published_at_for(index)
    end_at = published_at + timedelta(hours=2)
    observed_at = end_at + timedelta(minutes=5)
    collected_at = observed_at + timedelta(minutes=1)
    source = str(channel.get("metrics", {}).get("sources", [""])[0])
    return {
        "schema_version": "1.0",
        "instance_id": channel["instance_id"],
        "channel_id": channel["channel_id"],
        "platform": channel["platform"],
        "publication_id": publication_id,
        "remote_publication_id": remote_publication_id,
        "story_id": story_id,
        "product_id": product_id,
        "source": source,
        "observed_at": observed_at.isoformat().replace("+00:00", "Z"),
        "window": {
            "kind": "cumulative",
            "start_at": published_at.isoformat().replace("+00:00", "Z"),
            "end_at": end_at.isoformat().replace("+00:00", "Z"),
        },
        "publication_context": {
            "status": "PUBLISHED",
            "published_at": published_at.isoformat().replace("+00:00", "Z"),
            "native_format": native_format,
            "topic_keys": ["service_journalism", "infrastructure"],
            "series_id": None,
        },
        "metrics": {
            "reach": 1000 + index * 100,
            "shares": 42 + index * 5,
            "saves": 28 + index * 4,
            "comments": 16 + index * 3,
            "link_clicks": 24 + index * 2,
        },
        "provenance": {
            "retrieval_method": "native_export",
            "collector": "local-news-os-e2e-fixture",
            "source_payload_sha256": _digest(f"{channel['channel_id']}:{publication_id}:{index}"),
            "collected_at": collected_at.isoformat().replace("+00:00", "Z"),
        },
        "guards": {
            "observed_only": True,
            "predicted_or_estimated": False,
        },
    }


def _shadow_instance_fixture() -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    root = "shadow-civora"
    config_path = f"{root}/social/channels/facebook.json"
    registry_path = f"{root}/social/channel_registry.json"
    channel = {
        "schema_version": "1.0",
        "channel_id": "shadow-facebook",
        "instance_id": "shadow",
        "platform": "facebook",
        "status": "outbox_only",
        "publication_state": {
            "outbox_path": f"{root}/social/facebook_outbox.json",
            "state_path": f"{root}/social/facebook_state.json",
            "dedupe_by_id": True,
        },
        "zero_paid_dependency": True,
    }
    registry = {
        "schema_version": 2,
        "instance_id": "shadow",
        "canonical_domain": "shadow-civora.invalid",
        "execution_owner": "civora_site_engine",
        "scheduler": "github_actions",
        "state_owner": "repository",
        "required_active_direct_channels": [],
        "policy": {
            "verified_fact_kernel_required": True,
            "channel_native_copy_required": True,
            "cross_post_verbatim_forbidden": True,
            "idempotency_required": True,
            "deduplication_required": True,
            "correction_propagation_required": True,
            "paid_social_scheduler_required": False,
            "paid_llm_api_required": False,
            "fail_closed_on_missing_credentials": True,
            "fail_closed_on_missing_adapter": True,
        },
        "channels": [
            {
                "channel_id": "facebook",
                "status": "blocked_until_verified_adapter_and_credentials",
                "direct_publication_enabled": False,
                "publication_mode": "durable_outbox_only",
                "config": config_path,
                "adapter": None,
                "outbox": f"{root}/social/facebook_outbox.json",
                "state": f"{root}/social/facebook_state.json",
                "credentials": None,
            }
        ],
    }
    entry = {
        "instance_id": "shadow",
        "canonical_domain": "shadow-civora.invalid",
        "instance_root": root,
        "channel_registry": registry_path,
        "credential_namespace": "SHADOW_",
        "metrics_namespace": "shadow",
        "correction_target_namespace": "shadow:",
        "resource_namespaces": {
            "outbox": f"{root}/social",
            "state": f"{root}/social",
            "media": f"{root}/social/photos",
            "metrics": f"{root}/social/metrics",
            "corrections": f"{root}/social/corrections",
        },
    }
    return entry, {registry_path: registry, config_path: channel}


def _fleet_acceptance(repo_root: Path) -> dict[str, Any]:
    runtime = _load_json(repo_root, "local-news-os/social/social_runtime_registry.json")
    shadow_entry, virtual_files = _shadow_instance_fixture()
    runtime = copy.deepcopy(runtime)
    runtime.setdefault("instances", []).append(shadow_entry)

    def exists(rel: str) -> bool:
        return rel in virtual_files or (repo_root / rel).is_file()

    def load(rel: str) -> dict[str, Any]:
        if rel in virtual_files:
            return copy.deepcopy(virtual_files[rel])
        return _load_json(repo_root, rel)

    positive = multi_instance_isolation.validate_runtime(runtime, load_json=load, file_exists=exists)
    _check(positive.get("status") == "PASS", "FLEET_ISOLATION_POSITIVE_FAILED")
    _check({row.get("instance_id") for row in positive.get("instances", [])} == {"shadow", "valcea"}, "FLEET_INSTANCE_SET")

    collision = copy.deepcopy(runtime)
    collision["instances"][-1]["metrics_namespace"] = "valcea"
    negative = multi_instance_isolation.validate_runtime(collision, load_json=load, file_exists=exists)
    _check(negative.get("status") == "BLOCKED", "FLEET_NEGATIVE_PROBE_NOT_BLOCKED")
    _check(any(str(error).startswith("METRICS_NAMESPACE_COLLISION:") for error in negative.get("errors", [])), "FLEET_NEGATIVE_PROBE_REASON")
    return {
        "positive_status": positive["status"],
        "instance_ids": [row["instance_id"] for row in positive["instances"]],
        "credential_values_exposed": positive["guards"]["credential_values_exposed"],
        "negative_collision_probe_status": negative["status"],
        "negative_collision_probe_errors": [
            error for error in negative.get("errors", []) if str(error).startswith("METRICS_NAMESPACE_COLLISION:")
        ],
    }


def run_acceptance(repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    story = _fixture_story()
    atom_bundle = content_atomizer.atomize_story(story)
    _check(atom_bundle.get("blocked") is False, "ATOMIZER_BLOCKED")
    _check(int(atom_bundle.get("atom_count", 0)) >= 6, "ATOMIZER_TOO_FEW_ATOMS")

    inventory = _media_inventory(story["story_id"])
    channel_reports: dict[str, Any] = {}
    published_ledgers: list[dict[str, Any]] = []
    hook_texts: set[str] = set()
    product_ids: set[str] = set()
    native_formats: set[str] = set()
    publication_ids: set[str] = set()

    for platform, rel in CHANNEL_PATHS.items():
        channel = _load_json(repo_root, rel)
        _check(channel.get("instance_id") == story["instance_id"], f"{platform}:INSTANCE")
        _check(channel.get("status") == "active", f"{platform}:CHANNEL_NOT_ACTIVE")
        _check(channel.get("zero_paid_dependency") is True, f"{platform}:PAID_DEPENDENCY")

        fit = channel_fit.score_story(story, channel)
        _check(fit.get("blocked") is False and fit.get("recommendation") in {"primary", "eligible"}, f"{platform}:FIT")

        hook = hook_engine.build_hook(atom_bundle, channel, fit)
        _check(hook.get("blocked") is False and isinstance(hook.get("hook"), dict), f"{platform}:HOOK")

        formatted = format_engine.build_native_product(atom_bundle, hook, channel)
        _check(formatted.get("blocked") is False and isinstance(formatted.get("product"), dict), f"{platform}:FORMAT")
        product = formatted["product"]

        visual = visual_router.bind_visuals(formatted, channel, inventory)
        _check(visual.get("blocked") is False and isinstance(visual.get("binding"), dict), f"{platform}:VISUAL")
        binding = visual["binding"]
        _check(binding.get("provenance_complete") is True, f"{platform}:PROVENANCE")
        _check(binding.get("reuse_rights_complete") is True, f"{platform}:RIGHTS")
        _check(binding.get("synthetic_media_used") is False, f"{platform}:SYNTHETIC_MEDIA")

        virality = virality_engine.score_virality(story, channel, fit, hook, formatted, visual=visual)
        _check(virality.get("blocked") is False, f"{platform}:VIRALITY")
        _check(virality.get("guards", {}).get("zero_paid_dependency") is True, f"{platform}:VIRALITY_PAID")

        prepared = publication_state.prepare_publication(formatted, virality, channel, human_approved=True)
        _check(prepared.get("blocked") is False, f"{platform}:PUBLICATION_PREP")
        _check(prepared.get("record", {}).get("status") == "READY", f"{platform}:NOT_READY")
        publication_id = prepared["record"]["publication_id"]

        confirmed = publication_state.apply_attempt(
            prepared["ledger"],
            publication_id,
            "2026-08-15T10:00:00Z",
            success=True,
            remote_publication_id=f"fixture-remote:{platform}:1",
        )
        _check(confirmed.get("blocked") is False and confirmed.get("record", {}).get("status") == "PUBLISHED", f"{platform}:PUBLISH_CONFIRM")
        published_ledgers.append(confirmed["ledger"])

        observations = []
        for index in range(3):
            current = index == 2
            observations.append(
                _observation(
                    channel=channel,
                    publication_id=publication_id if current else f"fixture-history:{platform}:{index}",
                    remote_publication_id=confirmed["record"]["remote_publication_id"] if current else f"fixture-history-remote:{platform}:{index}",
                    story_id=story["story_id"] if current else f"fixture-history-story:{platform}:{index}",
                    product_id=product["product_id"] if current else f"fixture-history-product:{platform}:{index}",
                    native_format=product["native_format"],
                    index=index,
                )
            )
        feedback = observed_metrics.build_feedback(channel, observations, min_samples=3)
        _check(feedback.get("status") == "READY", f"{platform}:LEARNING_NOT_READY")
        _check(feedback.get("learning_samples") == 3, f"{platform}:LEARNING_SAMPLE_COUNT")
        _check(not feedback.get("rejected_observations"), f"{platform}:LEARNING_REJECTED")
        _check(feedback.get("application_policy", {}).get("mode") == "ADVISORY_ONLY", f"{platform}:LEARNING_POLICY")

        hook_text = str(hook["hook"]["text"])
        hook_texts.add(hook_text)
        product_ids.add(product["product_id"])
        native_formats.add(product["native_format"])
        publication_ids.add(publication_id)

        channel_reports[platform] = {
            "channel_id": channel["channel_id"],
            "fit_score": fit["score"],
            "hook_text": hook_text,
            "native_format": product["native_format"],
            "product_id": product["product_id"],
            "visual_status": binding["status"],
            "selected_asset_ids": binding["selected_asset_ids"],
            "provenance_complete": binding["provenance_complete"],
            "reuse_rights_complete": binding["reuse_rights_complete"],
            "publication_id": publication_id,
            "publication_status": confirmed["record"]["status"],
            "remote_publication_id": confirmed["record"]["remote_publication_id"],
            "learning_status": feedback["status"],
            "learning_samples": feedback["learning_samples"],
            "feedback_fingerprint_sha256": feedback["feedback_fingerprint_sha256"],
        }

    _check(len(channel_reports) == 3, "THREE_SOCIAL_PUBLICATIONS_REQUIRED")
    _check(len(hook_texts) == 3, "HOOKS_NOT_CHANNEL_DISTINCT")
    _check(native_formats == {"single_photo", "carousel", "short"}, "NATIVE_FORMATS_NOT_DISTINCT")
    _check(len(product_ids) == 3, "PRODUCT_IDS_NOT_CHANNEL_DISTINCT")
    _check(len(publication_ids) == 3, "PUBLICATION_STATE_NOT_INDEPENDENT")

    foreign_ledger = publication_state.empty_ledger("shadow", "shadow-facebook", "facebook")
    correction = {
        "instance_id": "valcea",
        "story_id": "e2e-valcea-traffic-20260817-correction",
        "correction": True,
        "verified": True,
        "editorial_gate": "PASS",
        "fact_kernel_sha256": _digest("corrected-e2e-fact-kernel"),
        "corrects_story_id": story["story_id"],
        "zero_paid_dependency": True,
    }
    correction_result = correction_propagation.propagate_correction(correction, [*published_ledgers, foreign_ledger])
    correction_actions = [item for item in correction_result.get("actions", []) if item.get("action") == "CORRECT_PUBLISHED_NATIVE"]
    _check(correction_result.get("blocked") is False, "CORRECTION_BLOCKED")
    _check(correction_result.get("affected_count") == 3, "CORRECTION_AFFECTED_COUNT")
    _check(len(correction_actions) == 3, "CORRECTION_NATIVE_ACTION_COUNT")
    _check(len(correction_result.get("ignored_foreign_ledgers", [])) == 1, "CORRECTION_FOREIGN_INSTANCE_NOT_ISOLATED")
    _check(all(item.get("native_regeneration", {}).get("reuse_prior_copy") is False for item in correction_actions), "CORRECTION_COPY_REUSE")

    fleet = _fleet_acceptance(repo_root)
    _check(fleet["credential_values_exposed"] is False, "FLEET_SECRET_EXPOSURE")

    report = {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS",
        "fixture_id": "local-news-os-social-e2e-v1",
        "instance_id": story["instance_id"],
        "story_id": story["story_id"],
        "fact_kernel_sha256": story["fact_kernel_sha256"],
        "website_sibling": {
            "surface": "website",
            "canonical_domain": "valceaclar.ro",
            "role": "durable_archive_and_evidence_surface",
            "independent_publication": True,
            "shared_fact_kernel_sha256": story["fact_kernel_sha256"],
            "social_copy_is_source_of_truth": False,
        },
        "atom_bundle": {
            "source_fingerprint_sha256": atom_bundle["source_fingerprint_sha256"],
            "atom_count": atom_bundle["atom_count"],
        },
        "social_publications": channel_reports,
        "distinctness": {
            "distinct_hook_count": len(hook_texts),
            "native_formats": sorted(native_formats),
            "distinct_product_count": len(product_ids),
            "distinct_publication_state_count": len(publication_ids),
            "verbatim_cross_platform_reuse_allowed": False,
        },
        "correction_propagation": {
            "affected_count": correction_result["affected_count"],
            "native_action_count": len(correction_actions),
            "action_channel_ids": sorted(item["channel_id"] for item in correction_actions),
            "foreign_instance_ledgers_ignored": len(correction_result["ignored_foreign_ledgers"]),
            "native_regeneration_required": True,
        },
        "multi_instance_isolation": fleet,
        "guards": {
            "real_media_metadata_required": True,
            "visual_provenance_required": True,
            "observed_metrics_only": True,
            "learning_advisory_only": True,
            "corrections_propagated": True,
            "instance_isolation": True,
            "credential_values_exposed": False,
            "zero_paid_dependency": True,
            "network_calls_performed": False,
            "real_publication_performed": False,
        },
    }
    report["acceptance_fingerprint_sha256"] = _digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run_acceptance(args.repo_root)
    except AcceptanceError as exc:
        print(json.dumps({"schema_version": SCHEMA_VERSION, "status": "BLOCKED", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
