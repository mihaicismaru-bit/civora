#!/usr/bin/env python3
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
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def edition_photo_template(outbox: dict) -> dict:
    for item in reversed(outbox.get("items", [])):
        if str(item.get("id", "")).startswith("editia-de-") and item.get("image_path") and isinstance(item.get("image"), dict):
            return {"image_path": item["image_path"], "image": item["image"]}
    raise RuntimeError("No approved real-photo template found for edition summaries")


def main() -> int:
    current = load(CURRENT)
    if current.get("status") != "auto_approved" or current.get("publication_intent") != "publish":
        print(json.dumps({"generated": False, "reason": "current edition is not publishable"}, ensure_ascii=False))
        return 0

    edition_path = VC / str(current["json_source"])
    edition = load(edition_path)
    if edition.get("status") != "auto_approved" or edition.get("publication_intent") != "publish":
        print(json.dumps({"generated": False, "reason": "edition payload is not publishable"}, ensure_ascii=False))
        return 0

    outbox = load(OUTBOX)
    slot = str(edition.get("slot", "morning"))
    date_compact = str(edition.get("edition_date", "")).replace("-", "")
    item_id = f"editia-de-{SLOT_ID.get(slot, slot)}-{date_compact}"
    existing = {str(x.get("id")) for x in outbox.get("items", [])}
    if item_id in existing:
        print(json.dumps({"generated": False, "reason": "already present", "id": item_id}, ensure_ascii=False))
        return 0

    selected = []
    for item in edition.get("items", []):
        if item.get("section") in {"NOTA_REDACTIEI", "UNDE_IEȘIM"}:
            continue
        gate = str(item.get("material_fact_gate", ""))
        if gate not in {"PASS", "PASS_EXPLAINER_ONLY", "PASS_DATE_ONLY"}:
            continue
        selected.append(item)
        if len(selected) == 4:
            break

    if not selected:
        print(json.dumps({"generated": False, "reason": "no Facebook-safe stories"}, ensure_ascii=False))
        return 0

    lines = [f"EDIȚIA DE {SLOT_LABEL.get(slot, slot.upper())} — VÂLCEA CLAR", "", "Ce contează azi în Vâlcea:", ""]
    for item in selected:
        headline = str(item.get("headline", "")).strip()
        dek = str(item.get("dek", "")).strip()
        text = headline if not dek else f"{headline}. {dek}"
        lines.append(f"• {text}")
        lines.append("")
    lines.extend([
        "VÂLCEA CLAR separă semnalul de fapt și informația utilă de zgomot. Urmărim ce se schimbă pe parcursul zilei și corectăm transparent dacă apar informații noi.",
        "",
        "#ValceaClar #RamnicuValcea #Valcea #EditiaDeAzi #StiriValcea",
    ])

    photo = edition_photo_template(outbox)
    new_item = {
        "id": item_id,
        "status": "ready",
        "message": "\n".join(lines),
        "link": "https://valceaclar.ro/",
        "image_path": photo["image_path"],
        "image": photo["image"],
        "replace_post_ids": [],
        "source_edition_id": edition.get("edition_id"),
        "source_edition_updated_local": edition.get("updated_local"),
        "generation_mode": "deterministic_current_edition_summary_v1"
    }
    outbox.setdefault("items", []).append(new_item)
    write(OUTBOX, outbox)
    print(json.dumps({"generated": True, "id": item_id, "stories": [x.get("id") for x in selected]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
