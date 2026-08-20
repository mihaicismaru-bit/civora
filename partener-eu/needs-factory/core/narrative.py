from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, List, Mapping, Sequence

from .engine import NeedsFactoryValidationError, sha256_json


NEED_TAG_RE = re.compile(r"\[NEED:([^\]]+)\]")
EVIDENCE_TAG_RE = re.compile(r"\[EV:([^\]]+)\]")
NEED_HEADING_RE = re.compile(r"^###\s+.+?\s+\[NEED:([^\]]+)\]\s*$", re.MULTILINE)


def _text(value: Any) -> str:
    if value is None:
        return "-"
    return " ".join(str(value).replace("\r", " ").replace("\n", " ").split())


def _format_number(value: Any) -> str:
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        rendered = f"{value:.4f}".rstrip("0").rstrip(".")
        return rendered or "0"
    return _text(value)


def _format_measure(measure: Mapping[str, Any]) -> str:
    name = _text(measure.get("name") or measure.get("measure_type") or "indicator")
    measure_type = measure.get("measure_type")
    value = measure.get("value")
    unit = _text(measure.get("unit")) if measure.get("unit") else ""
    if measure_type == "share" and unit == "proportion" and isinstance(value, (int, float)):
        display = f"{float(value) * 100:.1f}%"
        numerator = measure.get("numerator")
        denominator = measure.get("denominator_universe")
        suffix = ""
        if numerator is not None or denominator:
            suffix = f"; numărător={_format_number(numerator)}, univers={_text(denominator)}"
        return f"{name}: {display}{suffix}"
    if unit:
        return f"{name}: {_format_number(value)} {unit}"
    return f"{name}: {_format_number(value)}"


