from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        if data.strip():
            self.parts.append(data)

    def text(self) -> str:
        return " ".join(self.parts)


def _normalize(value: str) -> str:
    value = html.unescape(value or "")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = value.lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def _extract_visible_text(raw: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        return parser.text()
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw)


def read_source(url: str, timeout: float = 15.0, max_bytes: int = 1_500_000) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "CIVORA-Core-v2-Historical-Fact-Evidence/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = int(getattr(response, "status", 0) or 0)
            final_url = str(response.geturl() or url)
            content_type = str(response.headers.get("Content-Type") or "")
            body = response.read(max_bytes + 1)
    except HTTPError as exc:
        return {
            "requested_url": url,
            "final_url": getattr(exc, "url", url),
            "http_status": int(getattr(exc, "code", 0) or 0),
            "readback_ok": False,
            "error": str(exc),
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "requested_url": url,
            "final_url": None,
            "http_status": None,
            "readback_ok": False,
            "error": str(exc),
        }

    truncated = len(body) > max_bytes
    bounded = body[:max_bytes]
    raw = bounded.decode("utf-8", errors="ignore")
    visible = _extract_visible_text(raw)
    return {
        "requested_url": url,
        "final_url": final_url,
        "http_status": status,
        "content_type": content_type,
        "bytes_hashed": len(bounded),
        "content_sha256": hashlib.sha256(bounded).hexdigest() if bounded else None,
        "bounded_read_truncated": truncated,
        "readback_ok": bool(200 <= status < 400 and bounded),
        "_normalized_text": _normalize(visible),
        "_raw_lower": raw.lower(),
    }


SPECS: dict[str, dict[str, Any]] = {
    "valcea-apa-canal-contract-152m-20260902": {
        "sources": {
            "apavil": {
                "name": "APAVIL S.A. — comunicat privind semnarea contractului de finanțare",
                "url": "https://apavil.ro/?p=8650",
                "first_party": True,
                "identity_fragments": ["apavil s a", "proiect regional de dezvoltare a infrastructurii de apa si apa uzata in judetul valcea"],
                "raw_link_fragments": [],
            }
        },
        "fields": {
            "what": {
                "value": "Contractul de finanțare nr. 179 pentru Proiectul Regional de Dezvoltare a Infrastructurii de Apă și Apă Uzată în Județul Vâlcea a fost semnat.",
                "source": "apavil",
                "fragments": ["contractul de finantare", "nr 179", "cod smis 364180"],
            },
            "who": {
                "value": "APAVIL S.A. și Ministerul Investițiilor și Proiectelor Europene",
                "source": "apavil",
                "fragments": ["apavil s a", "ministerul investitiilor si proiectelor europene"],
            },
            "where": {
                "value": "Județul Vâlcea",
                "source": "apavil",
                "fragments": ["judetul valcea"],
            },
            "when": {
                "value": "28 august 2026",
                "source": "apavil",
                "fragments": ["28 08 2026", "nr 179"],
            },
            "why_it_matters": {
                "value": "Contractul finanțează investiții regionale de apă și apă uzată, cu o valoare totală de 931.728.052,15 lei și finanțare nerambursabilă maximă de 709.812.993,20 lei.",
                "source": "apavil",
                "fragments": ["931 728 052 15", "709 812 993 20", "92 12"],
            },
        },
        "source_label": "APAVIL S.A. — comunicat first-party privind Contractul de finanțare nr. 179",
        "source_url": "https://apavil.ro/?p=8650",
        "claims": [
            {
                "text": "Contractul de finanțare nr. 179 pentru proiectul regional a fost semnat la 28 august 2026.",
                "source": "apavil",
                "fragments": ["28 08 2026", "nr 179", "cod smis 364180"],
            },
            {
                "text": "Valoarea totală a contractului este 931.728.052,15 lei, iar finanțarea nerambursabilă maximă este 709.812.993,20 lei.",
                "source": "apavil",
                "fragments": ["931 728 052 15", "709 812 993 20"],
            },
        ],
    },
    "cet-govora-cine-a-decis-oprirea-20260821": {
        "sources": {
            "h225": {
                "name": "HCL Râmnicu Vâlcea nr. 225/2026 — text public și legătură la documentul municipal",
                "url": "https://hcl.usr.ro/ramnicu_valcea/2026/h225",
                "first_party": False,
                "identity_fragments": ["hotararea nr 225", "municipiul ramnicu valcea", "cet govora"],
                "raw_link_fragments": ["dm.primariavl.ro"],
            },
            "h5": {
                "name": "HCL Râmnicu Vâlcea nr. 5/2026 — text public și legătură la documentul municipal",
                "url": "https://hcl.usr.ro/ramnicu_valcea/2026/h5",
                "first_party": False,
                "identity_fragments": ["hotararea nr 5", "municipiul ramnicu valcea", "energie termica"],
                "raw_link_fragments": ["dm.primariavl.ro"],
            },
        },
        "fields": {
            "what": {
                "value": "CET Govora a notificat încetarea definitivă a producției cel târziu la 31 august 2026, iar Municipiul Râmnicu Vâlcea a aprobat cadrul pentru continuitatea serviciului public de alimentare cu energie termică.",
                "source": "h225",
                "fragments": ["cel tarziu la data de 31 08 2026 isi va inceta definitiv productia", "continuitatii serviciului public de alimentare cu energie termica"],
            },
            "who": {
                "value": "CET Govora S.A. și Municipiul Râmnicu Vâlcea",
                "source": "h225",
                "fragments": ["societatea cet govora sa", "municipiul ramnicu valcea"],
            },
            "where": {
                "value": "Râmnicu Vâlcea",
                "source": "h225",
                "fragments": ["municipiul ramnicu valcea"],
            },
            "when": {
                "value": "31 august 2026",
                "source": "h225",
                "fragments": ["31 08 2026", "inceta definitiv productia"],
            },
            "why_it_matters": {
                "value": "Oprirea producției pe cărbune impune surse de înlocuire și o nouă organizare a serviciului public de alimentare cu energie termică pentru continuitatea SACET Râmnicu Vâlcea.",
                "source": "h225",
                "fragments": ["contractului de delegare a gestiunii serviciului public de alimentare cu energie termica", "asigurarea continuitatii"],
            },
        },
        "source_label": "HCL Râmnicu Vâlcea nr. 225/2026 și HCL nr. 5/2026 — evidence-bound public text with official municipal document links",
        "source_url": "https://hcl.usr.ro/ramnicu_valcea/2026/h225",
        "claims": [
            {
                "text": "CET Govora a notificat că își va înceta definitiv producția cel târziu la 31 august 2026, invocând dispoziții legale imperative privind eliminarea producției pe bază de cărbune.",
                "source": "h225",
                "fragments": ["31 08 2026 isi va inceta definitiv productia", "dispozitiilor legale imperative", "eliminarea productiei de energie pe baza de carbune"],
            },
            {
                "text": "Studiul aprobat indică delegarea prin concesiune ca soluție și cere Municipiului Râmnicu Vâlcea să demareze achiziția publică pentru contractul de delegare a serviciului termic.",
                "source": "h225",
                "fragments": ["modalitatea de delegare a serviciului public de alimentare cu energie termica spaet catre un operator spaet prin concesiune", "municipiul ramnicu valcea trebuie sa demareze o procedura de achizitie publica", "contractului de delegare a gestiunii serviciului public de alimentare cu energie termica"],
            },
            {
                "text": "De la 1 ianuarie 2026, prețul de facturare pentru populația racordată la distribuție este 553,15 lei/Gcal, iar pentru populația racordată la transport 400,28 lei/Gcal, fără TVA.",
                "source": "h5",
                "fragments": ["01 01 2026", "553 15 lei gcal", "400 28 lei gcal", "exclusiv tva"],
            },
        ],
    },
}


