#!/usr/bin/env python3
"""Preview-only Threads editorial packaging v1 for VÂLCEA CLAR.

Threads is treated as a conversation-native, text-first sister publication. The
same verified story kernel is rewritten into concise observations/explainers,
not copied from X, Facebook or Instagram. This module makes no network calls.

Continuous-publication note: the public edition is intentionally compact and
omits fact kernels.  Threads therefore rehydrates decision-approved ids from the
full Editorial Writer registry before applying the canonical story-ready gate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import build_outbox_only_story_products as base
import story_social_policy as social_policy
import generate_edition

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
PREVIEW = VC / "social" / "previews" / "threads-v1"
MAX_INTERNAL_CHARS = 470


def compact(text: str, limit: int = MAX_INTERNAL_CHARS) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return (cut or value[: limit - 1]).rstrip(" ,.;:") + "…"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def money_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        if number >= 1_000_000:
            shown = f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mil. lei"
        else:
            shown = f"{int(round(number)):,}".replace(",", ".") + " lei"
        if shown not in values:
            values.append(shown)
    return values


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    return re.sub(r"\s+", " ", value).strip(" +") or None


def interest_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    ok, reason = social_policy.social_interest_gate(story)
    if not ok:
        reason_map = {
            "thin_title_date_source_only": "threads_conversation_gate_thin_title_date_source_only",
            "insufficient_context": "threads_conversation_gate_insufficient_context",
            "transient_service_update_expired": "threads_transient_service_update_expired",
        }
        return False, reason_map.get(str(reason), f"threads_social_gate:{reason}")
    return True, None


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason = interest_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "threads-editorial-v1.1",
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    posts: list[str] = []
    hook_family = "clear_observation"
    format_family = "text_update"

    if "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        posts = [
            "Luminos Fest a fost programat în Zăvoi în 15–16 august 2026, cu intrare liberă și activități orientate spre familii și copii.",
            "Lampioanele plutitoare au fost anunțate cu rezervare separată, online. Contextul și sursele verificate sunt în articol: " + base.canonical(story),
        ]
        hook_family = "local_utility"
        format_family = "conversation_update"
    elif "olănești" in lower and money:
        contract = money[1] if len(money) > 1 else None
        actor = pair or "asocierea câștigătoare"
        posts = [
            "44,37 mil. lei este valoarea totală aprobată pentru proiectul care include un pod nou peste Olănești, în zona Omniasig.",
            "Ce știm: documentația SMIS 334436 descrie un pod exclusiv pietonal și ciclist. "
            + (f"Contractul principal a fost atribuit {actor}, la {contract} fără TVA." if contract else f"Contractul principal a fost atribuit {actor}."),
            "Ce nu știm încă: documentele publice nu permit atribuirea lucrărilor vizibile unei anumite firme din asociere sau unui subcontractant. Sursele: " + base.canonical(story),
        ]
        hook_family = "short_explainer"
        format_family = "explanatory_thread"
    elif str(story.get("id") or "").startswith("rm-valcea-hcl-"):
        opening = dek or headline
        posts = [
            compact(headline, 390),
            compact(paragraphs[1] if len(paragraphs) > 1 else opening, 390),
            compact((paragraphs[2] if len(paragraphs) > 2 else "") + " Context și sursa oficială: " + base.canonical(story), 470),
        ]
        hook_family = "council_decision_explained"
        format_family = "explanatory_thread"
    elif money:
        posts.append(f"Un număr care merită context: {money[0]}. {compact(headline, 300)}")
        if dek:
            posts.append(compact(dek, 360))
        posts.append("Documentele și contextul complet: " + base.canonical(story))
        hook_family = "key_number_context"
        format_family = "explanatory_thread"
    else:
        opening = dek or headline
        posts.append(compact(opening, 390))
        if paragraphs:
            posts.append(compact(paragraphs[0], 390))
        posts.append("Context și surse: " + base.canonical(story))

    posts = [compact(post) for post in posts if str(post).strip()]
    if len(posts) > 4:
        posts = posts[:3] + [posts[-1]]
    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "native_api_fail_closed",
        "native_format": "thread" if len(posts) > 1 else "text",
        "format_family": format_family,
        "hook_family": hook_family,
        "posts": posts,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "conversation_native": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "max_internal_chars_per_post": MAX_INTERNAL_CHARS,
        "rendering_version": "threads-editorial-v1.1",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def build() -> dict[str, Any]:
    decision = base.load(base.DECISION, {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"story_ids": []})
    allowed_order = [str(value) for value in (event.get("story_ids") or decision.get("publishable_story_ids") or []) if str(value).strip()]

    registry, _ = generate_edition.merged_registry()
    by_id = {
        str(item.get("id")): item
        for item in registry.get("facts") or []
        if isinstance(item, dict) and item.get("id")
    }
    stories = [
        by_id[story_id]
        for story_id in allowed_order
        if story_id in by_id and base.story_ready(by_id[story_id])[0]
    ]
    products = [package(story) for story in stories]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.1-preview",
        "platform": "threads",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "story_materialization_source": "decision_approved_full_editorial_writer_products",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    thin = {"id": "thin", "headline": "Eveniment", "dek": "15 august", "paragraphs": [], "material_fact_gate": "PASS_DATE_ONLY"}
    assert package(thin)["status"] == "HOLD"
    hcl = {
        "id": "rm-valcea-hcl-306-20260814",
        "section": "SERVICII",
        "headline": "HCL 306/2026: prețul energiei termice",
        "dek": "Hotărârea apare în registrul oficial și este explicată în limitele documentelor disponibile.",
        "paragraphs": [
            "Registrul listează hotărârea.",
            "În limbaj curent, obiectul privește aprobarea prețului energiei termice.",
            "Titlul nu indică valoarea prețului sau subvențiile.",
        ],
        "material_fact_gate": "PASS_EXPLAINER_ONLY",
    }
    hcl_product = package(hcl)
    assert hcl_product["status"] == "READY"
    assert hcl_product["hook_family"] == "council_decision_explained"
    sample = {
        "id": "olanesti-test",
        "section": "INVESTIGAȚII",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436.",
        "paragraphs": [
            "Documentația include un pod exclusiv pietonal și ciclist.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
        "material_fact_gate": "PASS_EXPLAINER_ONLY",
    }
    product = package(sample)
    assert product["status"] == "READY"
    assert product["format_family"] == "explanatory_thread"
    assert "Ralunic + Dimex-2000 Company" in " ".join(product["posts"])
    assert all(len(post) <= MAX_INTERNAL_CHARS for post in product["posts"])
    assert not any("#" in post for post in product["posts"])
    print("VÂLCEA CLAR Threads editorial v1.1 self-test: PASS")
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
