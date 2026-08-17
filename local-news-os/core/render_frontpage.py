#!/usr/bin/env python3
"""CORE_GENERIC static frontpage renderer for LOCAL NEWS OS.

The renderer knows no local brand, domain, geography or source. All publication
identity comes from the instance and its Brand Pack; all editorial content comes
from a publishable LOCAL_NEWS_OS_EDITION_V1 document. No paid service or LLM is
required.
"""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTANCES = ROOT / "local-news-os" / "instances"
PUBLISHABLE = {"auto_approved", "editor_approved"}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected JSON object")
    return value


def default_production_instance_id() -> str:
    candidates: list[str] = []
    for path in sorted(INSTANCES.glob("*/instance.json")):
        cfg = load_json(path)
        if cfg.get("environment") == "production" and cfg.get("instance_id"):
            candidates.append(str(cfg["instance_id"]))
    if len(candidates) != 1:
        raise ValueError(f"expected exactly one production instance, found {len(candidates)}")
    return candidates[0]


def repo_file(raw: str) -> Path:
    path = (ROOT / raw).resolve()
    path.relative_to(ROOT.resolve())
    return path


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def load_instance(instance_id: str) -> tuple[dict, dict]:
    cfg_path = INSTANCES / instance_id / "instance.json"
    cfg = load_json(cfg_path)
    if cfg.get("instance_id") != instance_id:
        raise ValueError(f"{cfg_path}: instance mismatch")
    brand_path = repo_file(str(cfg["packs"]["brand_pack"]))
    brand_pack = load_json(brand_path)
    pack_instance = brand_pack.get("instance_id")
    if pack_instance is not None and pack_instance != instance_id:
        raise ValueError(f"{brand_path}: Brand Pack belongs to {pack_instance!r}")
    return cfg, brand_pack


def publication_identity(cfg: dict, brand_pack: dict) -> dict:
    pack_brand = brand_pack.get("brand") if isinstance(brand_pack.get("brand"), dict) else {}
    cfg_brand = cfg.get("brand") if isinstance(cfg.get("brand"), dict) else {}
    name = str(pack_brand.get("name") or cfg_brand.get("name") or "LOCAL NEWS").strip()
    short_name = str(pack_brand.get("short_name") or cfg_brand.get("short_name") or name).strip()
    slogan = str(pack_brand.get("slogan") or cfg_brand.get("slogan") or "").strip()
    domain = str(pack_brand.get("canonical_domain") or pack_brand.get("brand", {}).get("canonical_domain") or cfg["canonical_domain"]).strip()
    visual_policy = brand_pack.get("visual_policy") if isinstance(brand_pack.get("visual_policy"), dict) else {}
    palette = visual_policy.get("palette") if isinstance(visual_policy.get("palette"), dict) else {}
    return {
        "name": name,
        "short_name": short_name,
        "slogan": slogan,
        "domain": domain,
        "primary": str(palette.get("primary") or "#111827"),
        "accent": str(palette.get("accent") or "#b42318"),
        "paper": str(palette.get("paper") or "#ffffff"),
        "real_photographs_only": visual_policy.get("real_photographs_only") is True,
    }


def validate_edition(instance_id: str, doc: dict) -> None:
    if doc.get("instance_id") != instance_id:
        raise ValueError("edition/instance mismatch")
    if doc.get("status") not in PUBLISHABLE or doc.get("publication_intent") != "publish":
        raise ValueError("renderer refuses non-publishable edition")
    if not isinstance(doc.get("items"), list) or not doc["items"]:
        raise ValueError("renderer requires at least one editorial item")


def source_links(item: dict) -> str:
    result: list[str] = []
    for source in item.get("sources", [])[:3]:
        if not isinstance(source, dict) or not source.get("url"):
            continue
        result.append(
            f'<a href="{esc(source["url"])}" rel="nofollow noopener">{esc(source.get("name") or "Sursă")}</a>'
        )
    return " · ".join(result)


def visual(item: dict, *, real_only: bool, hero: bool = False) -> str:
    data = item.get("visual") if isinstance(item.get("visual"), dict) else {}
    url = str(data.get("image_url") or "").strip()
    if not url:
        return ""
    if real_only and data.get("synthetic") is not False:
        return ""
    alt = esc(data.get("alt") or item.get("headline"))
    credit = esc(data.get("credit") or "")
    caption = f"<figcaption>{credit}</figcaption>" if credit else ""
    loading = "eager" if hero else "lazy"
    return f'<figure><img src="{esc(url)}" alt="{alt}" loading="{loading}">{caption}</figure>'


def story(item: dict, *, real_only: bool) -> str:
    return f'''<article class="card">
      {visual(item, real_only=real_only)}
      <div class="kicker">{esc(str(item.get("section") or "LOCAL").replace("_", " "))}</div>
      <h2>{esc(item.get("headline"))}</h2>
      <p>{esc(item.get("dek"))}</p>
      <div class="sources">{source_links(item)}</div>
    </article>'''


