#!/usr/bin/env python3
"""Create or update WordPress drafts for verified VÂLCEA CLAR venue profiles.

Safety invariant: this program has no publish mode. Every write uses status=draft.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "valcea-clar" / "web" / "unde-iesim.json"
ELIGIBLE = {"DRAFT_ELIGIBLE", "DRAFT_REVIEW_REQUIRED"}


def slugify(value: str) -> str:
    replacements = str.maketrans("ăâîșşțţĂÂÎȘŞȚŢ", "aaiss ttAAISSTT".replace(" ", ""))
    value = value.translate(replacements).lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:160]


def clean_base(value: str) -> str:
    return value.rstrip("/")


class WP:
    def __init__(self, base: str, user: str, password: str) -> None:
        self.base = clean_base(base)
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "ValceaClar-UndeIesim-Publisher/1.0",
        }

    def request(self, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
        url = f"{self.base}/wp-json/wp/v2/{path.lstrip('/')}"
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.loads(response.read().decode("utf-8"))

    def category(self, name: str, slug: str) -> int:
        found = self.request("GET", f"categories?slug={urllib.parse.quote(slug)}&context=edit")
        if found:
            return int(found[0]["id"])
        created = self.request("POST", "categories", {"name": name, "slug": slug})
        return int(created["id"])


def render_content(venue: dict[str, Any]) -> str:
    address = venue.get("address", {}).get("display", "de confirmat")
    contacts = venue.get("contacts", {})
    phones = ", ".join(contacts.get("phones") or []) or "de confirmat"
    hours = venue.get("hours", {}).get("weekly", "de confirmat")
    menu = venue.get("menu", {})
    highlights = "".join(f"<li>{html.escape(str(value))}</li>" for value in menu.get("highlights", []))
    price_rows = ""
    for price in menu.get("prices", []):
        label = html.escape(str(price.get("item", "")))
        if "amount" in price:
            amount = f'{price["amount"]} {price.get("currency", "")}'
        else:
            amount = f'{price.get("min", "?")}–{price.get("max", "?")} {price.get("currency", "")}'
        portion = f' · {html.escape(str(price["portion"]))}' if price.get("portion") else ""
        price_rows += f"<li><strong>{label}</strong>: {html.escape(amount)}{portion}</li>"

    operator = venue.get("operator", {})
    operator_name = operator.get("legalName") or operator.get("displayName") or "în curs de verificare"
    cui = f' · CUI {html.escape(str(operator["cui"]))}' if operator.get("cui") else ""
    website = contacts.get("website")
    website_html = (
        f'<p><strong>Site oficial:</strong> <a href="{html.escape(website)}">{html.escape(website)}</a></p>'
        if website else ""
    )
    warning = (
        "<p><em>Fișă editorială în curs de verificare. Programul, prețurile și "
        "disponibilitatea se pot modifica; verificați direct înainte de deplasare.</em></p>"
    )
    return f"""
<!-- wp:heading --><h2 class="wp-block-heading">Fișa localului</h2><!-- /wp:heading -->
<p><strong>Adresă:</strong> {html.escape(address)}</p>
<p><strong>Telefon:</strong> {html.escape(phones)}</p>
<p><strong>Program raportat:</strong> {html.escape(str(hours))}</p>
{website_html}
<!-- wp:heading --><h2 class="wp-block-heading">Ce se mănâncă</h2><!-- /wp:heading -->
<ul>{highlights or "<li>Meniul urmează să fie verificat.</li>"}</ul>
{f"<ul>{price_rows}</ul>" if price_rows else ""}
<!-- wp:heading --><h2 class="wp-block-heading">Cine operează localul</h2><!-- /wp:heading -->
<p>{html.escape(str(operator_name))}{cui}</p>
<p><strong>Statut verificare:</strong> {html.escape(str(operator.get("verification", "NEVERIFICAT")))}</p>
<!-- wp:heading --><h2 class="wp-block-heading">Transparență</h2><!-- /wp:heading -->
<p>Sursele și legăturile publice sunt publicate numai după verificarea relevanței. Nu formulăm asocieri prin presupunere.</p>
{warning}
""".strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="perform writes; otherwise print the plan")
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()

    dataset = json.loads(DATA.read_text(encoding="utf-8"))
    candidates = [item for item in dataset["venues"] if item.get("editorialEligibility") in ELIGIBLE][: args.limit]
    plan = [{"id": item["id"], "name": item["name"], "status": "draft"} for item in candidates]

    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "plannedDrafts": plan}, ensure_ascii=False, indent=2))
        return 0

    base = os.getenv("VALCEA_WP_BASE", "").strip()
    user = os.getenv("VALCEA_WP_USER", "").strip()
    password = os.getenv("VALCEA_WP_APP_PASSWORD", "").strip()
    if not (base and user and password):
        print(json.dumps({"status": "SKIPPED_MISSING_WORDPRESS_SECRETS", "planned": len(plan)}, indent=2))
        return 0

    wp = WP(base, user, password)
    category_id = wp.category("Unde ieșim", "unde-iesim")
    results = []
    for venue in candidates:
        slug = f"unde-iesim-{slugify(venue['name'])}"
        existing = wp.request("GET", f"posts?slug={urllib.parse.quote(slug)}&context=edit&status=any")
        title_prefix = "S-a deschis" if venue.get("editorialAngle") == "NOU_DESCHIS" else "Unde ieșim"
        payload = {
            "title": f"{title_prefix}: {venue['name']}",
            "slug": slug,
            "status": "draft",
            "categories": [category_id],
            "content": render_content(venue),
            "excerpt": (
                f"Fișă verificabilă pentru {venue['name']}: adresă, program, meniu, "
                "operator și surse publice."
            ),
        }
        if existing:
            post_id = int(existing[0]["id"])
            response = wp.request("POST", f"posts/{post_id}", payload)
            action = "updated"
        else:
            response = wp.request("POST", "posts", payload)
            post_id = int(response["id"])
            action = "created"
        results.append({"venueId": venue["id"], "postId": post_id, "action": action, "status": "draft"})

    print(json.dumps({"status": "DRAFTS_UPSERTED", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
