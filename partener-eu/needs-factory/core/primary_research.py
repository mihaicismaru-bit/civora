from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from .engine import NeedsFactoryValidationError, sha256_json


QUESTION_LIBRARY: Dict[str, Dict[str, Any]] = {
    "career_intention": {
        "construct": "career_intention",
        "prompt": "În ce măsură intenționați să profesați într-un domeniu asociat calificării pe care o urmați?",
        "response_type": "likert_1_5",
        "labels": {"1":"deloc", "2":"în mică măsură", "3":"moderat", "4":"în mare măsură", "5":"în foarte mare măsură"},
    },
    "career_guidance_need": {
        "construct": "career_guidance_need",
        "prompt": "În ce măsură aveți nevoie de informații sau orientare suplimentară despre ocupațiile și traseele profesionale asociate calificării?",
        "response_type": "likert_1_5",
        "labels": {"1":"deloc", "2":"în mică măsură", "3":"moderat", "4":"în mare măsură", "5":"în foarte mare măsură"},
    },
    "practice_relevance": {
        "construct": "practice_relevance",
        "prompt": "În ce măsură considerați că experiența practică la un angajator vă ajută să dobândiți competențe relevante pentru calificarea urmată?",
        "response_type": "likert_1_5",
        "labels": {"1":"deloc", "2":"în mică măsură", "3":"moderat", "4":"în mare măsură", "5":"în foarte mare măsură"},
    },
    "employer_exposure": {
        "construct": "employer_exposure",
        "prompt": "Ați desfășurat până în prezent activități de practică într-un mediu real de lucru la un operator economic?",
        "response_type": "yes_no",
        "labels": {"yes":"da", "no":"nu"},
    },
    "practice_quality": {
        "construct": "practice_quality",
        "prompt": "Dacă ați participat la practică la un operator economic, în ce măsură sarcinile realizate au fost relevante pentru calificarea urmată?",
        "response_type": "likert_1_5_optional",
        "labels": {"1":"deloc", "2":"în mică măsură", "3":"moderat", "4":"în mare măsură", "5":"în foarte mare măsură"},
    },
    "skills_confidence": {
        "construct": "skills_confidence",
        "prompt": "Cât de pregătit(ă) vă considerați să realizați sarcini practice de bază specifice calificării pe care o urmați?",
        "response_type": "likert_1_5",
        "labels": {"1":"deloc pregătit(ă)", "2":"puțin", "3":"moderat", "4":"bine", "5":"foarte bine"},
    },
}

GAP_TO_QUESTIONS = {
    "career_intention": ["career_intention"],
    "career_guidance": ["career_guidance_need", "career_intention"],
    "practice_quality": ["employer_exposure", "practice_quality", "practice_relevance"],
    "practice_access": ["employer_exposure", "practice_relevance"],
    "skills_baseline": ["skills_confidence", "practice_relevance"],
    "direct_local_evidence": ["career_intention", "career_guidance_need", "practice_relevance", "employer_exposure"],
}


def generate_primary_research_plan(
    gaps: Sequence[Mapping[str, Any]],
    population_snapshot: Mapping[str, Any],
) -> Dict[str, Any]:
    question_keys: List[str] = []
    for gap in gaps:
        for key in GAP_TO_QUESTIONS.get(str(gap.get("gap_type")), ["practice_relevance"]):
            if key not in question_keys:
                question_keys.append(key)

    questions = []
    for idx, key in enumerate(question_keys, start=1):
        item = dict(QUESTION_LIBRARY[key])
        item["question_id"] = f"Q{idx:02d}"
        item["template_key"] = key
        questions.append(item)

    population_n = population_snapshot.get("eligible_population_n")
    if not isinstance(population_n, int) or population_n <= 0:
        strategy = "population_snapshot_required"
    elif population_n <= 1000:
        strategy = "census_preferred"
    else:
        strategy = "sampling_plan_required"

    plan = {
        "schema_version": "nf.primary_research_plan.v0.1",
        "population_snapshot_id": population_snapshot.get("snapshot_id"),
        "population_n": population_n,
        "sampling_strategy": strategy,
        "required_strata": ["grade", "qualification"],
        "questions": questions,
        "raw_response_contract": {
            "format": "long",
            "required_fields": ["respondent_id", "population_snapshot_id", "grade", "qualification", "question_id", "value"],
            "one_value_per_respondent_question": True,
            "raw_data_is_canonical": True,
        },
        "gaps_addressed": sorted({str(g.get("gap_id")) for g in gaps}),
    }
    plan["plan_sha256"] = sha256_json(plan)
    return plan


