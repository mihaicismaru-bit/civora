#!/usr/bin/env python3
"""VÂLCEA CLAR S5 — distinctive editorial products.

Presentation-only layer. It derives reader products from already-published
stories and the canonical Unde ieșim dataset. It never creates a new material
fact or changes the source story.
"""
from __future__ import annotations
import argparse, html, json, re
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
SITE=ROOT/"site"
RUNTIME=SITE/"runtime"
STATE=SITE/"public_ux_state.json"
NAV=SITE/"navigation.json"
ARCHIVE=SITE/"story_archive.json"
CFG=ROOT/"editorial"/"distinctive_products.json"
S2=ROOT/"editorial"/"s2_format_examples.json"
BASE="https://valceaclar.ro"

def load(path:Path,default=None):
    if not path.is_file(): return default
    return json.loads(path.read_text(encoding="utf-8"))

def write(path:Path,text:str):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text,encoding="utf-8")

def write_json(path:Path,value:Any):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def esc(v): return html.escape(str(v or ""),quote=True)

def story_index()->dict[str,dict[str,Any]]:
    doc=load(ARCHIVE,{"stories":[]}) or {"stories":[]}
    return {str(x.get("id")):x for x in doc.get("stories") or [] if isinstance(x,dict) and x.get("id")}

def s2_index()->dict[str,dict[str,Any]]:
    doc=load(S2,{"examples":[]}) or {"examples":[]}
    return {str(x.get("id")):x for x in doc.get("examples") or [] if isinstance(x,dict) and x.get("id")}

def source_list(rows)->str:
    items=[]
    for row in rows or []:
        if not isinstance(row,dict) or not row.get("url"): continue
        label=row.get("name") or row.get("role") or "Sursă"
        items.append(f'<li><a href="{esc(row["url"])}" rel="nofollow noopener">{esc(label)}</a>'
                     + (f' <span class="archive-label">{esc(row.get("tier"))}</span>' if row.get("tier") else "") + '</li>')
    return "".join(items)

def clarification_page(nav,shell,item,story,example)->str:
    documented=(example.get("paragraphs") or [])[:3]
    limits=example.get("limitations") or []
    contributions=example.get("editorial_contribution") or []
    calculations=example.get("calculations") or {}
    calc_html=""
    if calculations:
        calc_html='<section class="factbox">'+"".join(
            f'<div class="fact"><b>{esc(k.replace("_"," "))}</b><span>{esc(v)}%</span></div>'
            for k,v in calculations.items()
        )+'</section>'
    body=(
      f'<main><article class="article" data-s5-product="clarificam"><div class="kicker">{esc(item.get("label"))}</div>'
      f'<h1>{esc(item.get("question"))}</h1><p class="dek">{esc(item.get("framing"))}</p>'
      '<section class="rich"><h2>Ce este documentat</h2>'
      + "".join(f'<p>{esc(p)}</p>' for p in documented) + '</section>'
      + calc_html +
      '<section class="rich"><h2>Ce adaugă redacția</h2><ul>'
      + "".join(f'<li>{esc(x)}</li>' for x in contributions) + '</ul></section>'
      '<section class="rich"><h2>Ce nu putem spune din aceste date</h2><ul>'
      + "".join(f'<li>{esc(x)}</li>' for x in limits) + '</ul></section>'
      f'<section class="article-sources"><h2>Surse și trasabilitate</h2><ul>{source_list(example.get("sources") or story.get("sources"))}</ul>'
      f'<p>Material canonic: <a href="{esc(story.get("path") or "/stiri/"+story["id"]+"/")}">{esc(story.get("headline"))}</a></p></section>'
      '</article></main>'
    )
    return shell(nav,title=f'{item.get("question")} — VÂLCEA CLAR',description=str(item.get("framing") or ""),canonical=BASE+item["route"],body=body)

