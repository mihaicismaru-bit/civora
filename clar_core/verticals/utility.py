from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from typing import Iterable

from clar_core.contracts import FactPacket, SourceItem, Story


_DATE_RE = re.compile(r"\b([0-3]?\d)[.\-/]([01]?\d)[.\-/](20\d{2})\b")
_TIME_RANGE_RE = re.compile(
    r"\b([0-2]?\d)[.:]([0-5]\d)\s*(?:-|–|—|până\s+la)\s*([0-2]?\d)[.:]([0-5]\d)\b",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \n\t-–—:;,.")


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug[:90] or "stire"


def _sentence_with(text: str, needles: Iterable[str]) -> str | None:
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        lower = sentence.lower()
        if all(needle.lower() in lower for needle in needles):
            return _clean(sentence)
    return None


def _extract_area_hint(title: str, area_prefixes: Iterable[str] = ()) -> str | None:
    patterns = [
        r"cartier(?:ul|ele)?\s+([^,]+?)(?:,|\s+(?:joi|vineri|luni|marți|miercuri|sâmbătă|duminică)\b|$)",
        r"zona\s+([^,]+?)(?:,|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            for prefix in area_prefixes:
                value = re.sub(rf"^{re.escape(prefix)}\s+", "", value, flags=re.IGNORECASE)
            return _clean(value)
    return None


def _extract_affected(text: str) -> str | None:
    match = re.search(
        r"afecta(?:ți|te|t)[^:]{0,80}(?:fiind|sunt)?\s*:?\s*-*\s*(.+?)(?=(?:Atențion|Compania de Apă|Echipele|Ne cerem|Vă mulțumim|$))",
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    return _clean(match.group(1))[:900]


def _extract_date(text: str) -> str | None:
    match = _DATE_RE.search(text)
    if not match:
        return None
    day, month, year = map(int, match.groups())
    try:
        return datetime(year, month, day).date().isoformat()
    except ValueError:
        return None


def _extract_time_range(text: str) -> tuple[str, str] | None:
    match = _TIME_RANGE_RE.search(text)
    if not match:
        return None
    sh, sm, eh, em = map(int, match.groups())
    if sh > 23 or eh > 23:
        return None
    return f"{sh:02d}:{sm:02d}", f"{eh:02d}:{em:02d}"


class WaterUtilityExtractor:
    """Extract low-risk public-service facts from an official utility item."""

    def __init__(self, *, allowed_localities: Iterable[str], area_prefixes: Iterable[str] = ()) -> None:
        self.allowed_localities = tuple(x.casefold() for x in allowed_localities)
        self.area_prefixes = tuple(area_prefixes)

    def __call__(self, item: SourceItem) -> FactPacket | None:
        text = _clean(f"{item.title}\n{item.body_text or ''}")
        lower = text.casefold()
        if "apă" not in lower and "apa" not in lower:
            return None
        if not any(word in lower for word in ("întrerup", "oprire", "restric", "furnizare")):
            return None
        if self.allowed_localities and not any(loc in lower for loc in self.allowed_localities):
            return None

        kind = "water_supply_restriction" if "restric" in lower else "water_supply_interruption"
        time_range = _extract_time_range(text)
        event_date = _extract_date(text)
        area_hint = _extract_area_hint(item.title, self.area_prefixes)
        affected = _extract_affected(item.body_text or "")
        reason = _sentence_with(item.body_text or "", ("lucr",))
        turbidity = bool(re.search(r"turbid|limpez", lower))

        if not event_date or not (area_hint or affected):
            return None

        facts = {
            "event_date": event_date,
            "start_time": time_range[0] if time_range else None,
            "end_time": time_range[1] if time_range else None,
            "area_hint": area_hint,
            "affected": affected,
            "reason": reason,
            "turbidity_advisory": turbidity,
            "source_title": item.title,
        }
        return FactPacket(
            source_item=item,
            kind=kind,
            facts=facts,
            evidence_urls=(item.canonical_url,),
            confidence="high",
            risk="low",
            material=True,
        )


class UtilityStoryComposer:
    def __init__(self, *, product_name: str, source_name: str) -> None:
        self.product_name = product_name
        self.source_name = source_name

    def __call__(self, packet: FactPacket) -> Story | None:
        if packet.kind not in {"water_supply_interruption", "water_supply_restriction"}:
            return None
        f = packet.facts
        event_date = str(f.get("event_date") or "")
        area = _clean(str(f.get("area_hint") or ""))
        affected = _clean(str(f.get("affected") or ""))
        start = f.get("start_time")
        end = f.get("end_time")
        interval = f"{start}–{end}" if start and end else None

        if packet.kind == "water_supply_restriction":
            headline = f"Furnizarea apei va fi restricționată pe {event_date}"
        else:
            headline = f"Apa va fi oprită pe {event_date}"
        if area:
            headline += f" în {area}"
        if interval:
            headline += f": intervalul {interval}"

        dek_bits = [f"{self.source_name} a anunțat măsura pentru {event_date}."]
        if interval:
            dek_bits.append(f"Intervalul anunțat este {interval}.")
        if area:
            dek_bits.append(f"Zona indicată este {area}.")
        dek = " ".join(dek_bits)

        paragraphs: list[str] = []
        first = f"{self.source_name} anunță "
        first += "restricționarea furnizării apei" if packet.kind == "water_supply_restriction" else "întreruperea alimentării cu apă"
        first += f" pentru {event_date}"
        if interval:
            first += f", în intervalul {interval}"
        if area:
            first += f", în {area}"
        paragraphs.append(first + ".")
        if affected:
            paragraphs.append("Potrivit anunțului oficial, sunt afectați: " + affected + ".")
        if f.get("reason"):
            paragraphs.append("Motivul indicat de operator: " + _clean(str(f["reason"])) + ".")
        if f.get("turbidity_advisory"):
            paragraphs.append(
                "Operatorul avertizează că, după golirea și reumplerea rețelei, apa poate avea temporar turbiditate; consumul trebuie evitat până la limpezire dacă apare acest fenomen."
            )
        paragraphs.append(f"Sursa informației este anunțul oficial publicat de {self.source_name}.")

        seed = packet.source_item.canonical_url.encode("utf-8")
        story_id = hashlib.sha256(seed).hexdigest()[:16]
        slug = _slugify(headline)
        published_at = packet.source_item.published_at or datetime.now(timezone.utc)
        return Story(
            story_id=story_id,
            slug=slug,
            section="UTILITĂȚI",
            headline=headline,
            dek=dek,
            paragraphs=tuple(paragraphs),
            source_urls=tuple(packet.evidence_urls),
            published_at=published_at,
            media_query=area or None,
            metadata={"kind": packet.kind, "confidence": packet.confidence, "generator": "deterministic"},
        )
