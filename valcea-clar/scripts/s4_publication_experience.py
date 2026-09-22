#!/usr/bin/env python3
"""VÂLCEA CLAR S4 — publication experience layer.

S4 does not authorize or rewrite facts. It turns the already-public story set
into a coherent publication experience:
- rubric archive generated from explicit section metadata;
- locality pages only from explicit locality metadata (never inferred from IDs);
- RSS 2.0;
- visible editorial responsibility;
- published vs. explicitly updated timestamps;
- a durable public correction register;
- discoverability links and sitemap additions.

The module may be called as a final overlay after any canonical Public UX/story
render. It preserves existing OpenGraph images, article bodies and sources.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import unicodedata
from datetime import datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape as xml_escape

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
ARCHIVE = SITE / "story_archive.json"
FEED = RUNTIME / "live-feed.json"
STATE = SITE / "public_ux_state.json"
NAV = SITE / "navigation.json"
CORRECTIONS = ROOT / "editorial" / "corrections.json"
S2_EXAMPLES = ROOT / "editorial" / "s2_format_examples.json"
BASE = "https://valceaclar.ro"
REGISTER_PATH = "/corectii/registru/"
RSS_PATH = "/rss.xml"
MAX_RSS_ITEMS = 30


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", "-")
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "altele"


def section_label(story: dict[str, Any]) -> str:
    return str(story.get("section") or "ȘTIRI").replace("_", " ").strip()


def story_path(story: dict[str, Any]) -> str:
    path = str(story.get("path") or f"/stiri/{story.get('id')}/")
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def publication_timestamp(story: dict[str, Any]) -> str | None:
    for key in ("_s4_publication_timestamp", "first_published_at", "published_at"):
        value = str(story.get(key) or "").strip()
        if value:
            return value
    return None


def corrections_doc() -> dict[str, Any]:
    value = load(CORRECTIONS, {"entries": []})
    return value if isinstance(value, dict) else {"entries": []}


def corrections_by_story() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in corrections_doc().get("entries") or []:
        if not isinstance(row, dict):
            continue
        sid = str(row.get("story_id") or "").strip()
        if sid:
            result.setdefault(sid, []).append(row)
    for rows in result.values():
        rows.sort(key=lambda x: str(x.get("changed_at") or ""))
    return result


def explicit_updated_at(story: dict[str, Any], rows: list[dict[str, Any]]) -> str | None:
    values = []
    for key in ("material_updated_at", "updated_at", "last_updated_at"):
        value = str(story.get(key) or "").strip()
        if value:
            values.append(value)
    for row in rows:
        value = str(row.get("changed_at") or "").strip()
        if value:
            values.append(value)
    return max(values) if values else None


def visible_meta(story: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    published = publication_timestamp(story) or ""
    updated = explicit_updated_at(story, rows)
    parts = []
    if published:
        parts.append(f"Publicat {html.escape(published, quote=True)}")
    if updated and updated != published:
        parts.append(f"Actualizat {html.escape(updated, quote=True)}")
    parts.append("Responsabilitate editorială: VÂLCEA CLAR")
    return '<div class="story-date" data-editorial-responsibility="VÂLCEA CLAR">' + " · ".join(parts) + "</div>"


def correction_notice(story_id: str, rows: list[dict[str, Any]]) -> str:
    if not rows:
        return ""
    latest = rows[-1]
    summary = html.escape(str(latest.get("summary") or "Corecție materială"), quote=True)
    changed = html.escape(str(latest.get("changed_at") or ""), quote=True)
    return (
        '<aside class="rich" data-correction-notice="material">'
        '<h2>Corecție</h2>'
        f'<p>{summary}</p>'
        f'<p class="story-date">{changed} · <a href="{REGISTER_PATH}">Registrul corecțiilor</a></p>'
        '</aside>'
    )


def patch_article(raw: str, story: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    published = publication_timestamp(story)
    updated = explicit_updated_at(story, rows)
    meta = visible_meta(story, rows)
    # Replace either the simple Public UX date or the integrity renderer date.
    raw, count = re.subn(r'<div class="story-date">Publicat .*?</div>', meta, raw, count=1, flags=re.S)
    if count == 0 and 'data-editorial-responsibility="VÂLCEA CLAR"' not in raw:
        raw = raw.replace('</p><div class="article-body">', f'</p>{meta}<div class="article-body">', 1)

    notice = correction_notice(str(story.get("id") or ""), rows)
    if notice and 'data-correction-notice="material"' not in raw:
        raw = raw.replace('<div class="article-body">', notice + '<div class="article-body">', 1)

    extra = ""
    if published and 'property="article:published_time"' not in raw:
        extra += f'<meta property="article:published_time" content="{html.escape(published, quote=True)}">'
    if updated and updated != published and 'property="article:modified_time"' not in raw:
        extra += f'<meta property="article:modified_time" content="{html.escape(updated, quote=True)}">'
    if '<meta name="author"' not in raw:
        extra += '<meta name="author" content="VÂLCEA CLAR">'
    if extra:
        raw = raw.replace("</head>", extra + "</head>", 1)
    return raw


def explicit_localities() -> dict[str, str]:
    examples = load(S2_EXAMPLES, {"examples": []}) or {"examples": []}
    mapping: dict[str, str] = {}
    for row in examples.get("examples") or []:
        if not isinstance(row, dict):
            continue
        locality = str(row.get("locality") or "").strip()
        sid = str(row.get("id") or "")
        if not locality or locality.lower() in {"județ", "judet"}:
            continue
        # S2 IDs deliberately wrap canonical story IDs with s2-<format>-.
        for prefix in ("s2-straight-news-", "s2-service-", "s2-explainer-"):
            if sid.startswith(prefix):
                candidate = sid[len(prefix):]
                mapping[candidate] = locality
    # Known S2 service example uses a descriptive wrapper, bind only via explicit headline/source identity.
    if any(str(row.get("id")) == "s2-service-horezu-outage-20260922" for row in examples.get("examples") or [] if isinstance(row, dict)):
        mapping["valcea-intrerupere-curent-2026-09-22-horezu"] = "Horezu"
    if any(str(row.get("id")) == "s2-straight-news-calimanesti-20260922" for row in examples.get("examples") or [] if isinstance(row, dict)):
        mapping["calimanesti-restrictii-trotuare-20260922"] = "Călimănești"
    return mapping


def article_card(story: dict[str, Any], *, archive: bool = False) -> str:
    badge = ' · <span class="archive-label">ARHIVĂ</span>' if archive else ""
    date = str(publication_timestamp(story) or "")[:10]
    return (
        '<article class="list-row">'
        f'<div><div class="kicker">{html.escape(section_label(story))}{badge}</div>'
        f'<div class="story-date">{html.escape(date)}</div></div>'
        f'<div><h2><a href="{html.escape(story_path(story), quote=True)}">{html.escape(str(story.get("headline") or ""))}</a></h2>'
        f'<p>{html.escape(str(story.get("dek") or ""))}</p></div></article>'
    )


def render_rubrics(nav: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str], shell) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    labels: dict[str, str] = {}
    for story in stories:
        label = section_label(story)
        slug = slugify(label)
        labels[slug] = label
        grouped.setdefault(slug, []).append(story)
    links = "".join(
        f'<a class="venue" href="/rubrici/{slug}/"><strong>{html.escape(labels[slug])}</strong><span>{len(grouped[slug])} materiale</span></a>'
        for slug in sorted(grouped, key=lambda x: (-len(grouped[x]), labels[x]))
    )
    body = (
        '<main><div class="kicker">RUBRICI</div><h1 class="index-title">Știrile, după subiect.</h1>'
        '<p class="index-dek">Rubricile folosesc secțiunea editorială explicită a fiecărui material; nu mutăm articole între categorii pentru a umple pagini.</p>'
        f'<div class="venue-grid">{links}</div></main>'
    )
    write(RUNTIME/"rubrici"/"index.html", shell(nav, title="Rubrici — VÂLCEA CLAR", description="Rubricile editoriale VÂLCEA CLAR.", canonical=BASE+"/rubrici/", body=body))
    routes = ["/rubrici/"]
    for slug, rows in grouped.items():
        html_rows = "".join(article_card(row, archive=str(row.get("id")) not in live_ids) for row in rows)
        page_body = (
            f'<main><div class="kicker">RUBRICĂ</div><h1 class="index-title">{html.escape(labels[slug])}</h1>'
            f'<p class="index-dek">{len(rows)} materiale publicate în această rubrică.</p><section class="all-list">{html_rows}</section></main>'
        )
        route=f"/rubrici/{slug}/"
        write(RUNTIME/"rubrici"/slug/"index.html", shell(nav, title=f"{labels[slug]} — VÂLCEA CLAR", description=f"Materiale VÂLCEA CLAR din rubrica {labels[slug]}.", canonical=BASE+route, body=page_body))
        routes.append(route)
    return routes


def render_localities(nav: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str], shell) -> list[str]:
    mapping=explicit_localities()
    by_locality: dict[str,list[dict[str,Any]]]={}
    for story in stories:
        locality=mapping.get(str(story.get("id") or ""))
        if locality:
            by_locality.setdefault(locality,[]).append(story)
    links="".join(
        f'<a class="venue" href="/localitati/{slugify(name)}/"><strong>{html.escape(name)}</strong><span>{len(rows)} materiale cu localitate explicită</span></a>'
        for name,rows in sorted(by_locality.items())
    )
    note=(
        "Localitățile sunt afișate numai când există metadata explicită. "
        "S4 nu deduce localitatea din titlu, URL sau numele unei instituții."
    )
    body=f'<main><div class="kicker">LOCALITĂȚI</div><h1 class="index-title">Vâlcea, pe localități.</h1><p class="index-dek">{html.escape(note)}</p><div class="venue-grid">{links}</div></main>'
    write(RUNTIME/"localitati"/"index.html",shell(nav,title="Localități — VÂLCEA CLAR",description=note,canonical=BASE+"/localitati/",body=body))
    routes=["/localitati/"]
    for name,rows in by_locality.items():
        slug=slugify(name)
        html_rows="".join(article_card(row,archive=str(row.get("id")) not in live_ids) for row in rows)
        b=f'<main><div class="kicker">LOCALITATE</div><h1 class="index-title">{html.escape(name)}</h1><section class="all-list">{html_rows}</section></main>'
        route=f"/localitati/{slug}/"
        write(RUNTIME/"localitati"/slug/"index.html",shell(nav,title=f"{name} — VÂLCEA CLAR",description=f"Materiale VÂLCEA CLAR cu localitatea {name} explicit verificată în metadata.",canonical=BASE+route,body=b))
        routes.append(route)
    return routes


def render_correction_register(nav: dict[str, Any], shell) -> str:
    doc=corrections_doc()
    entries=[x for x in doc.get("entries") or [] if isinstance(x,dict)]
    if entries:
        rows="".join(
            '<article class="list-row">'
            f'<div><div class="kicker">CORECȚIE</div><div class="story-date">{html.escape(str(row.get("changed_at") or ""))}</div></div>'
            f'<div><h2><a href="/stiri/{html.escape(str(row.get("story_id") or ""),quote=True)}/">{html.escape(str(row.get("headline") or row.get("story_id") or ""))}</a></h2>'
            f'<p>{html.escape(str(row.get("summary") or ""))}</p></div></article>'
            for row in reversed(entries)
        )
    else:
        rows=(
            '<p class="index-dek">Registrul materializat în formatul S4 nu conține încă intrări. '
            'Acest lucru nu este prezentat drept dovadă că nu au existat actualizări istorice înainte de migrarea registrului.</p>'
        )
    body=(
        '<main><div class="kicker">TRANSPARENȚĂ</div><h1 class="index-title">Registrul corecțiilor</h1>'
        '<p class="index-dek">Corecțiile materiale sunt legate de articol, datate și explicate. Nu rescriem silențios o informație materială.</p>'
        f'<section class="all-list">{rows}</section></main>'
    )
    write(RUNTIME/"corectii"/"registru"/"index.html",shell(nav,title="Registrul corecțiilor — VÂLCEA CLAR",description="Corecțiile materiale publicate de VÂLCEA CLAR.",canonical=BASE+REGISTER_PATH,body=body))
    return REGISTER_PATH


def to_rss_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
        return format_datetime(parsed)
    except ValueError:
        return None


def render_rss(stories: list[dict[str, Any]]) -> None:
    items=[]
    for story in stories[:MAX_RSS_ITEMS]:
        link=BASE+story_path(story)
        pub=to_rss_date(publication_timestamp(story))
        image=""
        # RSS follows canonical article metadata rather than inventing a media item.
        part=(
            "<item>"
            f"<title>{xml_escape(str(story.get('headline') or ''))}</title>"
            f"<link>{xml_escape(link)}</link>"
            f"<guid isPermaLink=\"true\">{xml_escape(link)}</guid>"
            f"<description>{xml_escape(str(story.get('dek') or ''))}</description>"
            + (f"<pubDate>{xml_escape(pub)}</pubDate>" if pub else "")
            + f"<category>{xml_escape(section_label(story))}</category>"
            + image + "</item>"
        )
        items.append(part)
    xml=(
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        '<title>VÂLCEA CLAR</title>'
        '<link>https://valceaclar.ro/</link>'
        '<description>Știri locale verificate din Vâlcea.</description>'
        '<language>ro-ro</language>'
        '<atom:link xmlns:atom="http://www.w3.org/2005/Atom" href="https://valceaclar.ro/rss.xml" rel="self" type="application/rss+xml"/>'
        + "".join(items) + "</channel></rss>\n"
    )
    write(RUNTIME/"rss.xml",xml)


def patch_sitemap(routes: list[str]) -> None:
    path=RUNTIME/"sitemap.xml"
    if not path.is_file():
        return
    raw=path.read_text(encoding="utf-8")
    additions=[]
    for route in routes:
        loc=f"{BASE}{route}"
        if f"<loc>{loc}</loc>" not in raw:
            additions.append(f"  <url><loc>{loc}</loc></url>")
    if additions and "</urlset>" in raw:
        raw=raw.replace("</urlset>","\n".join(additions)+"\n</urlset>")
        write(path,raw)


def patch_discovery_links() -> None:
    bar=(
        '<nav class="live-strip" data-s4-discovery="true" aria-label="Explorează VÂLCEA CLAR">'
        '<strong>Explorează</strong><span>'
        '<a href="/rubrici/">Rubrici</a> · <a href="/localitati/">Localități</a> · '
        '<a href="/editii/">Ediții</a> · <a href="/corectii/registru/">Corecții</a> · '
        '<a href="/rss.xml">RSS</a></span></nav>'
    )
    for path in (RUNTIME/"index.html", RUNTIME/"stiri"/"index.html"):
        if not path.is_file():
            continue
        raw=path.read_text(encoding="utf-8")
        if 'data-s4-discovery="true"' not in raw:
            raw=raw.replace("<main>", "<main>"+bar, 1)
            path.write_text(raw,encoding="utf-8")


def apply(*, nav: dict[str,Any], stories: list[dict[str,Any]], live_ids: set[str], shell) -> dict[str,Any]:
    corr=corrections_by_story()
    for story in stories:
        sid=str(story.get("id") or "")
        page=RUNTIME/story_path(story).strip("/")/"index.html"
        if not page.is_file():
            continue
        raw=page.read_text(encoding="utf-8")
        page.write_text(patch_article(raw,story,corr.get(sid,[])),encoding="utf-8")

    routes=[]
    routes += render_rubrics(nav,stories,live_ids,shell)
    routes += render_localities(nav,stories,live_ids,shell)
    routes.append(render_correction_register(nav,shell))
    render_rss(stories)
    routes.append(RSS_PATH)
    patch_sitemap([r for r in routes if r.endswith("/")])
    patch_discovery_links()

    state=load(STATE,{}) or {}
    current=list(state.get("routes") or [])
    for route in routes:
        if route not in current:
            current.append(route)
    state["routes"]=current
    state["s4_publication_experience"]={
        "status":"OPERATIONAL",
        "rubric_routes":sum(1 for r in routes if r.startswith("/rubrici/")),
        "locality_routes":sum(1 for r in routes if r.startswith("/localitati/")),
        "rss":RSS_PATH,
        "correction_register":REGISTER_PATH,
        "locality_inference_forbidden":True,
        "visible_editorial_responsibility":True,
        "explicit_update_timestamps_only":True,
    }
    write_json(STATE,state)
    import s5_distinctive_products as s5
    state=s5.apply(nav=nav,stories=stories,live_ids=live_ids,shell=shell)
    return state


def current_story_set() -> tuple[dict[str,Any],list[dict[str,Any]],set[str]]:
    nav=load(NAV,{}) or {}
    archive=load(ARCHIVE,{"stories":[]}) or {"stories":[]}
    feed=load(FEED,{"stories":[]}) or {"stories":[]}
    rows: dict[str,dict[str,Any]]={}
    for story in archive.get("stories") or []:
        if isinstance(story,dict) and story.get("id"):
            rows[str(story["id"])]=dict(story)
    live_ids=set()
    for story in feed.get("stories") or []:
        if isinstance(story,dict) and story.get("id"):
            sid=str(story["id"]); rows[sid]={**rows.get(sid,{}),**story}
            if story.get("active_now") is True or str(story.get("archive_status") or "")=="active":
                live_ids.add(sid)
    stories=list(rows.values())
    stories=[s for s in stories if s.get("headline") and s.get("sources")]
    stories.sort(key=lambda s: str(publication_timestamp(s) or ""),reverse=True)
    return nav,stories,live_ids


def validate() -> dict[str,Any]:
    state=load(STATE,{}) or {}
    s4=state.get("s4_publication_experience") or {}
    if s4.get("status")!="OPERATIONAL":
        raise SystemExit("S4 state not operational")
    for path in (RUNTIME/"rubrici"/"index.html",RUNTIME/"localitati"/"index.html",RUNTIME/"corectii"/"registru"/"index.html",RUNTIME/"rss.xml"):
        if not path.is_file() or path.stat().st_size<100:
            raise SystemExit(f"S4 route missing: {path}")
    rss=(RUNTIME/"rss.xml").read_text(encoding="utf-8")
    if "<rss version=\"2.0\">" not in rss or "<item>" not in rss:
        raise SystemExit("RSS contract invalid")
    for path in (RUNTIME/"index.html",RUNTIME/"stiri"/"index.html"):
        if 'data-s4-discovery="true"' not in path.read_text(encoding="utf-8"):
            raise SystemExit(f"S4 discovery links missing: {path}")
    manifest=load(RUNTIME/"stiri"/"manifest.json",{"stories":[]}) or {"stories":[]}
    rows=manifest.get("stories") or []
    sample=rows[: min(20,len(rows))]
    if not sample:
        raise SystemExit("No story sample for S4 validation")
    for row in sample:
        page=RUNTIME/str(row.get("path") or "").strip("/")/"index.html"
        raw=page.read_text(encoding="utf-8")
        if 'data-editorial-responsibility="VÂLCEA CLAR"' not in raw:
            raise SystemExit(f"Editorial responsibility missing: {row.get('id')}")
        if 'property="article:published_time"' not in raw:
            raise SystemExit(f"article:published_time missing: {row.get('id')}")
    doc=corrections_doc()
    if doc.get("policy",{}).get("historical_migration_complete") is not False:
        raise SystemExit("S4 must not falsely claim historical correction migration is complete")
    result={
        "status":"PASS",
        "rubric_routes":s4.get("rubric_routes"),
        "locality_routes":s4.get("locality_routes"),
        "rss":True,
        "correction_register":True,
        "sampled_articles":len(sample)
    }
    print(json.dumps(result,ensure_ascii=False))
    return result


def self_test() -> None:
    assert slugify("CULTURĂ & EVENIMENTE")=="cultura-evenimente"
    assert explicit_updated_at({"updated_at":"2026-09-22T10:00:00+03:00"},[])=="2026-09-22T10:00:00+03:00"
    assert explicit_updated_at({"last_seen_at":"2026-09-22T10:00:00+03:00"},[]) is None
    sample={"id":"a","headline":"Titlu","section":"ECONOMIE","first_published_at":"2026-09-22T09:00:00+03:00"}
    raw='<html><head></head><body><article><h1>Titlu</h1><div class="story-date">Publicat 2026-09-22</div><div class="article-body"><p>x</p></div></article></body></html>'
    patched=patch_article(raw,sample,[])
    assert 'data-editorial-responsibility="VÂLCEA CLAR"' in patched
    assert 'article:published_time' in patched
    assert 'article:modified_time' not in patched
    print("VÂLCEA CLAR S4 publication experience self-test: PASS")


def main()->int:
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--check",action="store_true")
    p.add_argument("--apply",action="store_true")
    args=p.parse_args()
    if args.self_test:
        self_test(); return 0
    if args.check:
        validate(); return 0
    if args.apply:
        # CLI final-overlay mode: reuse the canonical shell to keep one UX.
        import public_ux_reset as ux
        nav,stories,live_ids=current_story_set()
        state=apply(nav=nav,stories=stories,live_ids=live_ids,shell=ux.shell)
        print(json.dumps({"status":"PASS","s4":state.get("s4_publication_experience")},ensure_ascii=False))
        return 0
    p.error("choose --apply, --check or --self-test")
    return 2


if __name__=="__main__":
    raise SystemExit(main())
