#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EUCONS = HERE.parent
EXTERNAL_RESOURCE_RE = re.compile(r"\b(?:src|href|action)\s*=\s*[\"']\s*(?:https?:)?//", re.IGNORECASE)
CSS_EXTERNAL_RE = re.compile(r"(?:@import\s+(?:url\()?|url\()\s*[\"']?\s*(?:https?:)?//", re.IGNORECASE)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load module {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_research_isolation(target: Path, research: dict[str, Any]) -> None:
    if research.get("production_enabled") is not False:
        raise RuntimeError("AI4WORK_CANDIDATE_MUST_REMAIN_FAIL_CLOSED")
    if research.get("test_twin_evidence_eligible") is not False:
        raise RuntimeError("TEST_TWIN_MUST_REMAIN_NON_EVIDENCE")
    expected = {
        target / "cercetare" / "ai4work-step" / "index.html",
        target / "cercetare" / "ai4work-step" / "adulti" / "index.html",
        target / "cercetare" / "ai4work-step" / "angajatori" / "index.html",
    }
    actual = {Path(path) for path in research.get("pages", [])}
    if actual != expected:
        raise RuntimeError("AI4WORK_RESEARCH_ROUTE_SET_DRIFT")
    for page in sorted(expected):
        text = _read(page)
        if '<meta name="robots" content="noindex,nofollow">' not in text:
            raise RuntimeError(f"AI4WORK_RESEARCH_PAGE_INDEXABLE:{page}")
        if EXTERNAL_RESOURCE_RE.search(text):
            raise RuntimeError(f"AI4WORK_RESEARCH_EXTERNAL_SUBRESOURCE:{page}")
    sitemap = _read(target / "sitemap.xml")
    if "/cercetare/ai4work-step" in sitemap:
        raise RuntimeError("AI4WORK_RESEARCH_ROUTE_LEAKED_TO_SITEMAP")
    client = _read(target / "assets" / "ai4work-research.js")
    for forbidden in ("localStorage", "sessionStorage", "document.cookie", "utm_", "gtag(", "fbq("):
        if forbidden in client:
            raise RuntimeError(f"AI4WORK_CLIENT_TRACKING_DRIFT:{forbidden}")
    css_path = target / "assets" / "eucons.css"
    if not css_path.is_file():
        raise RuntimeError("AI4WORK_SHARED_STYLESHEET_MISSING")
    css = _read(css_path)
    if CSS_EXTERNAL_RE.search(css):
        raise RuntimeError("AI4WORK_RESEARCH_STYLESHEET_EXTERNAL_RESOURCE")
    adults = _read(target / "cercetare" / "ai4work-step" / "adulti" / "index.html")
    employers = _read(target / "cercetare" / "ai4work-step" / "angajatori" / "index.html")
    for page_text in (adults, employers):
        if 'data-collection-enabled="false"' not in page_text:
            raise RuntimeError("AI4WORK_CANDIDATE_UI_NOT_FAIL_CLOSED")
        if 'data-endpoint="https://api.eucons.ro/research/ai4work/v1/submit"' not in page_text:
            raise RuntimeError("AI4WORK_ENDPOINT_DRIFT")
        if "data-eucons-lead-form" in page_text:
            raise RuntimeError("AI4WORK_RESEARCH_PAGE_REUSED_COMMERCIAL_LEAD_FORM")


def build_candidate(target: Path) -> dict[str, Any]:
    production = load_module(
        "eucons_build_production_ready",
        HERE / "build_production_ready.py",
    )
    research_builder = load_module(
        "eucons_ai4work_build_research_pages",
        EUCONS / "research" / "ai4work-step" / "build_research_pages.py",
    )
    production_result = production.build_site(target)
    if production_result.get("production_deployed") is not False:
        raise RuntimeError("CANDIDATE_BUILDER_MUST_NOT_DEPLOY")
    research_result = research_builder.build(target)
    _assert_research_isolation(target, research_result)
    return {
        "status": "PASS_FAIL_CLOSED_CANDIDATE",
        "production": production_result,
        "research": research_result,
        "merge_authorized": False,
        "deploy_authorized": False,
        "real_collection_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_candidate(args.target), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
