#!/usr/bin/env python3
"""Dependency-free validator for LOCAL NEWS OS instance isolation.

This is intentionally stdlib-only so every instance can be validated in CI
without a paid service or third-party runtime dependency.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTANCES_ROOT = ROOT / "local-news-os" / "instances"
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
REQUIRED_TOP = {
    "schema_version", "instance_id", "environment", "brand",
    "canonical_domain", "locale", "timezone", "country", "geography",
    "edition_schedule", "packs", "modules", "runtime", "social_channels",
    "policies",
}
REQUIRED_POLICIES = {
    "zero_paid_dependency": True,
    "llm_required": False,
    "verified_facts_only": True,
    "last_known_good": True,
}
RUNTIME_KEYS = ("state_root", "output_root", "current_edition", "live_feed")
PACK_KEYS = ("source_pack", "brand_pack", "geography_pack")
GENERIC_IDENTITY_WORDS = {"romania", "romanian", "county", "judetul", "local", "news", "clar"}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: root must be object")
    return value


def normalize_identity(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _geography_identity_values(geography: dict) -> list[str]:
    """Return place identity values, never generic schema labels such as type."""
    values: list[str] = []
    for key in ("primary_name", "county"):
        value = geography.get(key)
        if isinstance(value, str):
            values.append(value)
    for key in ("settlements", "aliases"):
        value = geography.get(key)
        if isinstance(value, list):
            values.extend(item for item in value if isinstance(item, str))
    return values


def production_identity_tokens() -> tuple[str, ...]:
    """Derive contamination tokens from current production instance configs."""
    tokens: set[str] = set()
    for path in sorted(INSTANCES_ROOT.glob("*/instance.json")):
        try:
            cfg = load(path)
        except Exception:
            continue
        if cfg.get("environment") != "production":
            continue
        values: list[str] = []
        for key in ("instance_id", "canonical_domain"):
            value = cfg.get(key)
            if isinstance(value, str):
                values.append(value)
        brand = cfg.get("brand")
        if isinstance(brand, dict):
            values.extend(str(brand[key]) for key in ("name", "short_name") if isinstance(brand.get(key), str))
        geography = cfg.get("geography")
        if isinstance(geography, dict):
            values.extend(_geography_identity_values(geography))
        for raw in values:
            normalized = normalize_identity(raw).strip()
            if len(normalized) >= 5:
                tokens.add(normalized)
            for part in re.findall(r"[a-z0-9.-]+", normalized):
                if len(part) >= 5:
                    tokens.add(part)
    tokens.difference_update(GENERIC_IDENTITY_WORDS)
    return tuple(sorted(tokens))


def norm(path: str) -> str:
    return str(Path(path).as_posix()).rstrip("/")


def overlap(a: str, b: str) -> bool:
    a, b = norm(a), norm(b)
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def repo_file(raw: str) -> Path | None:
    """Resolve a repository-relative path and reject traversal/outside paths."""
    if not raw or Path(raw).is_absolute():
        return None
    candidate = (ROOT / raw).resolve()
    try:
        candidate.relative_to(ROOT.resolve())
    except ValueError:
        return None
    return candidate


def validate_packs(
    path: Path,
    cfg: dict,
    instance_id: str,
    environment: str,
    forbidden_tokens: tuple[str, ...],
) -> list[str]:
    """Require every local pack to be real, instance-owned and contamination-free."""
    errors: list[str] = []
    packs = cfg.get("packs")
    if not isinstance(packs, dict):
        return [f"{path}: packs must be object"]

    instance_root = path.parent.resolve()
    instance_config = path.resolve()

    for key in PACK_KEYS:
        raw = str(packs.get(key, "")).strip()
        target = repo_file(raw)
        if target is None:
            errors.append(f"{path}: packs.{key} must be a repository-relative path")
            continue
        if target == instance_config:
            errors.append(f"{path}: packs.{key} cannot self-reference instance.json")
            continue
        try:
            target.relative_to(instance_root)
        except ValueError:
            errors.append(
                f"{path}: packs.{key} must be owned by instance {instance_id!r}; got {raw}"
            )
            continue
        if not target.is_file():
            errors.append(f"{path}: packs.{key} does not exist: {raw}")
            continue
        try:
            payload = load(target)
        except Exception as exc:
            errors.append(f"{path}: packs.{key} is not a valid JSON object: {exc}")
            continue

        pack_instance = payload.get("instance_id")
        if pack_instance is not None and str(pack_instance) != instance_id:
            errors.append(
                f"{path}: packs.{key} instance_id {pack_instance!r} does not match {instance_id!r}"
            )

        if environment == "test":
            serialized = normalize_identity(json.dumps(payload, ensure_ascii=False))
            leaks = [token for token in forbidden_tokens if token in serialized]
            if leaks:
                errors.append(
                    f"{path}: production-instance contamination in test {key}: {', '.join(leaks[:8])}"
                )

    return errors


def validate_one(path: Path, cfg: dict, forbidden_tokens: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    missing = sorted(REQUIRED_TOP - set(cfg))
    if missing:
        errors.append(f"{path}: missing keys: {', '.join(missing)}")
        return errors

    instance_id = str(cfg.get("instance_id", ""))
    if not SLUG.fullmatch(instance_id):
        errors.append(f"{path}: invalid instance_id {instance_id!r}")
    if path.parent.name != instance_id:
        errors.append(f"{path}: directory must match instance_id {instance_id!r}")

    environment = str(cfg.get("environment", ""))
    if environment not in {"production", "staging", "test"}:
        errors.append(f"{path}: invalid environment {environment!r}")

    domain = str(cfg.get("canonical_domain", "")).strip().lower()
    if not domain or "://" in domain or "/" in domain:
        errors.append(f"{path}: canonical_domain must be a bare host")
    if environment == "production" and domain.endswith(".invalid"):
        errors.append(f"{path}: production cannot use .invalid domain")

    brand = cfg.get("brand")
    if not isinstance(brand, dict) or not all(str(brand.get(k, "")).strip() for k in ("name", "short_name", "slogan")):
        errors.append(f"{path}: brand requires name, short_name and slogan")

    geography = cfg.get("geography")
    if not isinstance(geography, dict) or not str(geography.get("primary_name", "")).strip():
        errors.append(f"{path}: geography.primary_name is required")

    errors.extend(validate_packs(path, cfg, instance_id, environment, forbidden_tokens))

    policies = cfg.get("policies")
    if not isinstance(policies, dict):
        errors.append(f"{path}: policies must be object")
    else:
        for key, expected in REQUIRED_POLICIES.items():
            if policies.get(key) is not expected:
                errors.append(f"{path}: policies.{key} must be {expected!r}")

    runtime = cfg.get("runtime")
    if not isinstance(runtime, dict):
        errors.append(f"{path}: runtime must be object")
    else:
        for key in RUNTIME_KEYS:
            if not str(runtime.get(key, "")).strip():
                errors.append(f"{path}: runtime.{key} is required")

    if environment == "test":
        identity = {
            "brand": cfg.get("brand"),
            "canonical_domain": cfg.get("canonical_domain"),
            "geography": cfg.get("geography"),
        }
        serialized = normalize_identity(json.dumps(identity, ensure_ascii=False))
        leaks = [token for token in forbidden_tokens if token in serialized]
        if leaks:
            errors.append(f"{path}: production-instance contamination in test identity: {', '.join(leaks[:8])}")

    return errors


def validate_all() -> tuple[list[dict], list[str]]:
    paths = sorted(INSTANCES_ROOT.glob("*/instance.json"))
    errors: list[str] = []
    configs: list[dict] = []
    forbidden_tokens = production_identity_tokens()
    if len(paths) < 2:
        errors.append("at least two instances are required to prove isolation")

    for path in paths:
        try:
            cfg = load(path)
        except Exception as exc:
            errors.append(f"{path}: cannot load: {exc}")
            continue
        configs.append(cfg)
        errors.extend(validate_one(path, cfg, forbidden_tokens))

    domains: dict[str, str] = {}
    for cfg in configs:
        domain = str(cfg.get("canonical_domain", "")).lower()
        iid = str(cfg.get("instance_id", ""))
        if domain in domains:
            errors.append(f"domain collision: {domain} used by {domains[domain]} and {iid}")
        domains[domain] = iid

    for i, left in enumerate(configs):
        for right in configs[i + 1:]:
            lid, rid = str(left.get("instance_id")), str(right.get("instance_id"))
            lr, rr = left.get("runtime", {}), right.get("runtime", {})
            if not isinstance(lr, dict) or not isinstance(rr, dict):
                continue
            for lk in ("state_root", "output_root"):
                for rk in ("state_root", "output_root"):
                    if overlap(str(lr.get(lk, "")), str(rr.get(rk, ""))):
                        errors.append(
                            f"runtime isolation failure: {lid}.{lk} overlaps {rid}.{rk}"
                        )

    return configs, errors


def main() -> int:
    configs, errors = validate_all()
    report = {
        "status": "PASS" if not errors else "FAIL",
        "instance_count": len(configs),
        "instances": [str(c.get("instance_id")) for c in configs],
        "zero_paid_dependency": all(
            isinstance(c.get("policies"), dict)
            and c["policies"].get("zero_paid_dependency") is True
            and c["policies"].get("llm_required") is False
            for c in configs
        ),
        "packs_resolved": all(
            isinstance(c.get("packs"), dict)
            and all(repo_file(str(c["packs"].get(k, ""))) and repo_file(str(c["packs"].get(k, ""))).is_file() for k in PACK_KEYS)
            for c in configs
        ),
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
