from __future__ import annotations
from typing import Dict
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

def generate_article(story: StoryObject) -> StoryObject:
    if story.state != StoryState.READY:
        raise PipelineError("Story must be READY before drafting.")
    facts = story.fact_kernel.confirmed_facts
    lead = facts[0] if facts else story.signal.summary
    story.article = {
        "headline": story.signal.title,
        "dek": story.signal.summary,
        "lead": lead,
        "confirmed_facts": facts,
        "what_is_uncertain": story.fact_kernel.uncertain_claims,
        "why_it_matters": story.signal.summary,
        "next": story.fact_kernel.next_expected_event,
        "verification_status": story.fact_kernel.verification_status.value,
        "trust_score": story.trust_score,
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
        }
    }
    story.state = StoryState.PACKAGED
    return story