def _allowed_values(question: Mapping[str, Any]) -> Tuple[set, bool]:
    response_type = question.get("response_type")
    if response_type in {"likert_1_5", "likert_1_5_optional"}:
        return {"1", "2", "3", "4", "5"}, response_type.endswith("optional")
    if response_type == "yes_no":
        return {"yes", "no"}, False
    return set(), False


def validate_raw_responses(
    rows: Sequence[Mapping[str, Any]],
    plan: Mapping[str, Any],
) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    required_fields = set(plan.get("raw_response_contract", {}).get("required_fields", []))
    questions = {str(q["question_id"]): q for q in plan.get("questions", [])}
    expected_snapshot = plan.get("population_snapshot_id")
    seen = set()
    respondents = set()
    by_question = Counter()

    for idx, row in enumerate(rows):
        missing = sorted(field for field in required_fields if row.get(field) in (None, ""))
        if missing:
            failures.append({"row": idx, "failure": "missing_required_fields", "fields": missing})
            continue
        if row.get("population_snapshot_id") != expected_snapshot:
            failures.append({"row": idx, "failure": "population_snapshot_mismatch"})
        question_id = str(row.get("question_id"))
        question = questions.get(question_id)
        if not question:
            failures.append({"row": idx, "failure": "unknown_question_id", "value": question_id})
            continue
        key = (str(row.get("respondent_id")), question_id)
        if key in seen:
            failures.append({"row": idx, "failure": "duplicate_respondent_question", "value": list(key)})
        seen.add(key)
        respondents.add(str(row.get("respondent_id")))
        value = str(row.get("value")).lower()
        allowed, optional = _allowed_values(question)
        if allowed and value not in allowed:
            failures.append({"row": idx, "failure": "invalid_response_value", "question_id": question_id, "value": value})
        else:
            by_question[question_id] += 1

    response_n = len(respondents)
    population_n = plan.get("population_n")
    coverage = None
    if isinstance(population_n, int) and population_n > 0:
        coverage = round(response_n / population_n, 4)
        if response_n > population_n:
            failures.append({"failure": "respondents_exceed_population", "response_n": response_n, "population_n": population_n})

    for qid, question in questions.items():
        _, optional = _allowed_values(question)
        if not optional and by_question[qid] < response_n:
            warnings.append({"question_id": qid, "warning": "missing_required_question_responses", "valid_n": by_question[qid], "response_n": response_n})

    return {
        "valid": not failures,
        "failures": failures,
        "warnings": warnings,
        "response_n": response_n,
        "population_n": population_n,
        "coverage": coverage,
        "valid_n_by_question": dict(sorted(by_question.items())),
    }


def aggregate_responses(rows: Sequence[Mapping[str, Any]], plan: Mapping[str, Any]) -> Dict[str, Any]:
    validation = validate_raw_responses(rows, plan)
    if not validation["valid"]:
        raise NeedsFactoryValidationError("raw responses failed validation")

    questions = {str(q["question_id"]): q for q in plan.get("questions", [])}
    values_by_question: Dict[str, List[str]] = defaultdict(list)
    for row in rows:
        values_by_question[str(row["question_id"])].append(str(row["value"]).lower())

    aggregates: Dict[str, Any] = {}
    for qid, question in questions.items():
        values = values_by_question.get(qid, [])
        counts = Counter(values)
        n = len(values)
        record: Dict[str, Any] = {"valid_n": n, "counts": dict(sorted(counts.items()))}
        if question.get("response_type") in {"likert_1_5", "likert_1_5_optional"} and n:
            numeric = [int(v) for v in values]
            record["median"] = median(numeric)
            record["top2_n"] = sum(1 for v in numeric if v >= 4)
            record["top2_share"] = round(record["top2_n"] / n, 4)
        if question.get("response_type") == "yes_no" and n:
            record["yes_share"] = round(counts.get("yes", 0) / n, 4)
        aggregates[qid] = record

    return {
        "schema_version": "nf.primary_research_aggregates.v0.1",
        "population_snapshot_id": plan.get("population_snapshot_id"),
        "response_n": validation["response_n"],
        "population_n": validation["population_n"],
        "coverage": validation["coverage"],
        "aggregates": aggregates,
        "source": "deterministic aggregation of canonical raw responses",
    }
