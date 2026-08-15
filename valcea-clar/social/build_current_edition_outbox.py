#!/usr/bin/env python3
"""Build channel-native social packages from the current verified edition."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
CURRENT = VC / "site" / "current_edition.json"
OUTBOX = VC / "social" / "facebook_outbox.json"

SLOT_LABEL = {"morning": "DIMINEAȚĂ", "evening": "SEARĂ"}
SLOT_ID = {"morning": "dimineata", "evening": "seara"}


def load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def edition_photo_template(outbox: dict) -> dict:
    for item in reversed(outbox.get("items", [])):
        if (
            str(item.get("id", "")).startswith("editia-de-")
            and item.get("image_path")
            and isinstance(item.get("image"), dict)
        ):
            return {"image_path": item["image_path"], "image": item["image"]}
    for item in reversed(outbox.get("items", [])):
        if item.get("image_path") and isinstance(item.get("image"), dict):
            return {"image_path": item["image_path"], "image": item["image"]}
    raise RuntimeError("No approved real-photo template found for edition summaries")


def select_stories(edition: dict) -> list[dict]:
    selected: list[dict] = []
    for item in edition.get("items", []):
        if item.get("section") in {"NOTA_REDACTIEI", "UNDE_IEȘIM"}:
            continue
        if str(item.get("material_fact_gate", "")) not in {
            "PASS",
            "PASS_EXPLAINER_ONLY",
            "PASS_DATE_ONLY",
        }:
            continue
        selected.append(item)
        if len(selected) == 4:
            break
    return selected


def facebook_copy(selected: list[dict], slot: str) -> str:
    lines = [
        f"EDIȚIA DE {SLOT_LABEL.get(slot, slot.upper())} — VÂLCEA CLAR",
        "",
        "Ce contează azi în Vâlcea:",
        "",
    ]
    for item in selected:
        headline = str(item.get("headline", "")).strip()
        dek = str(item.get("dek", "")).strip()
        text = headline if not dek else f"{headline}. {dek}"
        lines.extend([f"• {text}", ""])
    lines.extend(
        [
            (
                "VÂLCEA CLAR separă semnalul de fapt și informația utilă de "
                "zgomot. Urmărim ce se schimbă pe parcursul zilei și corectăm "
                "transparent dacă apar informații noi."
            ),
            "",
            "#ValceaClar #RamnicuValcea #Valcea #EditiaDeAzi #StiriValcea",
        ]
    )
    return "\n".join(lines)


def instagram_copy(selected: list[dict], slot: str) -> str:
    lines = [
        f"VÂLCEA, PE SCURT — EDIȚIA DE {SLOT_LABEL.get(slot, slot.upper())}",
        "",
    ]
    for index, item in enumerate(selected, start=1):
        headline = str(item.get("headline", "")).strip()
        dek = str(item.get("dek", "")).strip()
        lines.append(f"{index}. {headline}")
        if dek:
            lines.append(dek)
        lines.append("")
    lines.extend(
        [
            "Contextul, sursele și actualizările sunt pe valceaclar.ro.",
            "",
            "#ValceaClar #Valcea #RamnicuValcea #StiriLocale #EditiaDeAzi",
        ]
    )
    return "\n".join(lines)


def tiktok_copy(selected: list[dict], slot: str) -> tuple[str, str]:
    title = f"Vâlcea azi: {min(len(selected), 4)} lucruri de știut"
    lines = [f"Ediția de {SLOT_LABEL.get(slot, slot).lower()} VÂLCEA CLAR:"]
    for item in selected[:4]:
        headline = str(item.get("headline", "")).strip()
        if headline:
            lines.append(f"• {headline}")
    lines.extend(
        [
            "",
            "Detaliile și sursele sunt pe valceaclar.ro.",
            "#ValceaClar #Valcea #RamnicuValcea #StiriValcea",
        ]
    )
    return title, "\n".join(lines)


def default_tiktok_package(
    title: str, description: str, photo_url: str
) -> dict:
    return {
        "status": "hold",
        "mode": "direct_post",
        "reason": "site_consent_and_tiktok_app_audit_required",
        "title": title,
        "description": description,
        "photo_url": photo_url,
        "privacy_level": None,
        "disable_comment": False,
        "consent": {
            "granted": False,
            "source": None,
            "granted_at": None,
            "actor": None,
        },
    }


def enrich_platforms(
    item: dict,
    *,
    instagram_caption: str,
    tiktok_title: str,
    tiktok_description: str,
    tiktok_photo_url: str,
) -> None:
    platforms = item.setdefault("platforms", {})
    if not isinstance(platforms, dict):
        raise ValueError(f"invalid platforms object for {item.get('id')}")

    facebook = platforms.setdefault(
        "facebook", {"status": "ready", "mode": "direct_publish"}
    )
    if isinstance(facebook, dict):
        facebook.setdefault("status", "ready")
        facebook.setdefault("mode", "direct_publish")

    instagram = platforms.setdefault(
        "instagram",
        {
            "status": "ready",
            "mode": "direct_publish",
            "caption": instagram_caption,
        },
    )
    if isinstance(instagram, dict):
        instagram.setdefault("status", "ready")
        instagram.setdefault("mode", "direct_publish")
        instagram["caption"] = instagram_caption

    tiktok = platforms.setdefault(
        "tiktok",
        default_tiktok_package(
            tiktok_title, tiktok_description, tiktok_photo_url
        ),
    )
    if isinstance(tiktok, dict):
        tiktok.setdefault("mode", "direct_post")
        tiktok["title"] = tiktok_title
        tiktok["description"] = tiktok_description
        tiktok["photo_url"] = tiktok_photo_url
        tiktok.setdefault("disable_comment", False)
        tiktok.setdefault("privacy_level", None)
        tiktok.setdefault(
            "consent",
            {
                "granted": False,
                "source": None,
                "granted_at": None,
                "actor": None,
            },
        )
        if tiktok.get("status") != "ready":
            tiktok["status"] = "hold"
            tiktok["reason"] = "site_consent_and_tiktok_app_audit_required"


def main() -> int:
    current = load(CURRENT)
    if (
        current.get("status") != "auto_approved"
        or current.get("publication_intent") != "publish"
    ):
        print(
            json.dumps(
                {"generated": False, "reason": "current edition is not publishable"},
                ensure_ascii=False,
            )
        )
        return 0

    edition_path = VC / str(current["json_source"])
    edition = load(edition_path)
    if (
        edition.get("status") != "auto_approved"
        or edition.get("publication_intent") != "publish"
    ):
        print(
            json.dumps(
                {"generated": False, "reason": "edition payload is not publishable"},
                ensure_ascii=False,
            )
        )
        return 0

    outbox = load(OUTBOX)
    selected = select_stories(edition)
    if not selected:
        print(
            json.dumps(
                {"generated": False, "reason": "no social-safe stories"},
                ensure_ascii=False,
            )
        )
        return 0

    slot = str(edition.get("slot", "morning"))
    date_compact = str(edition.get("edition_date", "")).replace("-", "")
    item_id = f"editia-de-{SLOT_ID.get(slot, slot)}-{date_compact}"
    photo = edition_photo_template(outbox)
    filename = Path(str(photo["image_path"])).name
    tiktok_title, tiktok_description = tiktok_copy(selected, slot)
    tiktok_photo_url = f"https://valceaclar.ro/media/social/{filename}"
    instagram_caption = instagram_copy(selected, slot)

    existing = next(
        (
            item
            for item in outbox.get("items", [])
            if isinstance(item, dict) and str(item.get("id")) == item_id
        ),
        None,
    )
    action = "created"
    if existing is None:
        existing = {
            "id": item_id,
            "status": "ready",
            "message": facebook_copy(selected, slot),
            "link": "https://valceaclar.ro/",
            "image_path": photo["image_path"],
            "image": photo["image"],
            "replace_post_ids": [],
        }
        outbox.setdefault("items", []).append(existing)
    else:
        action = "enriched"
        existing.setdefault("status", "ready")
        existing.setdefault("link", "https://valceaclar.ro/")
        existing.setdefault("image_path", photo["image_path"])
        existing.setdefault("image", photo["image"])
        existing.setdefault("replace_post_ids", [])

    existing["message"] = facebook_copy(selected, slot)
    existing["source_edition_id"] = edition.get("edition_id")
    existing["source_edition_updated_local"] = edition.get("updated_local")
    existing["generation_mode"] = "deterministic_channel_native_social_v1"
    enrich_platforms(
        existing,
        instagram_caption=instagram_caption,
        tiktok_title=tiktok_title,
        tiktok_description=tiktok_description,
        tiktok_photo_url=tiktok_photo_url,
    )

    write(OUTBOX, outbox)
    print(
        json.dumps(
            {
                "generated": True,
                "action": action,
                "id": item_id,
                "platforms": {
                    "facebook": "ready",
                    "instagram": "ready",
                    "tiktok": existing["platforms"]["tiktok"].get("status"),
                },
                "stories": [item.get("id") for item in selected],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
