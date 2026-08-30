#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from build_research_pages import build

ALLOWED_RESEARCH_API = "https://api.eucons.ro/research/ai4work/v1/submit"
TRACKER_TOKENS = (
    "google-analytics",
    "googletagmanager",
    "gtag(",
    "facebook.com/tr",
    "connect.facebook.net",
    "fbq(",
    "matomo",
    "hotjar",
    "clarity.ms",
    "plausible",
    "hubspot",
    "segment.com",
    "mixpanel",
)
FORBIDDEN_BROWSER_STORAGE_TOKENS = (
    "document.cookie",
    "localstorage",
    "sessionstorage",
    "indexeddb",
)
NETWORK_ATTRS = {
    "script": ("src",),
    "img": ("src", "srcset"),
    "iframe": ("src",),
    "link": ("href",),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
}


class SurfaceScanner(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.external_asset_urls: list[str] = []
        self.form_endpoints: list[str] = []
        self.form_actions: list[str] = []
        self.meta_referrer: list[str] = []
        self.meta_robots: list[str] = []

    @staticmethod
    def _is_external(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} or value.startswith("//")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "").strip() for k, v in attrs}
        for attr_name in NETWORK_ATTRS.get(tag_l, ()):
            value = attr_map.get(attr_name, "")
            if not value:
                continue
            candidates = [value]
            if attr_name == "srcset":
                candidates = [part.strip().split()[0] for part in value.split(",") if part.strip()]
            for candidate in candidates:
                if self._is_external(candidate):
                    self.external_asset_urls.append(candidate)
        if tag_l == "form" and attr_map.get("action"):
            self.form_actions.append(attr_map["action"])
        if tag_l == "form" and attr_map.get("data-endpoint"):
            self.form_endpoints.append(attr_map["data-endpoint"])
        if tag_l == "meta":
            name = attr_map.get("name", "").lower()
            if name == "referrer":
                self.meta_referrer.append(attr_map.get("content", "").lower())
            elif name == "robots":
                self.meta_robots.append(attr_map.get("content", "").lower())


def validate_page(path: Path, *, expect_form: bool) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    scanner = SurfaceScanner()
    scanner.feed(text)

    tracker_hits = sorted({token for token in TRACKER_TOKENS if token in lower})
    if tracker_hits:
        raise RuntimeError(f"commercial/third-party tracker token present in {path}: {tracker_hits}")
    if "http://" in lower:
        raise RuntimeError(f"cleartext external URL present in research surface: {path}")
    if scanner.external_asset_urls:
        raise RuntimeError(
            f"external asset/network dependency present in {path}: {sorted(scanner.external_asset_urls)}"
        )
    if any(action and action not in {"#", "/"} for action in scanner.form_actions):
        raise RuntimeError(f"HTML form action may bypass the reviewed JSON client in {path}: {scanner.form_actions}")
    if scanner.meta_referrer != ["no-referrer"]:
        raise RuntimeError(f"research page must carry exactly one no-referrer meta policy: {path}")
    if scanner.meta_robots != ["noindex,nofollow"]:
        raise RuntimeError(f"research page must remain noindex,nofollow: {path}")

    if expect_form:
        if scanner.form_endpoints != [ALLOWED_RESEARCH_API]:
            raise RuntimeError(
                f"form network egress must be exactly the first-party research API: {path}: {scanner.form_endpoints}"
            )
    elif scanner.form_endpoints:
        raise RuntimeError(f"landing page must not declare a submission endpoint: {path}")

    return {
        "path": str(path),
        "external_assets": 0,
        "tracker_hits": [],
        "form_endpoint": scanner.form_endpoints[0] if scanner.form_endpoints else None,
        "referrer_policy": "no-referrer",
        "robots": "noindex,nofollow",
    }


def run_control() -> dict[str, object]:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp)
        build_result = build(target)
        pages = {
            "landing": target / "cercetare" / "ai4work-step" / "index.html",
            "adults": target / "cercetare" / "ai4work-step" / "adulti" / "index.html",
            "employers": target / "cercetare" / "ai4work-step" / "angajatori" / "index.html",
        }
        missing = [name for name, path in pages.items() if not path.is_file()]
        if missing:
            raise RuntimeError(f"research build missing required routes: {missing}")
        results = {
            name: validate_page(path, expect_form=name != "landing")
            for name, path in pages.items()
        }
        client = target / "assets" / "ai4work-research.js"
        if not client.is_file():
            raise RuntimeError("research client asset missing from built candidate")
        client_text = client.read_text(encoding="utf-8").lower()
        tracker_hits = sorted({token for token in TRACKER_TOKENS if token in client_text})
        if tracker_hits:
            raise RuntimeError(f"commercial/third-party tracker token present in client: {tracker_hits}")
        if "navigator.sendbeacon" in client_text:
            raise RuntimeError("background beacon transport is forbidden for AI4WORK research")
        browser_storage_hits = sorted(
            token for token in FORBIDDEN_BROWSER_STORAGE_TOKENS if token in client_text
        )
        if browser_storage_hits:
            raise RuntimeError(
                f"persistent/browser tracking storage is forbidden for AI4WORK research: {browser_storage_hits}"
            )
        if "globalthis.history.replacestate" not in client_text:
            raise RuntimeError("recruitment-channel URL fragment must be scrubbed after one-time capture")
        if "const channelid = () => recruitmentchannel;" not in client_text:
            raise RuntimeError("recruitment channel must be held only in ephemeral client memory")
        return {
            "status": "PASS",
            "classification": "CONTROL_ONLY_NOT_EVIDENCE",
            "research_id": "AI4WORK-STEP-NF-RUN-001",
            "production_enabled": bool(build_result.get("production_enabled")),
            "allowed_network_egress": [ALLOWED_RESEARCH_API],
            "pages": results,
            "client_tracker_hits": [],
            "browser_storage_hits": [],
            "recruitment_channel_fragment_scrubbed": True,
            "test_twin_evidence_eligible": False,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run_control()
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
