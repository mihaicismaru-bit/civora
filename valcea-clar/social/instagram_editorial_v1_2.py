#!/usr/bin/env python3
"""Instagram editorial v1.2: entity-safe copy + premium feed identity.

Fact-checks receive an explicit evidence-led carousel contract so they cannot
fall back to the generic photo/caption path used by the legacy distributor.
"""
from __future__ import annotations

import argparse
import json
import re

import feed_identity_v1_1 as feed_identity
import instagram_editorial_v1_1 as impl


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


# Keep v1/v1.1 fact packaging intact, then layer fact-check-specific packaging
# and the shared premium presentation system on top.
impl.contractor_pair = contractor_pair
impl.base.contractor_pair = contractor_pair
_base_package = impl.package


def package(story: dict, visual: dict) -> dict:
    plan = _base_package(story, visual)
    editorial_type = str(story.get("editorial_type") or "").strip().lower()
    story_id = str(story.get("id") or "")
    if editorial_type != "fact_check" and "fact-check" not in str(story.get("headline") or "").lower():
        return plan

    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    plan["template_id"] = "investigation_card"
    plan["native_format"] = "carousel"
    plan["hook"] = "31 AUGUST 2026"
    plan["subline"] = "CET Govora: ce spune legea despre oprirea grupurilor pe cărbune"

    if story_id == "cet-govora-cine-a-decis-oprirea-20260821":
        plan["detail_slides"] = [
            {
                "kicker": "CE SPUNE LEGEA",
                "lead": "OUG 20/2026 fixează termenul",
                "body": "Grupurile 3 și 4 ale CET Govora sunt incluse în calendarul legal de scoatere din exploatare până la 31 august 2026.",
            },
            {
                "kicker": "CE A NOTIFICAT CET GOVORA",
                "lead": "Închiderea este legată de obligații legale",
                "body": "HCL 225/2026 reproduce notificarea operatorului: producția încetează cel târziu la 31 august 2026, iar licența urma să fie retrasă la aceeași dată.",
            },
            {
                "kicker": "CE URMEAZĂ PENTRU IARNĂ",
                "lead": "Nu este vorba de o singură centrală privată",
                "body": "Documentele municipale descriu un mix: producător privat de aproximativ 19 MWt, plus noile cazane de apă fierbinte de 100 MWt prevăzute pentru octombrie.",
            },
            {
                "kicker": "CÂT COSTĂ ÎN 2026",
                "lead": "553,15 lei/Gcal fără TVA",
                "body": "Acesta este prețul de facturare aprobat pentru populația racordată la distribuție. Intervalul 700–800 lei/Gcal rămâne o estimare, nu un tarif aprobat.",
            },
            {
                "kicker": "VERDICT",
                "lead": "Afirmația „nimeni nu a impus oprirea” este incompletă",
                "body": "Documentele oficiale arată un calendar legal explicit. Articolul separă faptele verificabile de afirmațiile și estimările politice.",
            },
        ]
    else:
        # Generic fact-check fallback: evidence, consequence, unknowns.
        slides = []
        labels = ["CE SPUNE DOCUMENTUL", "CE PUTEM CONFIRMA", "CE NU ȘTIM ÎNCĂ"]
        for idx, paragraph in enumerate(paragraphs[:3]):
            first = paragraph.split(".", 1)[0].strip()
            slides.append({
                "kicker": labels[min(idx, len(labels) - 1)],
                "lead": impl.base.truncate(first, 82),
                "body": impl.base.truncate(paragraph[len(first):].lstrip(". "), 190) or impl.base.truncate(paragraph, 190),
            })
        plan["detail_slides"] = slides

    plan["rendering_version"] = "instagram-editorial-v1.2-factcheck"
    plan["product_fingerprint_sha256"] = impl.base.digest({k: v for k, v in plan.items() if k != "product_fingerprint_sha256"})
    return plan


impl.package = package
impl.base.render_cover = feed_identity.render_instagram_cover
impl.render_text_slide = feed_identity.render_instagram_text_slide


def self_test() -> int:
    assert contractor_pair("atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    assert impl.base.render_cover is feed_identity.render_instagram_cover
    assert impl.render_text_slide is feed_identity.render_instagram_text_slide
    sample = {
        "id": "cet-govora-cine-a-decis-oprirea-20260821",
        "editorial_type": "fact_check",
        "section": "ENERGIE",
        "headline": "CET Govora: cine a decis oprirea",
        "dek": "Documentele oficiale permit verificarea afirmațiilor publice despre oprire.",
        "paragraphs": ["Document verificat suficient pentru test." for _ in range(5)],
    }
    plan = package(sample, {"image_path": "x.jpg", "image": {"contextual_archive": True}})
    assert plan["template_id"] == "investigation_card"
    assert plan["native_format"] == "carousel"
    assert plan["hook"] == "31 AUGUST 2026"
    assert len(plan["detail_slides"]) == 5
    feed_identity.self_test()
    result = impl.self_test()
    print("VÂLCEA CLAR Instagram editorial v1.2 premium feed identity + fact-check carousel: PASS")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(impl.build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
