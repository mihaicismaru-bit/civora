from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.adapters.wordpress_feed import WordPressFeedDiscoverer
from clar_core.pipeline import Pipeline
from clar_core.publishers.static_site import StaticSitePublisher
from clar_core.verticals.utility import UtilityStoryComposer, WaterUtilityExtractor


HERE = Path(__file__).resolve().parent


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    instance = load_json(HERE / "config" / "instance.json")
    source_pack = load_json(HERE / "config" / "source_pack.json")
    source = next(s for s in source_pack["sources"] if s.get("enabled") and s.get("vertical") == "UTILITY")

    discover = WordPressFeedDiscoverer(
        source_id=source["id"],
        feed_url=source["feed_url"],
        max_items=int(source.get("max_items", 12)),
    )
    extract = WaterUtilityExtractor(
        allowed_localities=source.get("allowed_localities", []),
        area_prefixes=source.get("area_prefixes", []),
    )
    compose = UtilityStoryComposer(product_name=instance["product_name"], source_name=source["name"])
    base_url = os.environ.get("CRAIOVA_CLAR_BASE_URL") or instance.get("domain")
    publish = StaticSitePublisher(root=HERE / "site", product_name=instance["product_name"], base_url=base_url)

    state_path = HERE / "state" / "utility_seen.json"
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
