#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR LinkedIn editorial v1.1 into canonical outbox/state.

READY products include a deterministic original evidence-card asset generated
from the verified fact kernel. Outbox-only: no LinkedIn network access is
claimed or used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

import linkedin_editorial_v1 as editorial
from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "linkedin_outbox.json"
STATE = VC / "social" / "linkedin_state.json"
RUNTIME = VC / "site" / "runtime" / "media" / "social" / "editorial" / "linkedin"


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def visual_alt_text(product: dict[str, Any]) -> str:
    visual = product.get("visual") if isinstance(product.get("visual"), dict) else {}
    parts = [
        str(visual.get("kicker") or "").strip(),
        str(visual.get("metric") or "").strip(),
        str(visual.get("headline") or product.get("hook") or "").strip(),
    ]
    for fact in visual.get("facts", []) if isinstance(visual.get("facts"), list) else []:
        if isinstance(fact, dict):
            parts.append(f"{str(fact.get('label') or '').strip()}: {str(fact.get('text') or '').strip()}".strip(": "))
    return "VÂLCEA CLAR. " + " ".join(part for part in parts if part)[:900]


def render_asset(product: dict[str, Any], runtime: Path = RUNTIME) -> dict[str, Any]:
    if product.get("status") != "READY":
        raise ValueError("LinkedIn visual asset may only be rendered for READY product")
    fingerprint = str(product.get("product_fingerprint_sha256") or "")
    if len(fingerprint) != 64:
        raise ValueError("LinkedIn product fingerprint missing")
    runtime.mkdir(parents=True, exist_ok=True)
    rendered = runtime / f"{product['story_id']}-linkedin-{fingerprint[:12]}.jpg"
    editorial.render_card(product, rendered)
    asset = {
        "kind": "editorial_evidence_card",
        "synthetic": False,
        "story_id": str(product["story_id"]),
        "platform": "linkedin",
        "renderer": "linkedin-editorial-v1.1",
        "rendered_path": str(rendered.relative_to(ROOT)),
        "sha256": sha256(rendered),
        "product_fingerprint_sha256": fingerprint,
        "rights_basis": "original_editorial_layout",
        "source_fact_kernel": "canonical_verified_story",
        "source_label": str(product.get("visual", {}).get("source_label") or "DOCUMENTE ȘI SURSE · valceaclar.ro"),
        "alt_text": visual_alt_text(product),
    }
    asset["asset_fingerprint_sha256"] = editorial.digest(asset)
    validate_asset(asset)
    return asset


def validate_asset(asset: dict[str, Any]) -> None:
    if asset.get("kind") != "editorial_evidence_card" or asset.get("synthetic") is not False:
        raise ValueError("invalid LinkedIn editorial evidence card")
    if asset.get("renderer") != "linkedin-editorial-v1.1":
        raise ValueError("LinkedIn renderer lineage drift")
    if asset.get("rights_basis") != "original_editorial_layout":
        raise ValueError("LinkedIn editorial rights basis missing")
    if asset.get("source_fact_kernel") != "canonical_verified_story":
        raise ValueError("LinkedIn fact-kernel lineage missing")
    candidate = dict(asset)
    supplied = str(candidate.pop("asset_fingerprint_sha256", ""))
    if supplied != editorial.digest(candidate):
        raise ValueError("LinkedIn asset fingerprint mismatch")
    path = ROOT / str(asset.get("rendered_path") or "")
    if not path.is_file() or sha256(path) != str(asset.get("sha256") or ""):
        raise ValueError("LinkedIn rendered bytes/hash mismatch")
    if not str(asset.get("source_label") or "").startswith("DOCUMENTE ȘI SURSE"):
        raise ValueError("LinkedIn source label missing")


