from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

from clar_core.contracts import FactPacket, SourceItem, Story


_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4, "mai": 5, "iunie": 6,
    "iulie": 7, "august": 8, "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}
_EVENT_DATE_RE = re.compile(
    r"(?:zilei|data)\s+(?:de\s+)?([0-3]?\d)\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \n\t-–—:;,.")


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug[:90] or "stire"


def _count(text: str, patterns: Iterable[str]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                continue
    return None


def _event_date(text: str, fallback: datetime | None) -> str | None:
    match = _EVENT_DATE_RE.search(text)
    if match:
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).casefold())
        year = int(match.group(3))
        try:
            return datetime(year, int(month), day).date().isoformat() if month else None
        except ValueError:
            pass
    return fallback.date().isoformat() if fallback else None


def _display_date(value: str | None) -> str:
    if not value:
        return "data anunțată"
    months = {
        1: "ianuarie", 2: "februarie", 3: "martie", 4: "aprilie", 5: "mai", 6: "iunie",
        7: "iulie", 8: "august", 9: "septembrie", 10: "octombrie", 11: "noiembrie", 12: "decembrie",
    }
    try:
        year, month, day = map(int, value.split("-"))
        return f"{day} {months[month]} {year}"
    except (ValueError, KeyError):
        return value


class PublicSafetyExtractor:
    """Extract low-ambiguity operational facts from an official emergency-service item."""

    def __init__(self, *, scope_terms: Iterable[str] = ()) -> None:
        self.scope_terms = tuple(_clean(term).casefold() for term in scope_terms if _clean(term))

    def __call__(self, item: SourceItem) -> FactPacket | None:
        text = _clean(f"{item.title}\n{item.body_text or ''}")
        lower = text.casefold()
        if not any(term in lower for term in ("situații de urgență", "interven", "incend", "smurd", "112")):
            return None
        if self.scope_terms and not any(term in lower for term in self.scope_terms):
            return None

        total = _count(text, (
            r"gestionarea\s+a\s+(\d+)\s+de\s+situații\s+de\s+urgență",
            r"gestionat(?:e)?\s+(\d+)\s+situații\s+de\s+urgență",
        ))
        vegetation_fires = _count(text, (
            r"(?:dintre\s+care\s+)?(\d+)\s+incendii\s+de\s+vegetație",
            r"stingerea\s+a\s+(\d+)\s+incendii\s+de\s+vegetație",
        ))
        smurd = _count(text, (
            r"(\d+)\s+de\s+intervenții[^.]{0,120}\bSMURD\b",
            r"(\d+)\s+intervenții[^.]{0,120}\bSMURD\b",
        ))
        other = _count(text, (r"(\d+)\s+alte\s+situații\s+de\s+urgență",))
        hectares = _count(text, (r"(?:peste\s+|aproximativ\s+)?(\d+)\s+de?\s*hectare",))
        scope_hits = tuple(term for term in self.scope_terms if term in lower)
        event_date = _event_date(text, item.published_at)

        material = any(value is not None for value in (total, vegetation_fires, smurd, other, hectares))
        if not material and not any(word in lower for word in ("incendiu", "căutare", "salvare", "evacuare")):
            return None

        return FactPacket(
            source_item=item,
            kind="public_safety_operations",
            facts={
                "event_date": event_date,
                "total_emergencies": total,
                "vegetation_fires": vegetation_fires,
                "smurd_interventions": smurd,
                "other_emergencies": other,
                "affected_hectares": hectares,
                "scope_hits": scope_hits,
                "mentions_112": "112" in lower,
                "source_title": item.title,
            },
            evidence_urls=(item.canonical_url,),
            confidence="high",
            risk="medium",
            material=True,
        )


class PublicSafetyStoryComposer:
    def __init__(self, *, product_name: str, source_name: str) -> None:
        self.product_name = product_name
        self.source_name = source_name

    def __call__(self, packet: FactPacket) -> Story | None:
        if packet.kind != "public_safety_operations":
            return None
        f = packet.facts
        total = f.get("total_emergencies")
        fires = f.get("vegetation_fires")
        smurd = f.get("smurd_interventions")
        other = f.get("other_emergencies")
        hectares = f.get("affected_hectares")
        display_date = _display_date(str(f.get("event_date") or ""))

        if isinstance(total, int):
            headline = f"{self.source_name}: {total} de situații de urgență pe {display_date}"
            if isinstance(fires, int) and fires:
                headline += f", inclusiv {fires} incendii de vegetație"
        else:
            headline = _clean(str(f.get("source_title") or "Intervenție a serviciilor de urgență"))

        dek_bits = [f"Datele provin din informarea oficială publicată de {self.source_name}."]
        if isinstance(smurd, int):
            dek_bits.append(f"Au fost raportate {smurd} intervenții SMURD.")
        if isinstance(fires, int):
            dek_bits.append(f"Informarea menționează {fires} incendii de vegetație.")
        dek = " ".join(dek_bits)

        paragraphs: list[str] = []
        if isinstance(total, int):
            paragraphs.append(f"{self.source_name} a raportat {total} de situații de urgență gestionate pe {display_date}.")
        if isinstance(fires, int):
            detail = f"Dintre acestea, informarea oficială indică {fires} incendii de vegetație"
            if isinstance(hectares, int):
                detail += f" și peste sau aproximativ {hectares} de hectare afectate, conform formulării din sursă"
            paragraphs.append(detail + ".")
        if isinstance(smurd, int):
            paragraphs.append(f"Echipajele SMURD au avut {smurd} intervenții pentru prim ajutor și asistență medicală, potrivit bilanțului oficial.")
        if isinstance(other, int):
            paragraphs.append(f"ISU a mai consemnat {other} alte situații de urgență în același bilanț.")
        if f.get("mentions_112"):
            paragraphs.append("În recomandările preventive, sursa oficială indică apelarea numărului unic 112 atunci când este observată o situație de urgență.")
        paragraphs.append(f"Sursa informațiilor este comunicarea oficială a {self.source_name}.")

        story_id = hashlib.sha256(packet.source_item.canonical_url.encode("utf-8")).hexdigest()[:16]
        published_at = packet.source_item.published_at or datetime.now(timezone.utc)
        scope_hits = tuple(f.get("scope_hits") or ())
        return Story(
            story_id=story_id,
            slug=_slugify(headline),
            section="SIGURANȚĂ PUBLICĂ",
            headline=headline,
            dek=dek,
            paragraphs=tuple(paragraphs),
            source_urls=tuple(packet.evidence_urls),
            published_at=published_at,
            media_query=str(scope_hits[0]) if scope_hits else None,
            metadata={"kind": packet.kind, "confidence": packet.confidence, "risk": packet.risk, "generator": "deterministic"},
        )
