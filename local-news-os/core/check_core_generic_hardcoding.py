#!/usr/bin/env python3
"""Fail closed when production-instance identity leaks into CORE_GENERIC source.

The forbidden vocabulary is derived from production instance configuration so
the guard itself contains no publication-specific names. Test fixtures are
ignored structurally; fixture/migration/compatibility file exceptions must be
explicit repository-relative paths.
"""
from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE_ROOT = ROOT / "local-news-os" / "core"
INSTANCES_ROOT = ROOT / "local-news-os" / "instances"

# PRS-074 permits explicit exceptions only for fixtures, migrations and
# compatibility adapters. These two files are the bounded legacy-crawler
# compatibility bridge and remain migration targets under PRS-065/066.
ALLOWLIST: dict[str, str] = {
    "local-news-os/core/discover_primary_source_facts.py": "TEMPORARY_COMPATIBILITY_ADAPTER",
    "local-news-os/core/discover_primary_source_facts_fast.py": "TEMPORARY_COMPATIBILITY_ADAPTER",
}


def normalize(value: str) -> str:
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


def identity_strings(cfg: dict) -> list[str]:
    values: list[str] = []
    for key in ("instance_id", "canonical_domain"):
        value = cfg.get(key)
        if isinstance(value, str):
            values.append(value)

    brand = cfg.get("brand")
    if isinstance(brand, dict):
        for key in ("name", "short_name"):
            value = brand.get(key)
            if isinstance(value, str):
                values.append(value)

    geography = cfg.get("geography")
    if isinstance(geography, dict):
        values.extend(_geography_identity_values(geography))
    return values


def forbidden_tokens() -> tuple[str, ...]:
    tokens: set[str] = set()
    for path in sorted(INSTANCES_ROOT.glob("*/instance.json")):
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if cfg.get("environment") != "production":
            continue
        for raw in identity_strings(cfg):
            value = normalize(raw).strip()
            if len(value) >= 5:
                tokens.add(value)
            for part in re.findall(r"[a-z0-9.-]+", value):
                if len(part) >= 5:
                    tokens.add(part)
    tokens.difference_update({"romania", "romanian"})
    return tuple(sorted(tokens, key=lambda item: (-len(item), item)))


def _docstring_node_ids(tree: ast.AST) -> set[int]:
    result: set[int] = set()
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            result.add(id(first.value))
    return result


class IdentityLiteralVisitor(ast.NodeVisitor):
    def __init__(self, tokens: tuple[str, ...], docstrings: set[int]) -> None:
        self.tokens = tokens
        self.docstrings = docstrings
        self.hits: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == "self_test" or node.name.startswith("test_"):
            return
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == "self_test" or node.name.startswith("test_"):
            return
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if id(node) in self.docstrings or not isinstance(node.value, str):
            return
        value = normalize(node.value)
        self.hits.update(token for token in self.tokens if token in value)


def scan() -> list[str]:
    tokens = forbidden_tokens()
    errors: list[str] = []
    this_file = Path(__file__).resolve()
    for path in sorted(CORE_ROOT.rglob("*.py")):
        if path.resolve() == this_file:
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWLIST:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source, filename=rel)
        except SyntaxError as exc:
            errors.append(f"{rel}: cannot scan invalid Python: {exc}")
            continue
        visitor = IdentityLiteralVisitor(tokens, _docstring_node_ids(tree))
        visitor.visit(tree)
        if visitor.hits:
            hits = sorted(visitor.hits, key=lambda item: (-len(item), item))
            errors.append(f"{rel}: production identity in CORE_GENERIC executable literals: {', '.join(hits[:8])}")
    return errors


def self_test() -> None:
    tokens = forbidden_tokens()
    assert tokens, "at least one production identity token must be derived"
    sample = ast.parse("VALUE = 'synthetic-instance'\n\ndef self_test():\n    x = 'fixture-only'\n")
    visitor = IdentityLiteralVisitor(("synthetic-instance", "fixture-only"), _docstring_node_ids(sample))
    visitor.visit(sample)
    assert visitor.hits == {"synthetic-instance"}
    print("CORE_GENERIC_HARDCODING_GUARD_SELF_TEST_PASS")


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
    errors = scan()
    report = {
        "status": "PASS" if not errors else "FAIL",
        "core_root": CORE_ROOT.relative_to(ROOT).as_posix(),
        "production_identity_token_count": len(forbidden_tokens()),
        "allowlist": ALLOWLIST,
        "errors": errors,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
