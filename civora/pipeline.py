from __future__ import annotations
from typing import Dict
from .evidence_rendering import EvidenceConstrainedRenderer, EvidenceRenderingError
from .models import Source, StoryObject, StoryState, VerificationStatus
from .scoring import source_score, opportunity_score, trust_score, viral_score

class PipelineError(Exception):
    pass

def verify_story(story: StoryObject, source_map: Dict[str, Source]) -> StoryObject:
    story.state = StoryState.VERIFYING
    source_scores = [source_score(source_map[sid]) for sid in story.signal.source_ids if sid in source_map]
    story.source_score = round(sum(source_scores) / len(source_scores), 2) if source_scores else 0.0

    if len(story.fact_kernel.evidence) >= 2 and story.source_score >= 60 and not story.fact_kernel.uncertain_claims:
        story.fact_kernel.verification_status = VerificationStatus.VERIFIED
    elif story.fact_kernel.evidence:
        story.fact_kernel.verification_status = VerificationStatus.PARTIAL
    else:
        story.fact_kernel.verification_status = VerificationStatus.UNVERIFIED

    story.opportunity_score = opportunity_score(story.signal)
    story.trust_score = trust_score(story.fact_kernel, source_scores)
    story.viral_score = viral_score(story.signal, story.trust_score)

    if story.trust_score < 35:
        story.state = StoryState.BLOCKED
    else:
        story.state = StoryState.READY
    return story

def generate_article(story: StoryObject, authorization: dict) -> StoryObject:
    """Draft only from an explicit AuthorizedStoryBuilder projection.

    The pipeline intentionally has no fallback to ``FactKernel.confirmed_facts``
    or reader-visible ``Signal`` prose. Callers must supply a projection bound
    to the current story/editorial decision; every factual reader-facing field
    is then rendered from that authorized projection.
    """
    if story.state != StoryState.READY:
        raise PipelineError("Story must be READY before drafting.")
    if not isinstance(authorization, dict):
        raise PipelineError("Drafting requires an authorized fact projection.")
    if authorization.get("story_id") != story.id:
        raise PipelineError("Authorized fact projection belongs to a different story.")
    facts = authorization.get("authorized_facts")
    if not isinstance(facts, list) or not facts:
        raise PipelineError("Drafting requires at least one authorized confirmed fact.")
    if any(not isinstance(item, dict) or not item.get("statement") for item in facts):
        raise PipelineError("Authorized fact projection is malformed.")

    confirmed_statements = [item["statement"] for item in facts]
    uncertain = authorization.get("authorized_uncertain_claims", [])
    if not isinstance(uncertain, list):
        raise PipelineError("Authorized uncertainty projection is malformed.")
    uncertain_statements = [
        item["statement"]
        for item in uncertain
        if isinstance(item, dict) and item.get("statement")
    ]

    try:
        rendering = EvidenceConstrainedRenderer().render(authorization)
    except EvidenceRenderingError as exc:
        raise PipelineError(f"Evidence-constrained rendering failed: {exc}") from exc

    story.article = {
        "headline": rendering["headline"],
        "dek": rendering["dek"],
        "lead": confirmed_statements[0],
        "confirmed_facts": confirmed_statements,
        "what_is_uncertain": uncertain_statements,
        "why_it_matters": rendering["why_it_matters"],
        # Raw FactKernel.next_expected_event is deliberately not reader-visible.
        # A future evidence-preserving workflow may enable `next` only from an
        # explicitly authorized projection.
        "next": rendering["next"],
        "verification_status": story.fact_kernel.verification_status.value,
        "trust_score": story.trust_score,
        "authorization": {
            "kernel_id": authorization.get("kernel_id"),
            "kernel_revision": authorization.get("kernel_revision"),
            "kernel_semantic_hash": authorization.get("kernel_semantic_hash"),
            "editorial_decision_id": authorization.get("editorial_decision_id"),
            "authorization_mode": authorization.get("authorization_mode"),
            "authorized_fact_ids": [item.get("fact_id") for item in facts],
        },
        "rendering": {
            "source": rendering["rendering_source"],
            "authorized_fact_ids": rendering["authorized_fact_ids"],
            "authorized_uncertain_claim_ids": rendering["authorized_uncertain_claim_ids"],
        },
    }
    story.state = StoryState.DRAFTED
    return story

def generate_content_pack(story: StoryObject) -> StoryObject:
    if story.state != StoryState.DRAFTED:
        raise PipelineError("Story must be DRAFTED before packaging.")
    headline = story.article["headline"]
    summary = story.article["dek"]
    story.content_pack = {
        "site": story.article,
        "facebook": f"{headline}\n\n{summary}",
        "instagram_caption": f"{headline}\n\n{summary}\n\n#CIVORA",
        "short_video_script": {
            "hook": headline,
            "body": summary,
            "cta": "Detalii și surse în materialul complet."
        },
        "newsletter_blurb": f"{headline} — {summary}",
        "audit": {
            "trust_score": story.trust_score,
            "source_score": story.source_score,
            "viral_score": story.viral_score,
            "editorial_decision_id": story.article.get("authorization", {}).get("editorial_decision_id"),
            "kernel_semantic_hash": story.article.get("authorization", {}).get("kernel_semantic_hash"),
            "rendering_source": story.article.get("rendering", {}).get("source"),
        }
    }
    story.state = StoryState.PACKAGED
    return story
