from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.adapters.official_listing import OfficialListingDiscoverer
from clar_core.media import MediaPackResolver
from clar_core.pipeline import Pipeline
from clar_core.publishers.static_site import StaticSitePublisher
from clar_core.verticals.public_safety import PublicSafetyExtractor, PublicSafetyStoryComposer


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    instance = load_json(HERE / "config" / "instance.json")
    source_pack = load_json(HERE / "config" / "source_pack.json")
    media_pack_path = HERE / "config" / "media_pack.json"
    media_pack = load_json(media_pack_path) if media_pack_path.exists() else {"assets": []}
    source = next(s for s in source_pack["sources"] if s.get("enabled") and s.get("vertical") == "PUBLIC_SAFETY")

    discover = OfficialListingDiscoverer(
        source_id=source["id"],
        listing_url=source.get("listing_url") or source["url"],
        link_prefixes=source.get("link_prefixes") or (),
        max_items=int(source.get("max_items", 10)),
        max_age_hours=int(source["max_age_hours"]) if source.get("max_age_hours") is not None else None,
    )
    editorial_scope = instance.get("editorial_scope") or {}
    scope_terms = tuple(editorial_scope.get("primary") or ()) + tuple(editorial_scope.get("secondary") or ())
    extract = PublicSafetyExtractor(scope_terms=scope_terms)
    base_compose = PublicSafetyStoryComposer(product_name=instance["product_name"], source_name=source["name"])
    media = MediaPackResolver(media_pack.get("assets") or (), context_terms=scope_terms)

    def compose(packet):
        story = base_compose(packet)
        return media(story) if story is not None else None

    base_url = instance.get("domain") or os.environ.get("CRAIOVA_CLAR_BASE_URL")
    publish = StaticSitePublisher(root=HERE / "site", product_name=instance["product_name"], base_url=base_url)

    state_path = HERE / "state" / "public_safety_seen.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        seen_urls = set(load_json(state_path).get("urls", []))
    except FileNotFoundError:
        seen_urls = set()

    def seen(item):
        return item.canonical_url in seen_urls

    def mark_seen(item):
        seen_urls.add(item.canonical_url)
        state_path.write_text(json.dumps({"urls": sorted(seen_urls)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    result = Pipeline(discover, extract, compose, publish, seen=seen, mark_seen=mark_seen).run_once()
    print(json.dumps(result.__dict__, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
