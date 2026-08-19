#!/usr/bin/env python3
"""Repository-wide fail-closed guard for VÂLCEA CLAR Facebook publication.

Persistence is not enough unless it is enforced. This guard makes the persisted
social doctrine executable: exactly one workflow may publish Facebook feed
content, and that workflow must use the canonical story-first editorial adapter.
Metadata-only Page maintenance remains an explicit non-content exception.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
WORKFLOWS = ROOT / ".github" / "workflows"

CANONICAL_WORKFLOW = ".github/workflows/valcea-clar-social-publishing.yml"
CANONICAL_ADAPTER = "valcea-clar/social/facebook_editorial_publish.py"
PROFILE_WORKFLOW = ".github/workflows/valcea-clar-facebook-profile-sync.yml"
PROFILE_ADAPTER = "valcea-clar/social/facebook_profile_sync.py"
FORBIDDEN_WORKFLOWS = {
    ".github/workflows/valcea-clar-facebook-backlog.yml",
    ".github/workflows/valcea-clar-facebook-intro-photo.yml",
    ".github/workflows/valcea-clar-facebook-featured.yml",
}
FORBIDDEN_APPLY_ADAPTERS = {
    "valcea-clar/social/facebook_text_publish.py",
    "valcea-clar/social/facebook_text_publish_v2.py",
    "valcea-clar/social/facebook_intro_photo_publish.py",
    "valcea-clar/social/facebook_featured_setup.py",
    "valcea-clar/social/facebook_publish.py",
}
APPLY_RE = re.compile(
    r"python(?:3)?(?:\s+-u)?\s+(valcea-clar/social/[A-Za-z0-9_.-]*facebook[A-Za-z0-9_.-]*\.py)\s+--apply\b",
    re.IGNORECASE,
)


class GuardFailure(RuntimeError):
    pass


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise GuardFailure(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def require(condition: bool, message: str, violations: list[str]) -> None:
    if not condition:
        violations.append(message)


def validate_doctrine(violations: list[str]) -> None:
    doctrine = load_json(SOCIAL / "social_network_doctrine.json")
    brand = load_json(SOCIAL / "social_brand_system.json")
    visual = load_json(SOCIAL / "facebook_visual_system.json")
    registry = load_json(SOCIAL / "channel_registry.json")

    invariants = set(doctrine.get("shared_invariants") or [])
    fb = (doctrine.get("channels") or {}).get("facebook") or {}
    require(doctrine.get("publication_model") == "continuous_story_first", "doctrine: publication_model must be continuous_story_first", violations)
    require(doctrine.get("canonical_source") == "site_story", "doctrine: canonical_source must be site_story", violations)
    require(doctrine.get("cross_platform_final_reuse_default") is False, "doctrine: cross-platform final-copy reuse must default false", violations)
    for invariant in (
        "same_verified_facts_different_packaging",
        "no_factual_embellishment_for_reach",
        "no_clickbait_or_fake_urgency",
        "no_engagement_bait",
        "rights_and_provenance_fail_closed",
        "civora_site_engine_owns_automation",
    ):
        require(invariant in invariants, f"doctrine: missing shared invariant {invariant}", violations)
    require(fb.get("product_mode") == "platform_native", "doctrine: Facebook must remain platform_native", violations)
    require(fb.get("interest_gate") == "FB_INTEREST_GATE", "doctrine: Facebook interest gate must be FB_INTEREST_GATE", violations)
    require("The Washington Post" in ((fb.get("benchmark") or {}).get("outlets") or []), "doctrine: Facebook benchmark must retain The Washington Post", violations)

    brand_doc = brand.get("brand") or {}
    grammar = brand.get("global_visual_grammar") or {}
    quality = brand.get("quality_gate") or {}
    fb_brand = (brand.get("platforms") or {}).get("facebook") or {}
    require(brand_doc.get("positioning") == "premium_local_news_publisher", "brand: positioning must be premium_local_news_publisher", violations)
    require("The Washington Post" in (brand_doc.get("reference_publishers") or []), "brand: Washington Post reference benchmark missing", violations)
    require(grammar.get("engagement_bait_forbidden") is True, "brand: engagement bait must be forbidden", violations)
    require(grammar.get("fake_urgency_forbidden") is True, "brand: fake urgency must be forbidden", violations)
    require(grammar.get("generic_stock_substitution_forbidden") is True, "brand: generic stock substitution must be forbidden", violations)
    require(grammar.get("platform_native_visual_grammar_required") is True, "brand: platform-native visual grammar must be required", violations)
    require(quality.get("must_look_like_established_newsroom") is True, "brand QA: established-newsroom gate missing", violations)
    require(quality.get("must_not_look_like_local_marketing_page") is True, "brand QA: local-marketing-page rejection missing", violations)
    require(quality.get("must_not_look_ai_generated") is True, "brand QA: AI-generated-look rejection missing", violations)
    require(fb_brand.get("caption_rule") == "lead_with_the_local_consequence_then_add_context_and_link", "brand: Facebook caption rule drift", violations)

    canvas = visual.get("canvas") or {}
    templates = visual.get("templates") or {}
    copy = visual.get("copy") or {}
    qa = visual.get("qa") or {}
    require(canvas.get("width") == 1200 and canvas.get("height") == 1500 and canvas.get("aspect_ratio") == "4:5", "Facebook visual canvas must remain 1200x1500 / 4:5", violations)
    require(templates.get("fb_news_card") == "photo_plus_editorial_footer", "Facebook fb_news_card template drift", violations)
    require(copy.get("lead_rule") == "local_consequence_or_useful_fact_first", "Facebook copy lead rule drift", violations)
    require(qa.get("engagement_bait_forbidden") is True, "Facebook QA: engagement bait must be forbidden", violations)
    require(qa.get("must_not_look_like_local_marketing_page") is True, "Facebook QA: local marketing look must be rejected", violations)
    require(qa.get("must_not_look_ai_generated") is True, "Facebook QA: AI-generated look must be rejected", violations)

    require(registry.get("workflow") == CANONICAL_WORKFLOW, "channel registry must point to canonical social workflow", violations)
    fb_rows = [row for row in registry.get("channels") or [] if isinstance(row, dict) and row.get("channel_id") == "facebook"]
    require(len(fb_rows) == 1, "channel registry must contain exactly one Facebook channel", violations)
    if fb_rows:
        row = fb_rows[0]
        req = row.get("requirements") or {}
        require(row.get("adapter") == CANONICAL_ADAPTER, "channel registry Facebook adapter must be canonical editorial publisher", violations)
        for key in ("story_event", "canonical_story_readiness_gate", "facebook_interest_gate", "editorial_composite", "platform_native_copy"):
            require(req.get(key) is True, f"channel registry Facebook requirement missing: {key}", violations)


def validate_workflow_single_writer(violations: list[str]) -> None:
    canonical = ROOT / CANONICAL_WORKFLOW
    require(canonical.is_file(), "canonical Facebook social workflow is missing", violations)
    if canonical.is_file():
        text = canonical.read_text(encoding="utf-8")
        require(f"python {CANONICAL_ADAPTER} --apply" in text, "canonical workflow does not invoke canonical Facebook adapter", violations)
        require("python valcea-clar/social/validate_facebook_single_writer.py" in text, "canonical workflow does not run the single-writer guard", violations)

    for forbidden in sorted(FORBIDDEN_WORKFLOWS):
        require(not (ROOT / forbidden).exists(), f"forbidden Facebook bypass workflow still exists: {forbidden}", violations)

    for path in sorted(WORKFLOWS.glob("*.yml")):
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for adapter in APPLY_RE.findall(text):
            if rel == CANONICAL_WORKFLOW and adapter == CANONICAL_ADAPTER:
                continue
            if rel == PROFILE_WORKFLOW and adapter == PROFILE_ADAPTER:
                continue
            violations.append(f"unauthorized Facebook --apply writer: {rel} -> {adapter}")
        for adapter in FORBIDDEN_APPLY_ADAPTERS:
            if f"{adapter} --apply" in text:
                violations.append(f"forbidden Facebook bypass adapter referenced by workflow: {rel} -> {adapter}")
        if "graph.facebook.com" in text and ("/feed" in text or "/photos" in text):
            violations.append(f"workflow contains direct Facebook feed/photo Graph endpoint: {rel}")


def main() -> int:
    violations: list[str] = []
    try:
        validate_doctrine(violations)
        validate_workflow_single_writer(violations)
    except (OSError, json.JSONDecodeError, GuardFailure) as exc:
        violations.append(str(exc))

    report = {
        "status": "PASS" if not violations else "FAIL",
        "contract": "valcea-clar-facebook-single-writer-v1",
        "canonical_workflow": CANONICAL_WORKFLOW,
        "canonical_adapter": CANONICAL_ADAPTER,
        "profile_metadata_exception": PROFILE_WORKFLOW,
        "violations": violations,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if violations:
        raise SystemExit(1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
