#!/usr/bin/env python3
"""Deterministic, read-only editorial writing quality checks for VÂLCEA CLAR.

This module evaluates copy against general professional newswriting practices:
clear/event-first leads when appropriate, verified attribution, local relevance,
story-type fit, readable structure and avoidance of bureaucratic/template language.
It does not imitate any publisher's voice, rewrite copy, add facts, authorize
publication or mutate the Fact Kernel.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

CONTRACT = "VALCEA_CLAR_EDITORIAL_WRITING_QUALITY_V1"
SUPPORTED_STORY_TYPES = {"REPORT", "UPDATE", "EXPLAINER", "SERVICE", "FEATURE", "BREAKING"}
HARD_NEWS_TYPES = {"REPORT", "UPDATE", "SERVICE", "BREAKING"}

# These are deliberately narrow markers. They identify common bureaucratic or
# press-release throat-clearing patterns, not a publisher-specific style.
BUREAUCRATIC_LEAD_PATTERNS = (
    r"^în cadrul\b",
    r"^potrivit unui comunicat\b",
    r"^conform unui comunicat\b",
    r"^cu ocazia\b",
    r"^în contextul\b",
    r"^a avut loc\b",
    r"^s-a desfășurat\b",
    r"^instituția .* informează\b",
    r"^instituția .* aduce la cunoștință\b",
)

MECHANICAL_PHRASES = (
    "în vederea",
    "în ceea ce privește",
    "la nivelul județului",
    "a fost organizată o acțiune",
    "s-a procedat la",
    "au fost desfășurate activități",
    "în conformitate cu prevederile",
    "facem precizarea că",
    "menționăm faptul că",
    "se aduce la cunoștința",
)

CLICHE_PHRASES = (
    "un pas important",
    "un moment deosebit",
    "și nu numai",
    "mai mult ca niciodată",
    "vremuri fără precedent",
)

LOCAL_MARKERS = (
    "vâlcea",
    "râmnicu vâlcea",
    "râmnicu-vâlcea",
    "rm. vâlcea",
    "rm vâlcea",
)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZĂÂÎȘȚ0-9„\"])")
WORD_RE = re.compile(r"[0-9A-Za-zĂÂÎȘȚăâîșț][0-9A-Za-zĂÂÎȘȚăâîșț'’.-]*")
NUMBER_RE = re.compile(r"(?<!\w)\d+(?:[.,]\d+)?(?:%|\s*(?:lei|euro|km|m|ore|minute|zile))?", re.IGNORECASE)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values() if _text(v))
    if isinstance(value, (list, tuple, set)):
        return " ".join(_text(v) for v in value if _text(v))
    return " ".join(str(value).split())


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _sentences(text: str) -> list[str]:
    text = " ".join(text.split())
    if not text:
        return []
    return [part.strip() for part in SENTENCE_SPLIT_RE.split(text) if part.strip()]


def _paragraphs(text: str) -> list[str]:
    return [" ".join(part.split()) for part in re.split(r"\n\s*\n", text or "") if part.strip()]


def _norm_token(token: str) -> str:
    return token.casefold().replace(" ", "")


def _add(diagnostics: list[dict[str, Any]], code: str, severity: str, message: str, **details: Any) -> None:
    item: dict[str, Any] = {"code": code, "severity": severity, "message": message}
    if details:
        item["details"] = details
    diagnostics.append(item)


def _repeated_sentence_starts(text: str) -> list[str]:
    starts: list[str] = []
    for sentence in _sentences(text):
        words = [w.casefold() for w in _words(sentence)]
        if len(words) >= 3:
            starts.append(" ".join(words[:3]))
    counts = Counter(starts)
    return sorted(start for start, count in counts.items() if count >= 3)


def _repeated_phrases(text: str, n: int = 5) -> list[str]:
    words = [w.casefold() for w in _words(text)]
    if len(words) < n * 2:
        return []
    grams = Counter(" ".join(words[i : i + n]) for i in range(len(words) - n + 1))
    # Ignore very short function-word dominated repetitions by requiring at
    # least two tokens with length >= 5.
    repeated = []
    for gram, count in grams.items():
        if count < 2:
            continue
        if sum(1 for token in gram.split() if len(token) >= 5) < 2:
            continue
        repeated.append(gram)
    return sorted(repeated)[:8]


def _has_local_relevance(item: dict[str, Any], corpus: str) -> bool:
    locality = _text(item.get("locality_context"))
    haystack = f"{locality} {corpus}".casefold()
    return bool(locality) or any(marker in haystack for marker in LOCAL_MARKERS)


def evaluate(item: dict[str, Any]) -> dict[str, Any]:
    diagnostics: list[dict[str, Any]] = []
    story_type = _text(item.get("story_type")).upper()
    headline = _text(item.get("headline"))
    lead = _text(item.get("lead"))
    body_raw = str(item.get("body") or "")
    body = _text(body_raw)
    provenance = item.get("provenance")
    confirmed_facts = item.get("confirmed_facts")
    why_it_matters = _text(item.get("why_it_matters"))
    unknowns = _text(item.get("unknowns"))
    next_steps = _text(item.get("next_steps"))
    what_changed = _text(item.get("what_changed"))

    if story_type not in SUPPORTED_STORY_TYPES:
        _add(
            diagnostics,
            "UNSUPPORTED_STORY_TYPE",
            "FAIL",
            "story_type must explicitly select a supported journalistic form.",
            supported=sorted(SUPPORTED_STORY_TYPES),
        )

    for field_name, value in (("headline", headline), ("lead", lead), ("body", body)):
        if not value:
            _add(diagnostics, f"MISSING_{field_name.upper()}", "FAIL", f"{field_name} is required for quality evaluation.")

    if not _text(provenance):
        _add(
            diagnostics,
            "MISSING_PROVENANCE",
            "FAIL",
            "Reader copy must remain bound to explicit source provenance.",
        )

    confirmed_text = _text(confirmed_facts)
    if not confirmed_text:
        _add(
            diagnostics,
            "MISSING_CONFIRMED_FACTS",
            "FAIL",
            "Quality checks require an explicit confirmed_facts basis; copy alone is not evidence.",
        )

    if lead:
        for pattern in BUREAUCRATIC_LEAD_PATTERNS:
            if re.search(pattern, lead.casefold()):
                _add(
                    diagnostics,
                    "BUREAUCRATIC_LEAD",
                    "WARN",
                    "Lead opens with institutional/process framing instead of the material reader fact.",
                    matched_pattern=pattern,
                )
                break

        lead_words = len(_words(lead))
        limit = 48 if story_type in HARD_NEWS_TYPES else 65
        if lead_words > limit:
            _add(
                diagnostics,
                "LEAD_TOO_LONG",
                "WARN",
                "Lead is longer than the conservative readability target for this story type.",
                words=lead_words,
                target_max=limit,
            )

    full_copy = " ".join(part for part in (headline, lead, body) if part)
    lower_copy = full_copy.casefold()

    mechanical_hits = sorted({phrase for phrase in MECHANICAL_PHRASES if phrase in lower_copy})
    if mechanical_hits:
        _add(
            diagnostics,
            "MECHANICAL_OR_BUREAUCRATIC_LANGUAGE",
            "WARN",
            "Copy contains narrow markers of bureaucratic or press-release language.",
            phrases=mechanical_hits,
        )

    cliche_hits = sorted({phrase for phrase in CLICHE_PHRASES if phrase in lower_copy})
    if cliche_hits:
        _add(
            diagnostics,
            "CLICHE_LANGUAGE",
            "WARN",
            "Copy contains generic promotional/cliché phrasing that weakens precision.",
            phrases=cliche_hits,
        )

    starts = _repeated_sentence_starts(f"{lead} {body}")
    if starts:
        _add(
            diagnostics,
            "REPEATED_SENTENCE_STARTS",
            "WARN",
            "Several sentences begin with the same three-word pattern, a mechanical-rhythm signal.",
            repeated_starts=starts,
        )

    repeated = _repeated_phrases(f"{lead} {body}")
    if repeated:
        _add(
            diagnostics,
            "DUPLICATE_PHRASING",
            "WARN",
            "Five-word phrasing is repeated without being treated as a quotation/evidence field.",
            phrases=repeated,
        )

    sentence_lengths = [(sentence, len(_words(sentence))) for sentence in _sentences(f"{lead} {body}")]
    very_long = [length for _sentence, length in sentence_lengths if length > 45]
    if very_long:
        _add(
            diagnostics,
            "OVERLONG_SENTENCES",
            "WARN",
            "One or more sentences exceed the conservative 45-word readability threshold.",
            count=len(very_long),
            longest=max(very_long),
        )

    paragraphs = _paragraphs(body_raw)
    long_paragraphs = [len(_words(paragraph)) for paragraph in paragraphs if len(_words(paragraph)) > 145]
    if long_paragraphs:
        _add(
            diagnostics,
            "OVERLONG_PARAGRAPHS",
            "WARN",
            "Body contains mobile-unfriendly long paragraphs.",
            count=len(long_paragraphs),
            longest=max(long_paragraphs),
        )

    support_corpus = confirmed_text.casefold()
    headline_numbers = NUMBER_RE.findall(headline)
    unsupported_numbers = [token for token in headline_numbers if _norm_token(token) not in _norm_token(support_corpus)]
    if unsupported_numbers:
        _add(
            diagnostics,
            "HEADLINE_MATERIAL_NUMBER_UNSUPPORTED",
            "FAIL",
            "A material number in the headline is absent from the explicit confirmed_facts basis.",
            tokens=unsupported_numbers,
        )

    if full_copy and not _has_local_relevance(item, full_copy):
        _add(
            diagnostics,
            "LOCAL_RELEVANCE_NOT_EXPLICIT",
            "WARN",
            "Copy or locality_context does not make the Vâlcea/local connection explicit.",
        )

    if story_type in {"REPORT", "BREAKING"} and not why_it_matters:
        _add(
            diagnostics,
            "WHY_IT_MATTERS_MISSING",
            "WARN",
            "Hard-news copy should make the local consequence or significance explicit when evidence supports it.",
        )

    if story_type == "UPDATE" and not what_changed:
        _add(
            diagnostics,
            "UPDATE_DELTA_MISSING",
            "FAIL",
            "UPDATE requires an explicit evidence-bound what_changed field so the new information leads.",
        )

    if story_type == "EXPLAINER":
        if not why_it_matters:
            _add(diagnostics, "EXPLAINER_CONTEXT_MISSING", "FAIL", "EXPLAINER requires an explicit why_it_matters/context basis.")
        if not unknowns:
            _add(diagnostics, "EXPLAINER_UNKNOWNS_MISSING", "WARN", "EXPLAINER should distinguish confirmed facts from material unknowns.")

    if story_type == "SERVICE" and not next_steps:
        _add(
            diagnostics,
            "SERVICE_ACTION_MISSING",
            "FAIL",
            "SERVICE journalism requires an explicit evidence-bound next_steps/action field.",
        )

    body_word_count = len(_words(body))
    fact_count = len(confirmed_facts) if isinstance(confirmed_facts, list) else (1 if confirmed_text else 0)
    if body_word_count >= 220 and fact_count < 2:
        _add(
            diagnostics,
            "LOW_EXPLICIT_FACT_DENSITY",
            "WARN",
            "A relatively long article is backed by fewer than two explicit confirmed-fact entries.",
            body_words=body_word_count,
            confirmed_fact_entries=fact_count,
        )

    fail_count = sum(1 for diagnostic in diagnostics if diagnostic["severity"] == "FAIL")
    warn_count = sum(1 for diagnostic in diagnostics if diagnostic["severity"] == "WARN")
    status = "FAIL" if fail_count else ("WARN" if warn_count else "PASS")

    return {
        "contract": CONTRACT,
        "status": status,
        "story_type": story_type,
        "diagnostics": diagnostics,
        "metrics": {
            "headline_words": len(_words(headline)),
            "lead_words": len(_words(lead)),
            "body_words": body_word_count,
            "sentence_count": len(sentence_lengths),
            "paragraph_count": len(paragraphs),
            "fail_count": fail_count,
            "warn_count": warn_count,
        },
        "quality_semantics": {
            "general_professional_journalism_practices_only": True,
            "publisher_voice_imitation": False,
            "single_template_style_enforced": False,
            "story_type_specific_checks": True,
            "ai_detection_claim": False,
        },
        "capabilities": {
            "publication_authorized": False,
            "automatic_rewrite_authorized": False,
            "fact_inference_authorized": False,
            "fact_kernel_mutation_authorized": False,
            "source_provenance_mutation_authorized": False,
            "breaking_promotion_authorized": False,
        },
    }


def _assert_codes(result: dict[str, Any], expected: Iterable[str]) -> None:
    codes = {diagnostic["code"] for diagnostic in result["diagnostics"]}
    missing = set(expected) - codes
    if missing:
        raise AssertionError(f"missing diagnostics: {sorted(missing)}; got {sorted(codes)}")


def self_test() -> int:
    strong_report = {
        "story_type": "REPORT",
        "headline": "Râmnicu Vâlcea: apa va fi oprită marți pe strada Carol I",
        "lead": "Furnizarea apei va fi întreruptă marți pe strada Carol I din Râmnicu Vâlcea, între 09:00 și 14:00, potrivit operatorului regional.",
        "body": "Operatorul anunță lucrări la rețea în intervalul indicat. Locuitorii din zona afectată sunt sfătuiți să își asigure necesarul de apă înainte de ora 09:00.",
        "provenance": [{"url": "https://example.test/official", "tier": "T1"}],
        "confirmed_facts": [
            "Râmnicu Vâlcea, strada Carol I",
            "întrerupere marți între 09:00 și 14:00",
            "operatorul indică lucrări la rețea",
        ],
        "why_it_matters": "Locuitorii din zona afectată rămân temporar fără apă.",
        "locality_context": "Râmnicu Vâlcea",
    }
    report_result = evaluate(strong_report)
    if report_result["status"] != "PASS":
        raise AssertionError(report_result)

    bureaucratic = dict(strong_report)
    bureaucratic["lead"] = "În cadrul unei acțiuni desfășurate marți, operatorul a informat cu privire la lucrări pe strada Carol I din Râmnicu Vâlcea."
    bureaucratic["body"] = "În vederea executării lucrărilor, furnizarea apei va fi oprită temporar."
    bureaucratic_result = evaluate(bureaucratic)
    _assert_codes(bureaucratic_result, {"BUREAUCRATIC_LEAD", "MECHANICAL_OR_BUREAUCRATIC_LANGUAGE"})

    missing_provenance = dict(strong_report)
    missing_provenance["provenance"] = []
    missing_result = evaluate(missing_provenance)
    if missing_result["status"] != "FAIL":
        raise AssertionError(missing_result)
    _assert_codes(missing_result, {"MISSING_PROVENANCE"})

    unsupported_headline = dict(strong_report)
    unsupported_headline["headline"] = "Râmnicu Vâlcea: 700 de locuințe rămân fără apă marți"
    unsupported_number_result = evaluate(unsupported_headline)
    if unsupported_number_result["status"] != "FAIL":
        raise AssertionError(unsupported_number_result)
    _assert_codes(unsupported_number_result, {"HEADLINE_MATERIAL_NUMBER_UNSUPPORTED"})

    explainer = dict(strong_report)
    explainer["story_type"] = "EXPLAINER"
    explainer["why_it_matters"] = ""
    explainer["unknowns"] = ""
    explainer_result = evaluate(explainer)
    if explainer_result["status"] != "FAIL":
        raise AssertionError(explainer_result)
    _assert_codes(explainer_result, {"EXPLAINER_CONTEXT_MISSING", "EXPLAINER_UNKNOWNS_MISSING"})

    repetitive = dict(strong_report)
    repetitive["body"] = (
        "Operatorul anunță lucrări la rețea pentru această zonă. "
        "Operatorul anunță lucrări la rețea pentru această zonă. "
        "Operatorul anunță lucrări la rețea pentru această zonă."
    )
    repetitive_result = evaluate(repetitive)
    _assert_codes(repetitive_result, {"REPEATED_SENTENCE_STARTS", "DUPLICATE_PHRASING"})

    update = dict(strong_report)
    update["story_type"] = "UPDATE"
    update["what_changed"] = ""
    update_result = evaluate(update)
    if update_result["status"] != "FAIL":
        raise AssertionError(update_result)
    _assert_codes(update_result, {"UPDATE_DELTA_MISSING"})

    service = dict(strong_report)
    service["story_type"] = "SERVICE"
    service["next_steps"] = ""
    service_result = evaluate(service)
    if service_result["status"] != "FAIL":
        raise AssertionError(service_result)
    _assert_codes(service_result, {"SERVICE_ACTION_MISSING"})

    for result in (
        report_result,
        bureaucratic_result,
        missing_result,
        unsupported_number_result,
        explainer_result,
        repetitive_result,
        update_result,
        service_result,
    ):
        if any(result["capabilities"].values()):
            raise AssertionError("quality validator must never authorize a write/publication capability")
        if result["quality_semantics"]["publisher_voice_imitation"]:
            raise AssertionError("publisher voice imitation must remain disabled")
        if result["quality_semantics"]["ai_detection_claim"]:
            raise AssertionError("no AI-detector claim is permitted")

    print(json.dumps({"contract": CONTRACT, "self_test": "PASS", "cases": 8}, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only VÂLCEA CLAR editorial writing quality validator")
    parser.add_argument("input", nargs="?", help="JSON file containing one article candidate")
    parser.add_argument("--self-test", action="store_true", help="run deterministic fail-closed regression cases")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.input:
        parser.error("provide a JSON input file or --self-test")
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit("input must be a JSON object")
    result = evaluate(payload)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