def canonical_item(product: dict[str, Any], asset: dict[str, Any] | None = None) -> dict[str, Any]:
    story_id = str(product["story_id"])
    common = {
        "id": f"linkedin-story-{story_id}",
        "story_id": story_id,
        "publication_mode": "durable_outbox_only",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "linkedin_direct_access_not_configured",
        "generation_mode": "linkedin_editorial_v1_1",
        "identity": product_identity("linkedin"),
        "edition_gate": False,
    }
    if product.get("status") == "HOLD":
        if asset is not None:
            raise ValueError("LinkedIn HOLD product must not carry visual asset")
        return {
            **common,
            "status": "hold",
            "native_format": "text",
            "format_family": "linkedin_hold",
            "hold_reason": product.get("reason"),
        }
    if asset is None:
        raise ValueError("LinkedIn READY product requires deterministic visual asset")
    validate_asset(asset)
    return {
        **common,
        "status": "outbox_ready",
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "hook_family": product["hook_family"],
        "hook": product["hook"],
        "body": product["body"],
        "professional_context": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "visual_asset": asset,
    }


def build() -> dict[str, Any]:
    preview = editorial.build()
    products: list[dict[str, Any]] = []
    for product in preview.get("products", []):
        if not isinstance(product, dict):
            continue
        asset = render_asset(product) if product.get("status") == "READY" else None
        products.append(canonical_item(product, asset))
    outbox = load(OUTBOX, {
        "schema_version": "1.0",
        "platform": "linkedin",
        "publication_model": "continuous_story_first",
        "items": [],
    })
    existing = {
        str(item.get("id")): item
        for item in outbox.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    outbox["schema_version"] = "1.2"
    outbox["platform"] = "linkedin"
    outbox["publication_model"] = "continuous_story_first"
    outbox["editorial_product_version"] = "linkedin-editorial-v1.1"
    outbox["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    outbox["edition_recaps_are_publication_gates"] = False
    outbox["items"] = list(existing.values())
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "linkedin",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state["schema_version"] = "1.2"
    state["platform"] = "linkedin"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["editorial_product_version"] = "linkedin-editorial-v1.1"
    state["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    state["direct_publication_enabled"] = False
    state["direct_publication_blocker"] = "linkedin_direct_access_not_configured"
    state.setdefault("published", {})
    state.setdefault("failures", {})
    write(STATE, state)

    return {
        "status": "PASS",
        "platform": "linkedin",
        "editorial_product_version": "linkedin-editorial-v1.1",
        "products": len(products),
        "ready": sum(1 for item in products if item.get("status") == "outbox_ready"),
        "held": sum(1 for item in products if item.get("status") == "hold"),
        "visual_assets": sum(1 for item in products if isinstance(item.get("visual_asset"), dict)),
        "direct_publication_enabled": False,
    }


def self_test() -> int:
    sample = {
        "id": "x",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436 de infrastructură cu impact local documentat.",
        "paragraphs": [
            "Documentația include un pod exclusiv pietonal și ciclist în zona Omniasig.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
        "material_fact_gate": "PASS",
    }
    product = editorial.package(sample)
    assert product["status"] == "READY"
    with tempfile.TemporaryDirectory() as raw:
        asset = render_asset(product, Path(raw))
        item = canonical_item(product, asset)
        assert item["status"] == "outbox_ready"
        assert item["native_format"] == "image_plus_text"
        assert item["direct_publication_enabled"] is False
        assert item["generation_mode"] == "linkedin_editorial_v1_1"
        assert item["identity"]["channel_id"] == "valcea-linkedin"
        assert item["identity"]["presentation"]["document_or_data_visual_preferred_over_decorative_photo"] is True
        assert item["visual_asset"]["kind"] == "editorial_evidence_card"
        assert item["visual_asset"]["synthetic"] is False
        assert item["visual_asset"]["source_fact_kernel"] == "canonical_verified_story"
        assert (ROOT / item["visual_asset"]["rendered_path"]).is_file()
    held = canonical_item({"story_id":"y","status":"HOLD","reason":"thin","canonical_url":"https://valceaclar.ro/stiri/y/"})
    assert held["status"] == "hold" and held["hold_reason"] == "thin"
    assert held["identity"]["product_role"] == "decision_maker_publication"
    print("VÂLCEA CLAR LinkedIn editorial materializer v1.1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
