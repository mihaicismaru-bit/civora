#!/usr/bin/env python3
"""Remote HTTP acceptance probe for the public VÂLCEA CLAR presentation layer.

CIVORA owns the newsroom. This probe only checks whether the external public host
actually serves the canonical outputs. Scheduled runs report status without mutating
editorial state. Use --require-ready when a deployment is expected to be production-ready.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://valceaclar.ro"
USER_AGENT = "VALCEA-CLAR-Public-Health/1.0 (+https://valceaclar.ro/)"


def fetch(url: str, timeout: int = 20) -> tuple[int | None, str, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000).decode("utf-8", errors="replace")
            return int(response.status), body, None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), body, f"HTTP {exc.code}"
    except Exception as exc:  # network/DNS/TLS are health evidence, not program crashes
        return None, "", f"{type(exc).__name__}: {exc}"


def canonical_present(html: str, canonical: str) -> bool:
    patterns = (
        f'href="{canonical}"',
        f"href='{canonical}'",
        f'content="{canonical}"',
        f"content='{canonical}'",
    )
    return any(value in html for value in patterns)


def first_story_contract() -> tuple[str | None, str | None]:
    manifest_path = ROOT / "site" / "runtime" / "stiri" / "manifest.json"
    if not manifest_path.is_file():
        return None, None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    stories = manifest.get("stories") or []
    for row in stories:
        path = str(row.get("path") or "")
        canonical = str(row.get("canonical") or "")
        if path.startswith("/stiri/") and path.endswith("/") and canonical.startswith("https://valceaclar.ro/stiri/"):
            return path, canonical
    return None, None


def evaluate(base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    checks: list[dict[str, Any]] = []

    def check(path: str, required: list[str], canonical: str | None = None, forbidden: list[str] | None = None) -> None:
        url = base + path
        status, body, error = fetch(url)
        missing = [marker for marker in required if marker not in body]
        forbidden_found = [marker for marker in (forbidden or []) if marker in body]
        canonical_ok = True if canonical is None else canonical_present(body, canonical)
        ok = status == 200 and not missing and not forbidden_found and canonical_ok
        checks.append({
            "path": path,
            "url": url,
            "http_status": status,
            "ok": ok,
            "missing_markers": missing,
            "forbidden_markers": forbidden_found,
            "canonical_ok": canonical_ok,
            "error": error,
        })

    check("/", ["VÂLCEA CLAR"])
    check("/robots.txt", ["Sitemap:", "valceaclar.ro/sitemap.xml"])
    check("/sitemap.xml", ["<urlset", "valceaclar.ro"])
    check(
        "/termeni/",
        ["Termeni și condiții", "redactie@valceaclar.ro", 'name="robots" content="index,follow"'],
        canonical="https://valceaclar.ro/termeni/",
        forbidden=["noindex"],
    )
    check(
        "/confidentialitate/",
        ["Politica de confidențialitate", "redactie@valceaclar.ro", 'name="robots" content="index,follow"'],
        canonical="https://valceaclar.ro/confidentialitate/",
        forbidden=["noindex"],
    )
    check("/unde-iesim/", ["Unde ieșim"])

    story_path, story_canonical = first_story_contract()
    if story_path and story_canonical:
        check(story_path, ["VÂLCEA CLAR"], canonical=story_canonical)
    else:
        checks.append({
            "path": "/stiri/<story-id>/",
            "url": None,
            "http_status": None,
            "ok": False,
            "missing_markers": ["canonical_story_manifest_entry"],
            "forbidden_markers": [],
            "canonical_ok": False,
            "error": "No canonical story route available in repository manifest",
        })

    blockers = [item["path"] for item in checks if not item["ok"]]
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR public HTTP acceptance",
        "base_url": base,
        "status": "READY" if not blockers else "BLOCKED",
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "publication_model": "continuous_story_first",
        "repository_is_not_publication_proof": True,
    }


def self_test() -> None:
    assert canonical_present('<link rel="canonical" href="https://valceaclar.ro/termeni/">', "https://valceaclar.ro/termeni/")
    assert not canonical_present('<link rel="canonical" href="https://example.com/">', "https://valceaclar.ro/termeni/")
    story_path, story_canonical = first_story_contract()
    assert (story_path is None and story_canonical is None) or (
        story_path.startswith("/stiri/") and story_canonical.startswith("https://valceaclar.ro/stiri/")
    )
    print("VÂLCEA CLAR public-site probe self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--output", default="/tmp/valcea-clar-public-health.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    result = evaluate(args.base_url)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_ready and not result["ready"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
