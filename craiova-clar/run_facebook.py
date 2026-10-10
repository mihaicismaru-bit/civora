from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from clar_core.contracts import PublicationReceipt, Story
from clar_core.social.facebook import FacebookPagePublisher, FacebookPublishError


HERE = Path(__file__).resolve().parent
CONFIG = HERE / "config" / "social_channels.json"
STORIES = HERE / "site" / "stories.json"
SITE_RECEIPT = HERE / "site" / "utility_publication_receipt.json"
STATE = HERE / "state" / "facebook.json"


def load(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save(value: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _persist_block_once(state: dict, block: dict) -> None:
    previous = state.get("last_attempt") if isinstance(state.get("last_attempt"), dict) else {}
    comparable = {key: value for key, value in block.items() if key != "at"}
    previous_comparable = {key: value for key, value in previous.items() if key != "at"}
    if comparable == previous_comparable:
        return
    state["last_attempt"] = block
    save(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform the external Facebook write")
    parser.add_argument(
        "--site-receipt",
        default=str(SITE_RECEIPT),
        help="verified site PublicationReceipt JSON to use; defaults to the utility receipt",
    )
    args = parser.parse_args()

    config = load(CONFIG)["channels"]["facebook"]
    if not config.get("enabled"):
        print(json.dumps({"status": "DISABLED"}))
        return 0

    site = load(Path(args.site_receipt))
    if site.get("status") != config.get("requires_site_status", "published_verified"):
        print(json.dumps({"status": "BLOCKED_SITE_NOT_VERIFIED", "site_status": site.get("status")}))
        return 0

    stories = load(STORIES).get("stories", [])
    row = next((item for item in stories if item.get("story_id") == site.get("story_id")), None)
    if not isinstance(row, dict):
        raise RuntimeError("verified site receipt does not match a story manifest row")
    media = row.get("media") if isinstance(row.get("media"), dict) else None
    if not media or media.get("rights_status") != config.get("requires_media_rights_status", "VERIFIED_REUSABLE"):
        print(json.dumps({"status": "BLOCKED_MEDIA_NOT_VERIFIED", "story_id": row.get("story_id")}))
        return 0

    story = Story(
        story_id=str(row["story_id"]),
        slug=str(row["slug"]),
        section=str(row.get("section") or ""),
        headline=str(row["headline"]),
        dek=str(row.get("dek") or ""),
        paragraphs=(),
        source_urls=(),
        published_at=parse_dt(row["published_at"]),
        media_query=None,
        metadata={"media": media},
    )
    site_receipt = PublicationReceipt(
        story_id=str(site["story_id"]),
        canonical_url=str(site["canonical_url"]),
        published_at=parse_dt(site["published_at"]),
        destination=str(site.get("destination") or "public_web"),
        status=str(site["status"]),
        external_id=site.get("external_id"),
        metadata=site.get("metadata") or {},
    )

    state = load(STATE, {"schema_version": 1, "published": {}, "last_attempt": None})
    published = state.setdefault("published", {})
    current = published.get(story.story_id) if isinstance(published, dict) else None
    if isinstance(current, dict) and current.get("status") == "published_verified":
        print(json.dumps({
            "status": "NO_ELIGIBLE_POSTS",
            "story_id": story.story_id,
            "reason": "already_published_verified",
            "facebook_post_id": current.get("external_id"),
        }, ensure_ascii=False))
        return 0

    max_age_hours = config.get("max_story_age_hours")
    if max_age_hours is not None:
        age_hours = (datetime.now(timezone.utc) - story.published_at.astimezone(timezone.utc)).total_seconds() / 3600
        if age_hours > float(max_age_hours):
            print(json.dumps({
                "status": "BLOCKED_STALE_STORY",
                "story_id": story.story_id,
                "age_hours": round(age_hours, 2),
                "max_story_age_hours": float(max_age_hours),
                "external_write": False,
            }, ensure_ascii=False))
            return 0

    if not args.apply:
        print(json.dumps({
            "status": "DRY_RUN",
            "eligible": [{
                "story_id": story.story_id,
                "headline": story.headline,
                "canonical_url": site_receipt.canonical_url,
                "media_asset_id": media.get("asset_id"),
            }],
            "already_submitted_external_id": current.get("external_id") if isinstance(current, dict) else None,
        }, ensure_ascii=False, indent=2))
        return 0

    page_id = os.getenv(str(config["page_id_env"]), "").strip()
    token = os.getenv(str(config["access_token_env"]), "").strip()
    version = os.getenv(str(config["graph_version_env"]), str(config.get("graph_version_default") or "")).strip()
    if not page_id or not token or not version:
        missing = [
            name for name, value in (
                (str(config["page_id_env"]), page_id),
                (str(config["access_token_env"]), token),
                (str(config["graph_version_env"]), version),
            ) if not value
        ]
        block = {
            "at": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED_MISSING_CREDENTIALS",
            "story_id": story.story_id,
            "missing": missing,
            "queue_preserved": True,
        }
        _persist_block_once(state, block)
        print(json.dumps({
            "status": "BLOCKED_MISSING_CREDENTIALS",
            "story_id": story.story_id,
            "required_runtime_values": [config["page_id_env"], config["access_token_env"]],
            "queue_preserved": True,
        }, ensure_ascii=False))
        return 0

    publisher = FacebookPagePublisher(page_id=page_id, access_token=token, graph_version=version)
    try:
        if isinstance(current, dict) and current.get("external_id") and current.get("status") == "submitted_unverified":
            receipt = publisher.verify_existing(
                story_id=story.story_id,
                canonical_url=site_receipt.canonical_url,
                external_id=str(current["external_id"]),
            )
        else:
            receipt = publisher(story, site_receipt)
    except FacebookPublishError as exc:
        block = {
            "at": datetime.now(timezone.utc).isoformat(),
            "status": "BLOCKED_META_OR_TRANSPORT",
            "story_id": story.story_id,
            "error": str(exc),
            "queue_preserved": True,
        }
        _persist_block_once(state, block)
        print(json.dumps(block, ensure_ascii=False))
        return 0

    record = {
        "status": receipt.status,
        "external_id": receipt.external_id,
        "canonical_url": receipt.canonical_url,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "metadata": dict(receipt.metadata),
    }
    published[story.story_id] = record
    state["last_attempt"] = {"at": record["updated_at"], "story_id": story.story_id, **record}
    save(state)
    print(json.dumps({"status": receipt.status, "story_id": story.story_id, "external_id": receipt.external_id}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