def render_clarificam(nav,shell,cfg,stories,examples)->list[str]:
    rows=[]
    routes=["/clarificam/"]
    for item in cfg.get("clarificam") or []:
        story=stories.get(str(item.get("source_story_id") or ""))
        example=examples.get(str(item.get("s2_example_id") or ""))
        if not story or not example:
            raise SystemExit(f"S5 Clarificăm source missing: {item.get('id')}")
        route=str(item["route"])
        write(RUNTIME/route.strip("/")/"index.html",clarification_page(nav,shell,item,story,example))
        routes.append(route)
        rows.append(
            '<article class="list-row"><div><div class="kicker">'+esc(item.get("label"))+'</div></div>'
            '<div><h2><a href="'+esc(route)+'">'+esc(item.get("question"))+'</a></h2>'
            '<p>'+esc(item.get("framing"))+'</p></div></article>'
        )
    body=(
      '<main data-s5-product="clarificam-hub"><div class="kicker">CLARIFICĂM / VERIFICAT</div>'
      '<h1 class="index-title">Ce știm. Ce nu știm. Ce rezultă din documente.</h1>'
      '<p class="index-dek">Formatul separă faptele și calculele verificabile de interpretările care ar depăși sursele.</p>'
      '<section class="all-list">'+"".join(rows)+'</section></main>'
    )
    write(RUNTIME/"clarificam"/"index.html",shell(nav,title="Clarificăm — VÂLCEA CLAR",description="Clarificări și verificări bazate pe surse, cu limitele dovezii vizibile.",canonical=BASE+"/clarificam/",body=body))
    return routes

def verification_label(value:str)->str:
    labels={
      "VERIFIED_OFFICIAL":"surse oficiale",
      "VERIFIED_SECONDARY":"surse secundare verificate"
    }
    return labels.get(str(value),str(value).replace("_"," ").lower())

def menu_details(venue:dict[str,Any])->str:
    menu=venue.get("menu") or {}
    highlights=menu.get("highlights") or []
    prices=menu.get("prices") or []
    bits=[]
    if highlights:
        bits.append(" · ".join(str(x) for x in highlights[:4]))
    if prices:
        samples=", ".join(f'{p.get("item")}: {p.get("amount")} {p.get("currency")}' for p in prices[:3])
        asof=next((str(p.get("asOf")) for p in prices if p.get("asOf")),str(menu.get("asOf") or ""))
        bits.append("Prețuri verificate"+(f" la {asof}" if asof else "")+": "+samples)
    return " — ".join(bits)

def render_unde_iesim(nav,shell,cfg)->tuple[list[str],int]:
    spec=cfg["unde_iesim"]
    dataset=load(ROOT/"web"/"unde-iesim.json",{"venues":[]}) or {"venues":[]}
    eligible=[v for v in dataset.get("venues") or [] if isinstance(v,dict) and v.get("editorialEligibility")==spec.get("eligibility")]
    eligible.sort(key=lambda v:str(v.get("name") or ""))
    route_map=spec.get("route_map") or {}
    cards=[]
    for v in eligible:
        vid=str(v.get("id") or "")
        route=route_map.get(vid)
        if not route:
            raise SystemExit(f"S5 Unde ieșim route mapping missing: {vid}")
        hours=v.get("hours") or {}
        hours_text=hours.get("weekly") if str(hours.get("status") or "").startswith("VERIFIED") else None
        address=(v.get("address") or {}).get("display")
        details=[]
        if address: details.append(str(address))
        if hours_text: details.append("Program: "+str(hours_text))
        md=menu_details(v)
        if md: details.append(md)
        unknown=[]
        if not hours_text: unknown.append("programul necesită reverificare")
        op=(v.get("operator") or {}).get("verification")
        if op and str(op).startswith("NEEDS"): unknown.append("operatorul juridic nu este încă verificat")
        cards.append(
          '<article class="card" data-s5-venue="'+esc(vid)+'">'
          '<div class="kicker">VERIFICAT EDITORIAL · '+esc(verification_label(v.get("verification")))+'</div>'
          '<h3><a href="'+esc(route)+'">'+esc(v.get("name"))+'</a></h3>'
          '<p>'+esc(" · ".join(details))+'</p>'
          + (f'<p class="story-date">De reverificat: {esc("; ".join(unknown))}</p>' if unknown else '')
          + f'<div class="story-date">Ultima verificare: {esc(v.get("lastVerifiedAt"))}</div></article>'
        )
    body=(
      '<main data-s5-product="unde-iesim-verificat"><div class="kicker">UNDE IEȘIM</div>'
      f'<h1 class="index-title">{esc(spec.get("title"))}</h1><p class="index-dek">{esc(spec.get("description"))}</p>'
      '<p class="index-dek">Nu este un clasament. Intrarea în selecție înseamnă că fișa are suficiente date pentru publicare; necunoscutele rămân afișate.</p>'
      '<div class="cards">'+"".join(cards)+'</div></main>'
    )
    route=str(spec["route"])
    write(RUNTIME/route.strip("/")/"index.html",shell(nav,title="Unde ieșim — verificat editorial — VÂLCEA CLAR",description=str(spec.get("description") or ""),canonical=BASE+route,body=body))
    return [route],len(eligible)

