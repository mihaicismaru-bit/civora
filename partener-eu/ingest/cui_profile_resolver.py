#!/usr/bin/env python3
"""PARTENER.EU persistent company/organisation profile resolver by Romanian CUI.

Core contract:
- one CUI in;
- canonical profile out;
- official public ANAF identity/fiscal/address + annual financial statements;
- last-known-good source cache with TTL and atomic writes;
- source/capability plan for privileged or batch enrichments (ONRC, MJ, etc.);
- no synthetic values and no silent overwrite after upstream failures.

This resolver intentionally does not scrape authenticated ONRC pages. Governance
and beneficial-owner fields are capability-gated until an authorised ONRC adapter
is configured.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Callable

from anaf_company_financials import fetch_series, normalize_cui, parse_years
from anaf_company_identity import fetch_identity

HERE = Path(__file__).resolve().parent
SOURCE_POLICY = HERE / "cui_profile_sources.json"
DEFAULT_CACHE = HERE / "state" / "cui_profiles"


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat()


def parse_iso(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def norm_text(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9]+", " ", text).strip().upper()
    return re.sub(r"\s+", " ", text)


def load_policy() -> dict[str, Any]:
    return json.loads(SOURCE_POLICY.read_text(encoding="utf-8"))


def cache_file(cache_dir: Path, cui: str) -> Path:
    return cache_dir / f"{cui}.json"


def read_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schemaVersion": "1.0", "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"schemaVersion": "1.0", "sources": {}}
    except (OSError, json.JSONDecodeError):
        return {"schemaVersion": "1.0", "sources": {}}


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def cache_fresh(entry: dict[str, Any], now: dt.datetime) -> bool:
    expires = parse_iso(entry.get("expiresAt"))
    return bool(expires and expires > now and entry.get("payload") is not None)


def resolve_source(
    *,
    source_id: str,
    fetcher: Callable[[], dict[str, Any]],
    ttl_hours: int,
    cache: dict[str, Any],
    now: dt.datetime,
    cache_only: bool,
    force_refresh: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    sources = cache.setdefault("sources", {})
    cached = sources.get(source_id) if isinstance(sources.get(source_id), dict) else None

    if cached and cache_fresh(cached, now) and not force_refresh:
        return cached.get("payload"), {
            "source": source_id,
            "mode": "CACHE_FRESH",
            "observedAt": cached.get("observedAt"),
            "expiresAt": cached.get("expiresAt"),
            "error": None,
        }

    if cache_only:
        if cached and cached.get("payload") is not None:
            return cached.get("payload"), {
                "source": source_id,
                "mode": "CACHE_STALE" if not cache_fresh(cached, now) else "CACHE_FRESH",
                "observedAt": cached.get("observedAt"),
                "expiresAt": cached.get("expiresAt"),
                "error": None,
            }
        return None, {"source": source_id, "mode": "UNAVAILABLE", "error": "CACHE_MISS"}

    try:
        payload = fetcher()
        observed = now
        entry = {
            "observedAt": iso(observed),
            "expiresAt": iso(observed + dt.timedelta(hours=max(1, ttl_hours))),
            "payload": payload,
        }
        sources[source_id] = entry
        return payload, {
            "source": source_id,
            "mode": "LIVE",
            "observedAt": entry["observedAt"],
            "expiresAt": entry["expiresAt"],
            "error": None,
        }
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        if cached and cached.get("payload") is not None:
            return cached.get("payload"), {
                "source": source_id,
                "mode": "CACHE_STALE_FALLBACK",
                "observedAt": cached.get("observedAt"),
                "expiresAt": cached.get("expiresAt"),
                "error": error,
            }
        return None, {"source": source_id, "mode": "UNAVAILABLE", "error": error}


def classify_entity(general: dict[str, Any] | None) -> str:
    """Classify legal entity without treating every J-number as a company.

    Romanian chambers and other statutory bodies can carry historic registry
    numbers while not having shareholders/associates. Strong name/legal-form
    signals therefore take precedence over the registry-number shape.
    """
    if not general or not general.get("available"):
        return "UNKNOWN"
    entity = general.get("entity") or {}
    name = norm_text(entity.get("name"))
    legal = norm_text(entity.get("legalForm"))

    if "CAMERA DE COMERT SI INDUSTRIE" in name or "CAMERA DE COMERT" in name:
        return "CHAMBER_OF_COMMERCE"

    ngo_prefixes = ("FUNDATIA ", "ASOCIATIA ", "FEDERATIA ", "UNIUNEA ")
    if name.startswith(ngo_prefixes) or any(f" {prefix}" in name for prefix in ngo_prefixes):
        return "NGO"

    company_tokens = (" SRL", " S R L", " SA", " S A", " SNC", " SCS", " SCA")
    if any(token in name for token in company_tokens):
        return "COMMERCIAL"
    if any(token in legal for token in ("SOCIETATE", "REGIE", "COOPERATIVA")):
        return "COMMERCIAL"

    return "OTHER_LEGAL_ENTITY"


def find_indicator(statement: dict[str, Any], patterns: list[str]) -> dict[str, Any] | None:
    wanted = [norm_text(p) for p in patterns]
    for item in statement.get("indicators") or []:
        label = norm_text(item.get("label"))
        if any(p in label for p in wanted):
            return {"code": item.get("code"), "value": item.get("value"), "label": item.get("label")}
    return None


def indicator_number(item: dict[str, Any] | None) -> int | float | None:
    if not item:
        return None
    value = item.get("value")
    if isinstance(value, bool):
        return int(value)
    return value if isinstance(value, (int, float)) else None


def summarize_financials(series: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not series:
        return []
    rows: list[dict[str, Any]] = []
    for statement in series.get("statements") or []:
        year = statement.get("year")
        revenue = find_indicator(statement, ["Cifra de afaceri neta", "Venituri totale - la 31.12"])
        expenses = find_indicator(statement, ["Cheltuieli totale - la 31.12"])
        profit = find_indicator(statement, ["Profit net", "Excedent/Profit - la 31.12", "Excedent din activitatile fara scop patrimonial - la 31.12"])
        loss = find_indicator(statement, ["Pierdere neta", "Deficit/Pierdere - la 31.12", "Deficit din activitatile fara scop patrimonial - la 31.12"])

        employee_average = find_indicator(statement, ["Numar mediu de salariati"])
        employees_nonprofit = find_indicator(
            statement,
            ["Efectivul de personal privind activitatile fara scop patrimonial"],
        )
        employees_economic = find_indicator(
            statement,
            ["Efectivul de personal privind activitatile economice"],
        )
        personnel_values = [
            value
            for value in (
                indicator_number(employees_nonprofit),
                indicator_number(employees_economic),
            )
            if value is not None
        ]
        employees_total = sum(personnel_values) if personnel_values else None

        rows.append({
            "year": year,
            "revenueOrTurnover": revenue,
            "expenses": expenses,
            "profitOrSurplus": profit,
            "lossOrDeficit": loss,
            "employeeAverage": employee_average,
            "employeesNonProfit": employees_nonprofit,
            "employeesEconomic": employees_economic,
            "employeesTotal": {
                "value": employees_total,
                "derivedFrom": [
                    item.get("code")
                    for item in (employees_nonprofit, employees_economic)
                    if item is not None
                ],
            } if employees_total is not None else None,
        })
    return rows


def access_plan(entity_type: str, policy: dict[str, Any]) -> dict[str, Any]:
    sources = policy.get("sources") or {}
    plan: dict[str, Any] = {
        "core": ["ANAF_GENERAL", "ANAF_FINANCIALS"],
        "extendedPublic": ["JUSTICE_PORTAL", "ANAF_DEBTORS", "MYSMIS_BENEFICIAR", "ONRC_BPI"],
        "authorised": [],
        "notes": [],
    }
    if entity_type == "COMMERCIAL":
        plan["authorised"] = ["ONRC_RECOM", "ONRC_RBR"]
        plan["notes"].append("Asociatii/actionarii, procentele si administratorii trebuie alimentati din ONRC autorizat; RBR numai dupa aprobarea interesului legitim.")
    elif entity_type == "NGO":
        plan["extendedPublic"].append("MJ_NGO_REGISTER")
        plan["notes"].append("Registrul ONG public are set redus; conducerea curenta nu se inventeaza daca nu este publicata.")
    elif entity_type == "CHAMBER_OF_COMMERCE":
        plan["authorised"] = ["ONRC_RECOM"]
        plan["notes"].append("Camera de comert nu are model de actionariat/asociati de tip societate. ONRC poate completa reprezentarea si istoricul registral; conducerea trebuie reconciliata cu sursele statutare oficiale ale camerei.")
    plan["capabilities"] = {
        sid: {
            "access": cfg.get("access"),
            "authority": cfg.get("authority"),
            "fields": cfg.get("fields", []),
        }
        for sid, cfg in sources.items()
        if sid in set(plan["core"] + plan["extendedPublic"] + plan["authorised"])
    }
    return plan


def governance_stub(entity_type: str) -> dict[str, Any]:
    if entity_type == "COMMERCIAL":
        return {
            "shareholdersOrAssociates": None,
            "administratorsOrLegalRepresentatives": None,
            "beneficialOwners": None,
            "status": "AUTHORISED_SOURCE_REQUIRED",
        }
    if entity_type == "NGO":
        return {
            "foundersOrMembers": None,
            "governingBoardOrLegalRepresentatives": None,
            "beneficialOwners": None,
            "status": "PUBLIC_REDUCED_OR_REQUEST_REQUIRED",
        }
    if entity_type == "CHAMBER_OF_COMMERCE":
        return {
            "shareholdersOrAssociates": "NOT_APPLICABLE",
            "administratorsOrLegalRepresentatives": None,
            "beneficialOwners": "NOT_APPLICABLE_AS_SHAREHOLDER_MODEL",
            "status": "STATUTORY_SOURCE_REQUIRED",
        }
    return {
        "shareholdersOrAssociates": None,
        "administratorsOrLegalRepresentatives": None,
        "beneficialOwners": None,
        "status": "NOT_RESOLVED",
    }


def build_profile(
    cui_value: str | int,
    years: list[int],
    *,
    query_date: str,
    cache_dir: Path,
    cache_only: bool = False,
    force_refresh: bool = False,
) -> dict[str, Any]:
    cui = normalize_cui(cui_value)
    policy = load_policy()
    path = cache_file(cache_dir, cui)
    cache = read_cache(path)
    now = utcnow()
    statuses: list[dict[str, Any]] = []

    general, st = resolve_source(
        source_id="ANAF_GENERAL",
        fetcher=lambda: fetch_identity(cui, query_date),
        ttl_hours=int(policy["sources"]["ANAF_GENERAL"]["refreshHours"]),
        cache=cache,
        now=now,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    statuses.append(st)

    financials, st = resolve_source(
        source_id="ANAF_FINANCIALS",
        fetcher=lambda: fetch_series(cui, years, timeout=20, attempts=3, pace_seconds=0.6),
        ttl_hours=int(policy["sources"]["ANAF_FINANCIALS"]["refreshHours"]),
        cache=cache,
        now=now,
        cache_only=cache_only,
        force_refresh=force_refresh,
    )
    statuses.append(st)

    entity_type = classify_entity(general)
    live_count = sum(1 for item in statuses if item.get("mode") == "LIVE")
    stale_count = sum(1 for item in statuses if item.get("mode") in {"CACHE_STALE", "CACHE_STALE_FALLBACK"})
    unavailable = [item for item in statuses if item.get("mode") == "UNAVAILABLE"]

    if not cache_only and live_count:
        cache.update({
            "schemaVersion": "1.0",
            "cui": cui,
            "updatedAt": iso(now),
            "policy": "LAST_KNOWN_GOOD",
        })
        atomic_write(path, cache)

    entity = (general or {}).get("entity") or {}
    profile = {
        "schemaVersion": "1.1",
        "generatedAt": iso(now),
        "cui": cui,
        "status": "UNAVAILABLE" if len(unavailable) == 2 else ("STALE_CACHE" if stale_count and not live_count else ("PARTIAL" if unavailable else "OK")),
        "entityType": entity_type,
        "identity": entity,
        "addresses": {
            "registered": (general or {}).get("registeredAddress"),
            "fiscal": (general or {}).get("fiscalAddress"),
        },
        "fiscal": {
            "vat": (general or {}).get("vat"),
            "vatOnReceipt": (general or {}).get("vatOnReceipt"),
            "inactive": (general or {}).get("inactive"),
            "splitVat": (general or {}).get("splitVat"),
            "taxAuthority": entity.get("taxAuthority"),
            "eFactura": entity.get("eFactura"),
        },
        "financials": {
            "summary": summarize_financials(financials),
            "statementCount": (financials or {}).get("statementCount", 0),
            "statements": (financials or {}).get("statements", []),
            "errors": (financials or {}).get("errors", []),
        },
        "governance": governance_stub(entity_type),
        "accessPlan": access_plan(entity_type, policy),
        "sourceStatus": statuses,
        "fieldSources": {
            "identity": "ANAF_GENERAL",
            "addresses": "ANAF_GENERAL",
            "fiscal": "ANAF_GENERAL",
            "financials": "ANAF_FINANCIALS",
            "governance.commercial": "ONRC_RECOM",
            "governance.beneficialOwners": "ONRC_RBR",
            "governance.ngo": "MJ_NGO_REGISTER",
            "governance.chamber": "ONRC_RECOM_AND_STATUTORY_OFFICIAL_SOURCES",
        },
        "cache": {
            "path": str(path),
            "lastKnownGood": True,
            "cacheOnly": cache_only,
        },
        "privacy": {
            "collectCnp": False,
            "collectPrivateHomeAddressOfNaturalPersons": False,
        },
    }
    return profile


def main() -> int:
    p = argparse.ArgumentParser(description="Resolve persistent official profile after Romanian CUI")
    p.add_argument("--cui", required=True)
    p.add_argument("--years", help="comma-separated financial years; default last five completed years")
    p.add_argument("--date", default=dt.date.today().isoformat())
    p.add_argument("--cache-dir", default=str(DEFAULT_CACHE))
    p.add_argument("--cache-only", action="store_true")
    p.add_argument("--force-refresh", action="store_true")
    p.add_argument("--pretty", action="store_true")
    args = p.parse_args()
    try:
        result = build_profile(
            args.cui,
            parse_years(args.years),
            query_date=args.date,
            cache_dir=Path(args.cache_dir),
            cache_only=args.cache_only,
            force_refresh=args.force_refresh,
        )
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if result["status"] != "UNAVAILABLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