def render(instance_id: str, doc: dict) -> str:
    cfg, brand_pack = load_instance(instance_id)
    validate_edition(instance_id, doc)
    identity = publication_identity(cfg, brand_pack)
    items = doc["items"]
    lead, secondary = items[0], items[1:7]
    lead_paragraphs = "".join(f"<p>{esc(p)}</p>" for p in lead.get("paragraphs", [])[:2])
    cards = "".join(story(item, real_only=identity["real_photographs_only"]) for item in secondary)
    slot = "DIMINEAȚĂ" if doc.get("slot") == "morning" else "SEARĂ"
    description = str(lead.get("dek") or lead.get("headline") or identity["slogan"])
    canonical = f'https://{identity["domain"]}/'
    lang = str(cfg.get("locale") or "ro-RO").split("-")[0]

    return f'''<!doctype html>
<html lang="{esc(lang)}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(identity["name"])} — Ediția curentă</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:site_name" content="{esc(identity["name"])}">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(identity["name"])} — Ediția curentă">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="{esc(canonical)}">
<style>
:root{{--primary:{esc(identity["primary"])};--accent:{esc(identity["accent"])};--paper:{esc(identity["paper"])};--ink:#101828;--muted:#667085;--line:#e4e7ec}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Arial,sans-serif}}a{{color:inherit}}
header{{background:var(--primary);color:white}}.mast{{max-width:1180px;margin:auto;padding:22px 20px}}.brand{{font:800 clamp(30px,6vw,52px)/1 Georgia,serif;letter-spacing:.025em}}.brand span{{border-bottom:3px solid var(--accent);padding-bottom:6px}}.slogan{{margin-top:10px;opacity:.82}}
main{{max-width:1180px;margin:auto;padding:24px 20px 52px}}.bar{{display:flex;gap:12px;align-items:center;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:20px}}.badge{{background:var(--accent);color:white;padding:6px 10px;border-radius:4px;font-size:12px;font-weight:800}}.time{{color:var(--muted);font-size:13px}}
.hero{{max-width:920px}}.kicker{{color:var(--accent);font-size:12px;font-weight:900;letter-spacing:.06em;text-transform:uppercase}}h1{{font:800 clamp(36px,7vw,66px)/1.03 Georgia,serif;margin:8px 0 14px}}.dek{{font-size:20px;color:#344054;max-width:850px}}.copy{{font-size:18px;max-width:850px}}
figure{{margin:18px 0 12px}}figure img{{display:block;width:100%;max-height:520px;object-fit:cover;border-radius:10px}}figcaption{{font-size:12px;color:var(--muted);margin-top:6px}}.sources{{font-size:12px;color:var(--muted);margin-top:10px}}.sources a{{color:#475467}}
.section{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid var(--primary);padding-bottom:8px;margin:34px 0 16px}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px}}.card{{border-top:3px solid var(--primary);padding-top:12px}}.card h2{{font:700 24px/1.15 Georgia,serif;margin:7px 0 9px}}.card p{{color:#475467;margin:0}}
.note{{margin-top:34px;padding:14px 16px;background:#f8f9fb;border-left:4px solid var(--accent);font-size:13px;color:#475467}}footer{{background:var(--primary);color:#d0d5dd;padding:22px;text-align:center;font-size:13px}}
@media(max-width:820px){{.cards{{grid-template-columns:1fr}}h1{{font-size:42px}}}}
</style>
</head>
<body>
<header><div class="mast"><div class="brand"><span>{esc(identity["name"])}</span></div><div class="slogan">{esc(identity["slogan"])}</div></div></header>
<main>
<div class="bar"><span class="badge">EDIȚIA DE {slot}</span><span class="time">{esc(doc.get("updated_local"))}</span></div>
<article class="hero"><div class="kicker">{esc(lead.get("section"))}</div><h1>{esc(lead.get("headline"))}</h1><p class="dek">{esc(lead.get("dek"))}</p>{visual(lead, real_only=identity["real_photographs_only"], hero=True)}<div class="copy">{lead_paragraphs}</div><div class="sources">{source_links(lead)}</div></article>
<h2 class="section">Alte știri</h2><div class="cards">{cards}</div>
<div class="note">Această publicație afișează numai elementele furnizate de ediția verificată a motorului LOCAL NEWS OS. Golurile de dovezi nu sunt completate automat.</div>
</main>
<footer>{esc(identity["short_name"])} · {esc(identity["domain"])} · LOCAL NEWS OS</footer>
</body></html>'''


def fixture_edition(instance_id: str, brand_hint: str) -> dict:
    return {
        "contract": "LOCAL_NEWS_OS_EDITION_V1",
        "instance_id": instance_id,
        "edition_id": "2026-08-15-morning",
        "slot": "morning",
        "status": "auto_approved",
        "publication_intent": "publish",
        "updated_local": "2026-08-15T08:00:00+03:00",
        "items": [{
            "id": "fixture-story",
            "section": "LOCAL",
            "headline": f"{brand_hint}: titlu fixture verificat",
            "dek": "Conținut sintetic folosit exclusiv pentru testarea rendererului generic.",
            "paragraphs": [],
            "sources": [{"name": "Fixture", "url": "https://example.invalid/source"}],
        }],
    }


def self_test() -> int:
    valcea_html = render("valcea", fixture_edition("valcea", "Publicație pilot"))
    test_html = render("test-local", fixture_edition("test-local", "Publicație test"))
    valcea_cfg, valcea_pack = load_instance("valcea")
    test_cfg, test_pack = load_instance("test-local")
    valcea_identity = publication_identity(valcea_cfg, valcea_pack)
    test_identity = publication_identity(test_cfg, test_pack)
    assert valcea_identity["name"] in valcea_html
    assert test_identity["name"] in test_html
    assert valcea_identity["domain"] in valcea_html
    assert test_identity["domain"] in test_html
    assert valcea_html != test_html
    lowered = test_html.lower()
    for forbidden in ("vâlcea", "valcea", "valceaclar.ro", "râmnicu", "ramnicu"):
        assert forbidden not in lowered, forbidden
    print("LOCAL NEWS OS generic frontpage renderer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--edition")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.edition or not args.output:
        parser.error("--edition and --output are required")
    instance_id = args.instance or default_production_instance_id()
    doc = load_json(Path(args.edition))
    rendered = render(instance_id, doc)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(rendered, encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "instance_id": instance_id,
        "edition_id": doc.get("edition_id"),
        "output": str(output),
        "paid_api_required": False,
        "llm_required": False,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
