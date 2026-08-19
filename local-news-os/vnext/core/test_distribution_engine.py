#!/usr/bin/env python3
"""Regression coverage for the site-owned vNext Distribution Engine."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path

from distribution_engine import (
    DistributionError,
    build_adapter_request,
    delivery_record,
    ensure_distribution_schema,
    list_deliveries,
    materialize_story_distribution,
    record_delivery_attempt,
    record_remote_receipt,
    validate_channels_pack,
)
from media_intelligence import (
    DEFAULT_USAGE_SCOPES,
    RIGHTS_BASES,
    SPECIFICITY_ORDER,
    bind_media_asset,
    ensure_media_schema,
    register_media_asset,
    resolve_story_media,
)
from runtime_store import connect, create_story, initialize, register_instance, utc_now
from site_publication import ensure_publication_schema


def stable(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def manifest(instance_id: str, domain: str, marker: str) -> dict:
    return {
        "instance_id": instance_id,
        "publication": {"canonical_domain": domain},
        "config_sha256": marker * 64,
        "runtime": {"owner": "site_application", "repository_runtime_state_enabled": False},
    }


def media_policy(instance_id: str) -> dict:
    return {
        "schema_version": "2.0",
        "pack_type": "photos",
        "instance_id": instance_id,
        "resolver_policy": {
            "allowed_usage_scopes": sorted(DEFAULT_USAGE_SCOPES),
            "allowed_rights_bases": sorted(RIGHTS_BASES),
            "specificity_order": list(SPECIFICITY_ORDER),
            "fallback": "EDITORIAL_CARD",
        },
        "assets": [],
    }


def channels(instance_id: str) -> dict:
    return {
        "schema_version": "2.0",
        "pack_type": "channels",
        "instance_id": instance_id,
        "channels": [
            {
                "id": "facebook",
                "mode": "direct_capable",
                "enabled": True,
                "adapter_id": "meta_facebook",
                "product_type": "LINK_POST",
                "media_usage_scope": "SOCIAL_FACEBOOK",
                "require_visual": False,
                "account": {"id_ref": "EXAMPLE_FACEBOOK_ACCOUNT_ID"},
                "credential_refs": {"access_token": "EXAMPLE_META_ACCESS_TOKEN"},
                "apply_gate_ref": "EXAMPLE_FACEBOOK_LIVE_ENABLED",
            },
            {
                "id": "instagram",
                "mode": "direct_capable",
                "enabled": True,
                "adapter_id": "meta_instagram",
                "product_type": "SINGLE_VISUAL",
                "media_usage_scope": "SOCIAL_INSTAGRAM",
                "require_visual": True,
                "account": {"id_ref": "EXAMPLE_INSTAGRAM_ACCOUNT_ID"},
                "credential_refs": {"access_token": "EXAMPLE_META_ACCESS_TOKEN"},
                "apply_gate_ref": "EXAMPLE_INSTAGRAM_LIVE_ENABLED",
            },
        ],
    }


def source(label: str) -> list[dict[str, str]]:
    return [{
        "source_url": f"https://example.invalid/{label}",
        "evidence_fingerprint": hashlib.sha256(label.encode()).hexdigest(),
        "observed_at": "2026-08-19T12:00:00Z",
    }]


def published_story(conn, instance_id: str, story_id: str, headline: str) -> None:
    create_story(
        conn,
        instance_id=instance_id,
        story_id=story_id,
        fingerprint=stable([instance_id, story_id]),
        engine_version="p14-regression",
        headline=headline,
    )
    now = utc_now()
    snapshot = {
        "story_id": story_id,
        "headline": headline,
        "dek": "Verified grounded summary.",
        "body_blocks": [{"text": "Verified fact."}],
        "factbox": [],
        "context": {},
        "source_references": [],
        "follow_up": {},
        "section": "LOCAL",
        "tags": [],
    }
    content_fp = stable(snapshot)
    qa_id = f"qa-{story_id}"
    publication_id = f"pub-{story_id}"
    conn.execute("UPDATE stories SET state='PUBLISHED',canonical_path=?,updated_at=? WHERE instance_id=? AND story_id=?", (f"/story/{story_id}/", now, instance_id, story_id))
    conn.execute(
        """
        INSERT INTO editorial_qa_decisions(
            instance_id,decision_id,story_id,draft_fingerprint,draft_revision,decision_fingerprint,
            editorial_class,outcome,gates_json,duplicate_story_id,publication_authority,created_at
        ) VALUES (?,?,?,?,1,?,'LOW_RISK','QA_PASSED','{}',NULL,'NONE',?)
        """,
        (instance_id, qa_id, story_id, f"draft-{story_id}", stable([story_id, "qa"]), now),
    )
    conn.execute(
        """
        INSERT INTO story_publications(
            instance_id,story_id,publication_id,canonical_path,current_revision,current_content_fingerprint,published_at,updated_at
        ) VALUES (?,?,?,?,1,?,?,?)
        """,
        (instance_id, story_id, publication_id, f"/story/{story_id}/", content_fp, now, now),
    )
    conn.execute(
        """
        INSERT INTO publication_revisions(
            instance_id,publication_revision_id,publication_id,story_id,revision,qa_decision_id,
            draft_fingerprint,content_fingerprint,snapshot_json,created_at
        ) VALUES (?,?,?,?,1,?,?,?,?,?)
        """,
        (instance_id, f"pubrev-{story_id}", publication_id, story_id, qa_id, f"draft-{story_id}", content_fp, json.dumps(snapshot, sort_keys=True), now),
    )
    conn.commit()


def attach_photo(conn, instance_id: str, story_id: str) -> None:
    raw = {
        "asset_id": f"photo-{story_id}",
        "media_kind": "PHOTO",
        "storage_uri": f"https://media.invalid/{story_id}.jpg",
        "source_type": "USER_OWNED",
        "rights_basis": "USER_OWNED",
        "license_code": "OWNED",
        "credit": "Example newsroom",
        "rights_evidence": f"OWNERSHIP:{story_id}",
        "synthetic": False,
        "depicts_real_scene": True,
        "freshness_class": "EVERGREEN",
        "usage_scopes": ["SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM"],
        "metadata": {"alt": "Verified real scene"},
        "content_fingerprint": hashlib.sha256(f"photo:{story_id}".encode()).hexdigest(),
        "status": "READY",
        "provenance": source(f"photo-{story_id}"),
    }
    asset, _ = register_media_asset(
        conn,
        instance_id=instance_id,
        asset=raw,
        media_policy=media_policy(instance_id),
        engine_version="p14-regression",
    )
    bind_media_asset(
        conn,
        instance_id=instance_id,
        asset_id=asset["asset_id"],
        target_type="STORY",
        target_id=story_id,
        specificity_class="SUBJECT_DIRECT",
        provenance=source(f"binding-{story_id}"),
        engine_version="p14-regression",
    )
    for scope in ("SOCIAL_FACEBOOK", "SOCIAL_INSTAGRAM"):
        resolve_story_media(
            conn,
            instance_id=instance_id,
            story_id=story_id,
            usage_scope=scope,
            media_policy=media_policy(instance_id),
            engine_version="p14-regression",
        )


def run() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "runtime.sqlite3"
        conn = connect(db)
        initialize(conn)
        ensure_publication_schema(conn)
        ensure_media_schema(conn)
        ensure_distribution_schema(conn)
        register_instance(conn, manifest("alpha-local", "alpha.invalid", "a"), engine_version="p14-regression")
        register_instance(conn, manifest("beta-local", "beta.invalid", "b"), engine_version="p14-regression")
        published_story(conn, "alpha-local", "story-one", "Verified local story")
        published_story(conn, "beta-local", "story-one", "Independent second instance")
        attach_photo(conn, "alpha-local", "story-one")

        products = materialize_story_distribution(
            conn,
            instance_id="alpha-local",
            story_id="story-one",
            channels_pack=channels("alpha-local"),
            engine_version="p14-regression",
        )
        by_channel = {item["channel"]["id"]: item for item in products}
        assert by_channel["facebook"]["delivery"]["status"] == "READY"
        assert by_channel["instagram"]["delivery"]["status"] == "READY"
        assert by_channel["instagram"]["product"]["payload"]["media"]["asset"]["synthetic"] is False

        repeated = materialize_story_distribution(
            conn,
            instance_id="alpha-local",
            story_id="story-one",
            channels_pack=channels("alpha-local"),
            engine_version="p14-regression",
        )
        assert [x["product"]["product_id"] for x in repeated] == [x["product"]["product_id"] for x in products]
        assert len(list_deliveries(conn, instance_id="alpha-local")) == 2

        fb_delivery = by_channel["facebook"]["delivery"]["delivery_id"]
        request = build_adapter_request(conn, instance_id="alpha-local", delivery_id=fb_delivery, channels_pack=channels("alpha-local"))
        wire = json.dumps(request, sort_keys=True)
        assert request["adapter_id"] == "meta_facebook"
        assert "EXAMPLE_META_ACCESS_TOKEN" in wire
        assert "real-token-value" not in wire
        attempt = record_delivery_attempt(
            conn,
            instance_id="alpha-local",
            delivery_id=fb_delivery,
            adapter_id="meta_facebook",
            outcome="SUCCESS_UNVERIFIED",
            response={"candidate_external_id": "remote-1"},
            engine_version="p14-regression",
        )
        assert attempt["status"] == "DELIVERING" and not bool(attempt["remote_verified"])
        record = delivery_record(conn, instance_id="alpha-local", delivery_id=fb_delivery)
        assert record["delivery"]["status"] != "PUBLISHED"
        live = record_remote_receipt(
            conn,
            instance_id="alpha-local",
            delivery_id=fb_delivery,
            external_object_id="remote-1",
            verified=True,
            verification_method="provider_get_by_id",
            evidence={
                "provider_readback_fingerprint": hashlib.sha256(b"remote-readback").hexdigest(),
                "story_identity_confirmed": True,
            },
            verified_at="2026-08-19T15:00:00Z",
            engine_version="p14-regression",
            remote_url="https://social.invalid/remote-1",
        )
        assert live["status"] == "PUBLISHED" and bool(live["remote_verified"])

        attempt_id = delivery_record(conn, instance_id="alpha-local", delivery_id=fb_delivery)["attempts"][0]["attempt_id"]
        try:
            conn.execute("UPDATE delivery_attempts SET error='tamper' WHERE instance_id=? AND attempt_id=?", ("alpha-local", attempt_id))
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError("append-only delivery attempt was mutable")
        conn.rollback()

        beta_products = materialize_story_distribution(
            conn,
            instance_id="beta-local",
            story_id="story-one",
            channels_pack={
                "schema_version": "2.0",
                "pack_type": "channels",
                "instance_id": "beta-local",
                "channels": [{"id": "archive-feed", "mode": "outbox_only", "enabled": True, "adapter_id": "outbox_only", "product_type": "TEXT_POST"}],
            },
            engine_version="p14-regression",
        )
        assert beta_products[0]["delivery"]["status"] == "HELD"
        assert len(list_deliveries(conn, instance_id="beta-local")) == 1
        assert len(list_deliveries(conn, instance_id="alpha-local")) == 2
        try:
            build_adapter_request(
                conn,
                instance_id="beta-local",
                delivery_id=beta_products[0]["delivery"]["delivery_id"],
                channels_pack={
                    "schema_version": "2.0",
                    "pack_type": "channels",
                    "instance_id": "beta-local",
                    "channels": [{"id": "archive-feed", "mode": "outbox_only", "enabled": True, "adapter_id": "outbox_only", "product_type": "TEXT_POST"}],
                },
            )
        except DistributionError as exc:
            assert "direct-capable" in str(exc)
        else:
            raise AssertionError("outbox-only delivery reached direct adapter boundary")

        bad = channels("alpha-local")
        bad["channels"][0]["credential_refs"]["access_token"] = "actual-secret-value"
        try:
            validate_channels_pack(bad, instance_id="alpha-local")
        except DistributionError:
            pass
        else:
            raise AssertionError("credential value accepted instead of runtime reference")
        conn.close()
    print("LOCAL_NEWS_OS_VNEXT_DISTRIBUTION_REGRESSION_PASS")


if __name__ == "__main__":
    run()