def _evidence_refs(pack: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    refs: Dict[str, Mapping[str, Any]] = {}
    for claim in pack.get("claim_ledger", []) or []:
        for ref in claim.get("evidence_refs", []) or []:
            evidence_id = str(ref.get("evidence_id"))
            refs.setdefault(evidence_id, ref)
    return refs


def render_source_register(pack: Mapping[str, Any]) -> str:
    refs = _evidence_refs(pack)
    lines = [
        "# Registrul surselor — Needs Factory",
        "",
        "Registrul de mai jos este derivat exclusiv din `NARRATIVE_READY_PACK` și păstrează identificatorii de dovadă folosiți în analiză.",
        "",
    ]
    for evidence_id in sorted(refs):
        ref = refs[evidence_id]
        lines.append(f"## [EV:{evidence_id}] {_text(ref.get('source'))}")
        lines.append("")
        lines.append(f"- Teritoriu: {_text(ref.get('territory'))}")
        lines.append(f"- Scop: {_text(ref.get('scope'))}")
        lines.append(f"- Perioadă/data: {_text(ref.get('period'))}")
        lines.append(f"- Tier: {_text(ref.get('tier'))}")
        if ref.get("source_type"):
            lines.append(f"- Tip sursă: {_text(ref.get('source_type'))}")
        if ref.get("source_document_id"):
            lines.append(f"- Document: {_text(ref.get('source_document_id'))}")
        if ref.get("population_snapshot_id"):
            lines.append(f"- Population snapshot: {_text(ref.get('population_snapshot_id'))}")
        if ref.get("source_url"):
            lines.append(f"- URL: {_text(ref.get('source_url'))}")
        constructs = ref.get("constructs") or []
        if constructs:
            lines.append(f"- Constructe măsurate/susținute: {', '.join(_text(value) for value in constructs)}")
        measures = ref.get("measures") or []
        if measures:
            lines.append("- Măsuri:")
            for measure in measures:
                lines.append(f"  - {_format_measure(measure)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def render_analysis_markdown(pack: Mapping[str, Any], *, title: str = "Analiza de nevoi") -> str:
    if not (pack.get("release_gate") or {}).get("ready_for_narrative"):
        raise NeedsFactoryValidationError("narrative compiler requires a passed release gate")

    ledger = list(pack.get("claim_ledger") or [])
    if not ledger:
        raise NeedsFactoryValidationError("narrative compiler requires at least one validated need")

    lines: List[str] = [
        f"# {_text(title)}",
        "",
        f"**Proiect:** {_text(pack.get('project_id'))}  ",
        f"**Teritoriu:** {_text(pack.get('territory'))}  ",
        f"**Grup țintă:** {_text(pack.get('target_group'))}",
        "",
        "## 1. Metodologie și standard de probă",
        "",
        "Prezenta analiză este compilată exclusiv din nevoi care au trecut validarea Needs Factory. Fiecare nevoie materială este legată de dovezi identificate explicit, iar limitele de aplicabilitate ale dovezilor sunt păstrate. Lipsa unei dovezi nu este completată prin presupuneri, indicatorii programului nu sunt folosiți pentru a crea nevoi, iar obligațiile orizontale nu sunt tratate automat ca probleme empirice ale grupului țintă.",
        "",
        "## 2. Sinteza nevoilor prioritare",
        "",
        "| Rang | Nevoie | Scop | Nr. dovezi |",
        "|---:|---|---|---:|",
    ]
    for claim in ledger:
        lines.append(
            f"| {_format_number(claim.get('rank'))} | {_text(claim.get('title'))} | {_text(claim.get('scope'))} | {len(claim.get('evidence_refs') or [])} |"
        )

    lines.extend(["", "## 3. Nevoi identificate și fundamentare", ""])
    for index, claim in enumerate(ledger, start=1):
        need_id = str(claim["need_id"])
        lines.append(f"### 3.{index}. {_text(claim.get('title'))} [NEED:{need_id}]")
        lines.append("")
        lines.append(_text(claim.get("statement")))
        lines.append("")
        lines.append(f"**Scopul afirmației:** {_text(claim.get('scope'))}.")
        lines.append("")
        lines.append("**Baza probatorie validată:**")
        lines.append("")
        for ref in claim.get("evidence_refs", []) or []:
            evidence_id = str(ref["evidence_id"])
            descriptor = f"{_text(ref.get('source'))}; teritoriu={_text(ref.get('territory'))}; perioadă={_text(ref.get('period'))}; tier={_text(ref.get('tier'))}"
            lines.append(f"- [EV:{evidence_id}] {descriptor}.")
            for measure in ref.get("measures", []) or []:
                lines.append(f"  - {_format_measure(measure)}")
        limitation = _text(claim.get("prohibited_overclaim")) if claim.get("prohibited_overclaim") else "Nu se formulează concluzii dincolo de scopul și populația susținute de dovezile de mai sus."
        lines.append("")
        lines.append(f"**Limită de interpretare:** {limitation}")
        lines.append("")

    lines.extend(["## 4. Limitări și precauții metodologice", ""])
    causal_warnings = list((pack.get("causal_validation") or {}).get("warnings") or [])
    if causal_warnings:
        lines.append("Modelul cauzal conține următoarele precauții validate:")
        lines.append("")
        for warning in causal_warnings:
            lines.append(f"- {_text(warning.get('warning'))}: {_text(warning.get('node_id'))}")
    else:
        lines.append("Modelul cauzal nu conține avertismente nerezolvate la momentul compilării.")
    lines.extend([
        "",
        "Nu există goluri de evidență blocante în release gate-ul folosit pentru această compilație. Orice modificare ulterioară a populației, surselor sau datelor primare impune o nouă validare a checkpointurilor dependente.",
        "",
        "## 5. Trasabilitate și surse",
        "",
        "Marcajele de audit `NEED:<id>` și `EV:<id>` sunt parte a mecanismului de audit. În corpul analizei, marcajele efective folosesc exclusiv identificatori validați; registrul complet al surselor este livrat separat în `SOURCE_REGISTER.md`.",
        "",
    ])
    return "\n".join(lines).rstrip() + "\n"


def _need_sections(markdown: str) -> Dict[str, str]:
    matches = list(NEED_HEADING_RE.finditer(markdown))
    sections: Dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else markdown.find("\n## 4.", start)
        if end < 0:
            end = len(markdown)
        sections[match.group(1)] = markdown[start:end]
    return sections


def validate_compiled_narrative(markdown: str, pack: Mapping[str, Any]) -> Dict[str, Any]:
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    ledger = list(pack.get("claim_ledger") or [])
    known_needs = {str(claim["need_id"]) for claim in ledger}
    known_evidence = set(_evidence_refs(pack))

    need_tags = NEED_TAG_RE.findall(markdown)
    evidence_tags = EVIDENCE_TAG_RE.findall(markdown)
    need_counts = Counter(need_tags)
    unknown_needs = sorted(set(need_tags) - known_needs)
    unknown_evidence = sorted(set(evidence_tags) - known_evidence)
    if unknown_needs:
        failures.append({"failure": "unknown_need_tags", "values": unknown_needs})
    if unknown_evidence:
        failures.append({"failure": "unknown_evidence_tags", "values": unknown_evidence})

    missing_needs = sorted(known_needs - set(need_tags))
    if missing_needs:
        failures.append({"failure": "missing_need_sections", "values": missing_needs})
    duplicate_needs = sorted(need for need, count in need_counts.items() if count != 1)
    if duplicate_needs:
        failures.append({"failure": "need_marker_not_exactly_once", "values": duplicate_needs})

    sections = _need_sections(markdown)
    for claim in ledger:
        need_id = str(claim["need_id"])
        section = sections.get(need_id)
        if section is None:
            continue
        expected_evidence = {str(ref["evidence_id"]) for ref in (claim.get("evidence_refs") or [])}
        found_evidence = set(EVIDENCE_TAG_RE.findall(section))
        missing = sorted(expected_evidence - found_evidence)
        unrelated = sorted(found_evidence - expected_evidence)
        if missing:
            failures.append({"failure": "need_section_missing_evidence", "need_id": need_id, "values": missing})
        if unrelated:
            failures.append({"failure": "need_section_contains_unrelated_evidence", "need_id": need_id, "values": unrelated})
        limitation = claim.get("prohibited_overclaim")
        if limitation and _text(limitation) not in section:
            failures.append({"failure": "need_section_missing_interpretation_limit", "need_id": need_id})

    missing_evidence_global = sorted(known_evidence - set(evidence_tags))
    if missing_evidence_global:
        warnings.append({"warning": "evidence_not_rendered_anywhere", "values": missing_evidence_global})
    if not (pack.get("release_gate") or {}).get("ready_for_narrative"):
        failures.append({"failure": "pack_release_gate_not_ready"})

    return {
        "schema_version": "nf.narrative_validation.v0.1",
        "valid": not failures,
        "failures": failures,
        "warnings": warnings,
        "need_count": len(known_needs),
        "evidence_count": len(known_evidence),
        "rendered_need_tags": len(need_tags),
        "rendered_evidence_tags": len(evidence_tags),
    }


def compile_analysis(pack: Mapping[str, Any], *, title: str = "Analiza de nevoi") -> Dict[str, Any]:
    markdown = render_analysis_markdown(pack, title=title)
    source_register = render_source_register(pack)
    validation = validate_compiled_narrative(markdown, pack)
    if not validation["valid"]:
        raise NeedsFactoryValidationError(f"compiled narrative failed validation: {validation['failures']}")
    return {
        "schema_version": "nf.compiled_analysis.v0.1",
        "markdown": markdown,
        "source_register_markdown": source_register,
        "validation": validation,
        "markdown_sha256": sha256_json(markdown),
        "source_register_sha256": sha256_json(source_register),
        "source_pack_sha256": pack.get("pack_sha256"),
    }
