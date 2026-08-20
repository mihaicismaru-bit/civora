#!/usr/bin/env python3
"""Hardened entrypoint for direct official decision-maker Source Intelligence.

The stable collector implementation lives in people_policy_official_ingest_core.py.
This entrypoint narrows article evidence to semantic main/article content when
available and otherwise excludes structural navigation boilerplate before the
collector can bind actor, speech and funding evidence.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

_CORE_PATH = Path(__file__).with_name("people_policy_official_ingest_core.py")
_CORE_NAME = "_partener_people_policy_official_ingest_core"
_spec = importlib.util.spec_from_file_location(_CORE_NAME, _CORE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Cannot load Source Intelligence core from {_CORE_PATH}")
_core = importlib.util.module_from_spec(_spec)
sys.modules[_CORE_NAME] = _core
_spec.loader.exec_module(_core)

# Preserve the collector's public contract for existing workflows/tests/importers.
for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

HARD_SKIP_TAGS = {"script", "style", "svg", "noscript", "template"}
STRUCTURAL_BOILERPLATE_TAGS = {"header", "nav", "footer", "aside", "form"}
STRUCTURAL_BOILERPLATE_ROLES = {"navigation", "banner", "contentinfo", "complementary"}
SEMANTIC_CONTENT_TAGS = {"main", "article"}
SEMANTIC_CONTENT_ROLES = {"main", "article"}
MIN_SEMANTIC_CHARS = 80
MIN_SEMANTIC_WORDS = 10


class TextParser(HTMLParser):
    """Extract evidence text without letting site chrome become funding evidence.

    A sufficiently substantive <main>/<article> scope is preferred. If a source
    does not expose semantic content tags, the fallback body still excludes
    header/nav/footer/aside/form and equivalent ARIA structural roles. Title is
    retained separately for discovery/headline only, matching the collector's
    existing contract.
    """

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.semantic_parts: list[str] = []
        self.extraction_mode = "UNFINALIZED"
        self._body_parts: list[str] = []
        self._frames: list[tuple[str, bool, bool, bool, bool]] = []
        self._hard_skip_depth = 0
        self._boilerplate_depth = 0
        self._semantic_depth = 0
        self._title_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attr = {str(k).lower(): str(v or "").lower() for k, v in attrs}
        role = attr.get("role", "")
        hard = t in HARD_SKIP_TAGS
        boilerplate = t in STRUCTURAL_BOILERPLATE_TAGS or role in STRUCTURAL_BOILERPLATE_ROLES
        semantic = t in SEMANTIC_CONTENT_TAGS or role in SEMANTIC_CONTENT_ROLES
        title = t == "title"
        self._frames.append((t, hard, boilerplate, semantic, title))
        self._hard_skip_depth += int(hard)
        self._boilerplate_depth += int(boilerplate)
        self._semantic_depth += int(semantic)
        self._title_depth += int(title)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        match = None
        for index in range(len(self._frames) - 1, -1, -1):
            if self._frames[index][0] == t:
                match = index
                break
        if match is None:
            return
        closing = self._frames[match:]
        del self._frames[match:]
        for _, hard, boilerplate, semantic, title in reversed(closing):
            self._hard_skip_depth = max(0, self._hard_skip_depth - int(hard))
            self._boilerplate_depth = max(0, self._boilerplate_depth - int(boilerplate))
            self._semantic_depth = max(0, self._semantic_depth - int(semantic))
            self._title_depth = max(0, self._title_depth - int(title))

    def handle_data(self, data: str) -> None:
        if self._hard_skip_depth:
            return
        value = _core.clean(data)
        if not value:
            return
        if self._title_depth:
            self.title_parts.append(value)
            return
        if self._boilerplate_depth:
            return
        self._body_parts.append(value)
        if self._semantic_depth:
            self.semantic_parts.append(value)

    def feed(self, data: str) -> None:
        super().feed(data)
        semantic = _core.clean(" ".join(self.semantic_parts))
        fallback = _core.clean(" ".join(self._body_parts))
        if len(semantic) >= MIN_SEMANTIC_CHARS and len(semantic.split()) >= MIN_SEMANTIC_WORDS:
            self.parts = [semantic]
            self.extraction_mode = "SEMANTIC_MAIN_OR_ARTICLE"
        else:
            self.parts = [fallback] if fallback else []
            self.extraction_mode = "BODY_EXCLUDING_STRUCTURAL_BOILERPLATE"


# Core ingest_source resolves TextParser from its own module globals at runtime.
# Patching that global preserves all existing source-health/provenance logic while
# making scoped text the only evidence available to actor/speech/funding binding.
_core.TextParser = TextParser


def main() -> int:
    rc = _core.main()
    if rc != 0:
        return rc
    payload = _core.load(_core.STATE, {})
    if isinstance(payload, dict):
        policy = payload.setdefault("policy", {})
        if isinstance(policy, dict):
            policy.update({
                "articleEvidenceExcludesStructuralBoilerplate": True,
                "articleEvidencePrefersSemanticMainOrArticle": True,
                "articleEvidenceFallbackExcludesAriaNavigation": True,
            })
        _core.STATE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