def pick_paragraph(story,prefix):
    for p in story.get("paragraphs") or []:
        if str(p).startswith(prefix): return p
    return None

def render_dosare(nav,shell,cfg,stories)->list[str]:
    routes=["/dosare/"]; hub=[]
    for item in cfg.get("dosare") or []:
        story=stories.get(str(item.get("source_story_id") or ""))
        if not story: raise SystemExit(f"S5 dossier source story missing: {item.get('id')}")
        selected=[]
        for prefix in item.get("paragraph_prefixes") or []:
            p=pick_paragraph(story,str(prefix))
            if not p: raise SystemExit(f"S5 dossier paragraph missing: {prefix}")
            selected.append(p)
        body=(
          '<main><article class="article" data-s5-product="dosar"><div class="kicker">DOSAR</div>'
          f'<h1>{esc(story.get("headline"))}</h1><p class="dek">{esc(item.get("intro"))}</p>'
          '<section class="rich"><h2>Indexul dosarului</h2>'
          + "".join(f'<p>{esc(p)}</p>' for p in selected) + '</section>'
          f'<section class="article-sources"><h2>Baza documentară</h2><p>{len(story.get("sources") or [])} surse sunt listate în materialul canonic.</p>'
          f'<p><a href="{esc(story.get("path") or "/stiri/"+story["id"]+"/")}">Citește materialul complet și sursele originale →</a></p></section>'
          '</article></main>'
        )
        route=str(item["route"])
        write(RUNTIME/route.strip("/")/"index.html",shell(nav,title=f'Dosar: {story.get("headline")} — VÂLCEA CLAR',description=str(story.get("dek") or ""),canonical=BASE+route,body=body))
        routes.append(route)
        hub.append('<article class="list-row"><div><div class="kicker">DOSAR</div></div><div><h2><a href="'+esc(route)+'">'+esc(story.get("headline"))+'</a></h2><p>'+esc(story.get("dek"))+'</p></div></article>')
    body=(
      '<main data-s5-product="dosare-hub"><div class="kicker">DOSARE</div><h1 class="index-title">Subiecte desfăcute pe documente și surse.</h1>'
      '<p class="index-dek">Dosarul nu este un monitor intern și nu este o listă de suspiciuni: publicăm numai materialul deja trecut prin traseul editorial.</p>'
      '<section class="all-list">'+"".join(hub)+'</section></main>'
    )
    write(RUNTIME/"dosare"/"index.html",shell(nav,title="Dosare — VÂLCEA CLAR",description="Dosare editoriale VÂLCEA CLAR construite din materiale publicate și surse documentate.",canonical=BASE+"/dosare/",body=body))
    return routes

def patch_home():
    path=RUNTIME/"index.html"
    if not path.is_file(): return
    raw=path.read_text(encoding="utf-8")
    if 'data-s5-products="true"' in raw: return
    strip=(
      '<section class="section" data-s5-products="true"><div class="section-head"><h2>Produse VÂLCEA CLAR</h2></div>'
      '<div class="cards">'
      '<article class="card"><div class="kicker">CLARIFICĂM</div><h3><a href="/clarificam/">Ce știm și ce nu știm</a></h3><p>Verificări și explicații cu limitele surselor la vedere.</p></article>'
      '<article class="card"><div class="kicker">UNDE IEȘIM</div><h3><a href="/unde-iesim/verificat/">Verificat editorial</a></h3><p>Fișe cu sursa și data verificării, fără clasamente artificiale.</p></article>'
      '<article class="card"><div class="kicker">DOSARE</div><h3><a href="/dosare/">Documente și context</a></h3><p>Materiale lungi organizate în jurul surselor și al întrebărilor rămase.</p></article>'
      '</div></section>'
    )
    raw=raw.replace("</main>",strip+"</main>",1)
    path.write_text(raw,encoding="utf-8")

def patch_sitemap(routes):
    p=RUNTIME/"sitemap.xml"
    if not p.is_file(): return
    raw=p.read_text(encoding="utf-8"); additions=[]
    for route in routes:
        loc=BASE+route
        if f"<loc>{loc}</loc>" not in raw:
            additions.append(f"  <url><loc>{loc}</loc></url>")
    if additions:
        raw=raw.replace("</urlset>","\n".join(additions)+"\n</urlset>")
        p.write_text(raw,encoding="utf-8")

