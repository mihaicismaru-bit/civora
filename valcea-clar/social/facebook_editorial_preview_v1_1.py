#!/usr/bin/env python3
"""Facebook editorial preview v1.1: entity-safe copy + premium feed identity."""
from __future__ import annotations

import argparse
import json
import re

import facebook_editorial_preview as impl
import feed_identity_v1_1 as feed_identity


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    # Only spaced separator dashes become ` + `; internal hyphens stay intact.
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


_base_package = impl.package


def package(story: dict, visual: dict) -> dict:
    """Upgrade verified fact-checks to an evidence-led Facebook-native product."""
    plan = _base_package(story, visual)
    if str(story.get("editorial_type") or "").strip().lower() != "fact_check":
        return plan

    plan["template_id"] = "fb_investigation_card"
    story_id = str(story.get("id") or "")
    if story_id == "cet-govora-cine-a-decis-oprirea-20260821":
        hook = "Cine a decis, de fapt, oprirea CET Govora?"
        plan["hook"] = hook
        plan["visual_subline"] = "31 august 2026 · termen prevăzut în OUG 20/2026"
        link = plan["canonical_link"]
        plan["cta"] = "Documentele și contextul complet sunt în articol."
        plan["body"] = (
            f"{hook}\n\n"
            "O postare politică susține că oprirea nu a fost impusă de nimeni. Documentele oficiale arată însă un calendar legal explicit: OUG 20/2026 include grupurile 3 și 4 ale CET Govora între capacitățile pe cărbune care trebuie scoase din exploatare până la 31 august 2026.\n\n"
            "HCL Râmnicu Vâlcea nr. 225/2026 consemnează chiar notificarea CET Govora: operatorul anunța încetarea definitivă a producției cel târziu la 31 august, ca urmare a dispozițiilor legale privind eliminarea producției pe cărbune.\n\n"
            "Am verificat separat și prețurile pentru 2026. Pentru populația racordată la rețeaua de distribuție, HCL nr. 5/2026 stabilește 553,15 lei/Gcal fără TVA. Intervalul 700–800 lei/Gcal invocat în disputa politică nu este, la 21 august 2026, un tarif aprobat.\n\n"
            "Foto de arhivă: CET Govora, 27 iunie 2011. Imaginea nu surprinde situația operațională din 2026.\n\n"
            f"{plan['cta']}\n{link}"
        )

    plan["rendering_version"] = "facebook-editorial-v1.1"
    plan["product_fingerprint_sha256"] = impl.digest(
        {k: v for k, v in plan.items() if k != "product_fingerprint_sha256"}
    )
    return plan


# Preserve the verified base implementation while upgrading entity normalization,
# fact-check packaging and deterministic premium presentation.
impl.contractor_pair = contractor_pair
impl.package = package
impl.render = feed_identity.render_facebook


def self_test() -> int:
    assert contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert contractor_pair("asocierii Alpha-Beta SRL - Gamma SRL, cu subcontractanți") == "Alpha-Beta + Gamma"
    assert impl.render is feed_identity.render_facebook
    sample = {
        "id": "cet-govora-cine-a-decis-oprirea-20260821",
        "editorial_type": "fact_check",
        "section": "ENERGIE",
        "headline": "CET Govora: cine a decis oprirea și ce urmează pentru termoficarea Râmnicului",
        "dek": "Documentele oficiale permit verificarea afirmațiilor publice despre oprirea CET Govora.",
        "paragraphs": ["OUG 20/2026 stabilește calendarul legal de scoatere din exploatare."],
    }
    visual = {"image_path": "x.jpg", "image": {"contextual_archive": True, "editorial_note": "archive"}}
    product = package(sample, visual)
    assert product["template_id"] == "fb_investigation_card"
    assert product["hook"] == "Cine a decis, de fapt, oprirea CET Govora?"
    assert "31 august 2026" in product["visual_subline"]
    assert "553,15 lei/Gcal" in product["body"]
    feed_identity.self_test()
    result = impl.self_test()
    print("VÂLCEA CLAR Facebook editorial v1.1 premium fact-check identity: PASS")
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