def _public_snapshot(source: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in source.items() if not key.startswith("_")}


def _fragments_present(normalized_text: str, fragments: list[str]) -> tuple[bool, list[str]]:
    normalized_fragments = [_normalize(fragment) for fragment in fragments]
    missing = [fragment for fragment, normalized in zip(fragments, normalized_fragments) if normalized not in normalized_text]
    return not missing, missing


def build(
    candidates: dict[str, Any],
    *,
    reader: Callable[[str], dict[str, Any]] = read_source,
) -> dict[str, Any]:
    story_ids = [str(value) for value in candidates.get("first_ten_candidate_ids") or []]
    rows: list[dict[str, Any]] = []
    ready_count = 0

    for story_id in story_ids:
        spec = SPECS.get(story_id)
        row: dict[str, Any] = {
            "story_id": story_id,
            "publication_authority": "NONE",
            "live_promotion_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "fact_kernel_evidence_ready": False,
            "state": "BLOCKED_NO_HISTORICAL_EVIDENCE_SPEC",
            "source_readback": {},
            "evidence": [],
        }
        if not isinstance(spec, dict):
            rows.append(row)
            continue

        source_results: dict[str, dict[str, Any]] = {}
        source_failures: list[str] = []
        for source_key, source_spec in spec["sources"].items():
            result = reader(str(source_spec["url"]))
            source_results[source_key] = result
            normalized_text = str(result.get("_normalized_text") or "")
            raw_lower = str(result.get("_raw_lower") or "")
            if result.get("readback_ok") is not True:
                source_failures.append(f"{source_key}:readback")
                continue
            ok, missing = _fragments_present(normalized_text, list(source_spec.get("identity_fragments") or []))
            if not ok:
                source_failures.append(f"{source_key}:identity:{'|'.join(missing)}")
            for raw_fragment in source_spec.get("raw_link_fragments") or []:
                if str(raw_fragment).lower() not in raw_lower:
                    source_failures.append(f"{source_key}:official_link:{raw_fragment}")

        row["source_readback"] = {
            key: {
                **_public_snapshot(result),
                "source_name": spec["sources"][key]["name"],
                "first_party": spec["sources"][key]["first_party"],
                "official_document_link_required": bool(spec["sources"][key].get("raw_link_fragments")),
            }
            for key, result in source_results.items()
        }
        if source_failures:
            row["state"] = "BLOCKED_SOURCE_IDENTITY_OR_READBACK"
            row["blockers"] = source_failures
            rows.append(row)
            continue

        evidence: list[dict[str, Any]] = []
        field_values: dict[str, str] = {}
        evidence_ids: list[str] = []
        blockers: list[str] = []

        for field_name, field_spec in spec["fields"].items():
            source_key = str(field_spec["source"])
            normalized_text = str(source_results[source_key].get("_normalized_text") or "")
            ok, missing = _fragments_present(normalized_text, list(field_spec["fragments"]))
            evidence_id = f"hist:{story_id}:field:{field_name}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "kind": "FIELD_EVIDENCE",
                    "field": field_name,
                    "value": field_spec["value"],
                    "source_key": source_key,
                    "source_url": spec["sources"][source_key]["url"],
                    "source_content_sha256": source_results[source_key].get("content_sha256"),
                    "required_fragments": field_spec["fragments"],
                    "verified": ok,
                    "missing_fragments": missing,
                }
            )
            if ok:
                field_values[field_name] = str(field_spec["value"])
                evidence_ids.append(evidence_id)
            else:
                blockers.append(f"field:{field_name}")

        claim_texts: list[str] = []
        claim_bindings: list[dict[str, Any]] = []
        for idx, claim_spec in enumerate(spec["claims"]):
            source_key = str(claim_spec["source"])
            normalized_text = str(source_results[source_key].get("_normalized_text") or "")
            ok, missing = _fragments_present(normalized_text, list(claim_spec["fragments"]))
            evidence_id = f"hist:{story_id}:claim:{idx}"
            evidence.append(
                {
                    "evidence_id": evidence_id,
                    "kind": "CLAIM_EVIDENCE",
                    "claim_index": idx,
                    "claim": claim_spec["text"],
                    "source_key": source_key,
                    "source_url": spec["sources"][source_key]["url"],
                    "source_content_sha256": source_results[source_key].get("content_sha256"),
                    "required_fragments": claim_spec["fragments"],
                    "verified": ok,
                    "missing_fragments": missing,
                }
            )
            if ok:
                claim_texts.append(str(claim_spec["text"]))
                evidence_ids.append(evidence_id)
                claim_bindings.append({"claim_index": idx, "claim": claim_spec["text"], "evidence_ids": [evidence_id]})
            else:
                blockers.append(f"claim:{idx}")

        row["evidence"] = evidence
        row["claim_evidence"] = claim_bindings
        if blockers or len(field_values) != len(spec["fields"]) or len(claim_texts) != len(spec["claims"]):
            row["state"] = "BLOCKED_INCOMPLETE_FIELD_OR_CLAIM_EVIDENCE"
            row["blockers"] = blockers
            rows.append(row)
            continue

        row["fact_kernel"] = {
            "what": field_values["what"],
            "who": field_values["who"],
            "where": field_values["where"],
            "when": field_values["when"],
            "why_it_matters": field_values["why_it_matters"],
            "source": spec["source_label"],
            "source_url": spec["source_url"],
            "claims": claim_texts,
            "evidence_ids": evidence_ids,
        }
        row["fact_kernel_evidence_ready"] = True
        row["state"] = "FACT_KERNEL_EVIDENCE_READY_SHADOW"
        ready_count += 1
        rows.append(row)

    return {
        "schema_version": "1.0",
        "mode": "READ_ONLY_HISTORICAL_FACT_KERNEL_EVIDENCE",
        "publication_authority": "NONE",
        "live_promotion_allowed": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        "candidate_count": len(rows),
        "fact_kernel_evidence_ready_count": ready_count,
        "truth_rule": "A historical FactKernel may be materialized for shadow replay only when every semantic field and every included claim is directly matched against bounded external source content. Legacy prose is never reverse-engineered into evidence, and this artifact grants no live publication authority.",
        "rows": rows,
    }


def _load(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object document: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Build evidence-bound historical FactKernel candidates for Core v2 shadow replay")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build(_load(args.candidates))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "candidate_count": result["candidate_count"],
        "fact_kernel_evidence_ready_count": result["fact_kernel_evidence_ready_count"],
        "states": {row["story_id"]: row["state"] for row in result["rows"]},
        "publication_authority": "NONE",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