def apply(*,nav,stories,live_ids,shell):
    cfg=load(CFG,{}) or {}
    idx=story_index(); ex=s2_index()
    routes=[]
    routes+=render_clarificam(nav,shell,cfg,idx,ex)
    ui_routes,venue_count=render_unde_iesim(nav,shell,cfg); routes+=ui_routes
    routes+=render_dosare(nav,shell,cfg,idx)
    patch_home(); patch_sitemap(routes)
    state=load(STATE,{}) or {}; current=list(state.get("routes") or [])
    for r in routes:
        if r not in current: current.append(r)
    state["routes"]=current
    state["s5_distinctive_products"]={
      "status":"OPERATIONAL",
      "clarification_products":len(cfg.get("clarificam") or []),
      "verified_venue_cards":venue_count,
      "dossiers":len(cfg.get("dosare") or []),
      "new_material_fact_authority":False,
      "venue_ranking":False,
      "canonical_inputs":["story_archive","s2_format_examples","web/unde-iesim"]
    }
    write_json(STATE,state)
    return state

def validate():
    cfg=load(CFG,{}) or {}; state=load(STATE,{}) or {}; s5=state.get("s5_distinctive_products") or {}
    if s5.get("status")!="OPERATIONAL": raise SystemExit("S5 state not operational")
    required=["/clarificam/","/unde-iesim/verificat/","/dosare/"]
    required += [x["route"] for x in cfg.get("clarificam") or []]
    required += [x["route"] for x in cfg.get("dosare") or []]
    for r in required:
        p=RUNTIME/r.strip("/")/"index.html"
        if not p.is_file() or p.stat().st_size<200: raise SystemExit(f"S5 route missing: {r}")
    home=(RUNTIME/"index.html").read_text(encoding="utf-8")
    if 'data-s5-products="true"' not in home: raise SystemExit("S5 homepage module missing")
    ui=(RUNTIME/"unde-iesim"/"verificat"/"index.html").read_text(encoding="utf-8")
    if "Nu este un clasament" not in ui: raise SystemExit("S5 venue non-ranking disclosure missing")
    if ui.count('data-s5-venue=') != int(s5.get("verified_venue_cards") or 0): raise SystemExit("S5 venue count mismatch")
    for item in cfg.get("clarificam") or []:
        raw=(RUNTIME/item["route"].strip("/")/"index.html").read_text(encoding="utf-8")
        if "Ce nu putem spune din aceste date" not in raw: raise SystemExit(f"S5 limitation block missing: {item['id']}")
    dossier=cfg.get("dosare") or []
    for item in dossier:
        raw=(RUNTIME/item["route"].strip("/")/"index.html").read_text(encoding="utf-8")
        if 'data-s5-product="dosar"' not in raw or "materialul complet și sursele originale" not in raw:
            raise SystemExit(f"S5 dossier traceability missing: {item['id']}")
    result={"status":"PASS",**s5}
    print(json.dumps(result,ensure_ascii=False))
    return result

def self_test():
    assert verification_label("VERIFIED_OFFICIAL")=="surse oficiale"
    assert verification_label("VERIFIED_SECONDARY")=="surse secundare verificate"
    assert pick_paragraph({"paragraphs":["A. unu","B. doi"]},"B.")=="B. doi"
    print("VÂLCEA CLAR S5 distinctive products self-test: PASS")

def main():
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); p.add_argument("--check",action="store_true"); p.add_argument("--apply",action="store_true"); args=p.parse_args()
    if args.self_test: self_test(); return 0
    if args.check: validate(); return 0
    if args.apply:
        import public_ux_reset as ux
        archive=load(ARCHIVE,{"stories":[]}) or {"stories":[]}
        stories=[x for x in archive.get("stories") or [] if isinstance(x,dict) and x.get("id")]
        live_ids={str(x.get("id")) for x in stories if x.get("active_now") is True}
        nav=load(NAV,{}) or {}
        state=apply(nav=nav,stories=stories,live_ids=live_ids,shell=ux.shell)
        print(json.dumps({"status":"PASS","s5":state.get("s5_distinctive_products")},ensure_ascii=False)); return 0
    p.error("choose --apply, --check or --self-test")

if __name__=="__main__": raise SystemExit(main())
