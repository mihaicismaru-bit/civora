#!/usr/bin/env python3
'''Render indexable /oameni/ pages from public VÂLCEA CLAR People Intelligence.'''
from __future__ import annotations
import html, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PEOPLE=ROOT/"site/runtime/people.json"
RUNTIME=ROOT/"site/runtime"
INDEXING=ROOT/"site/indexing_routes.json"
BASE="https://valceaclar.ro"

def load(p:Path): return json.loads(p.read_text(encoding="utf-8"))
def esc(v): return html.escape(str(v or ""),quote=True)

def shell(title,description,body,canonical):
    return f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — VÂLCEA CLAR</title><meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(canonical)}"><meta name="robots" content="index,follow">
<meta property="og:type" content="profile"><meta property="og:site_name" content="VÂLCEA CLAR"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}">
<style>:root{{--navy:#071a3d;--red:#d71920;--ink:#101828;--muted:#667085;--line:#e4e7ec;--soft:#f6f7f9}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font:16px/1.62 system-ui,-apple-system,Segoe UI,Arial,sans-serif}}header{{background:var(--navy);color:white;padding:20px 22px}}header a{{color:white;text-decoration:none;font:700 32px Georgia,serif}}nav{{margin-top:10px;display:flex;gap:18px;flex-wrap:wrap}}nav a{{font:800 12px system-ui;color:#fff;text-transform:uppercase}}main{{max-width:1050px;margin:auto;padding:38px 22px 64px}}.k{{color:var(--red);font-weight:900;font-size:12px;letter-spacing:.08em;text-transform:uppercase}}h1{{font:800 clamp(38px,6vw,66px)/1.04 Georgia,serif;letter-spacing:-.03em;margin:7px 0 14px}}h2{{font:800 25px/1.2 Georgia,serif}}.dek{{font-size:20px;color:#475467;max-width:820px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-top:28px}}.card{{border:1px solid var(--line);border-radius:12px;padding:16px;text-decoration:none;color:inherit}}.card strong{{display:block;font:700 21px Georgia,serif}}.card span{{color:var(--muted);font-size:13px}}.box{{margin-top:30px;border-top:2px solid var(--ink);padding-top:14px}}ul{{padding-left:20px}}li{{margin:8px 0}}.notice{{background:var(--soft);border-left:4px solid var(--red);padding:13px 16px;color:#475467;margin:22px 0}}.tag{{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:5px 9px;margin:3px 5px 3px 0;font-size:12px;font-weight:800}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}main{{padding:28px 16px 52px}}}}</style></head><body>
<header><a href="/">VÂLCEA CLAR</a><nav><a href="/stiri/">Știri</a><a href="/oameni/">Oameni</a><a href="/artisti/">Artiști</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>{body}</body></html>'''

def role_label(r):
    end=str(r.get("to") or "")
    if not end and str(r.get("status") or "").startswith("current"): end="prezent"
    dates=" – ".join(x for x in (str(r.get("from") or ""),end) if x)
    return f"{r.get('title')} — {r.get('organization')}" + (f" ({dates})" if dates else "")

def legal_label(r):
    bits=[str(r.get("case_number") or "").strip(),str(r.get("role") or "").strip(),str(r.get("legal_status") or "").strip()]
    return " · ".join(x for x in bits if x)

def render_index(profiles):
    cards=[]
    for p in profiles:
        tags=", ".join(str(x).replace("_"," ") for x in p.get("profile_types",[])[:3])
        cards.append(f'<a class="card" href="{esc(p["path"])}"><strong>{esc(p["name"])}</strong><span>{esc(tags or "profil public")}</span></a>')
    desc="Profiluri publice VÂLCEA CLAR construite incremental din documente, arhive, alegeri și surse verificabile. Identitățile ambigue și afirmațiile sensibile rămân blocate până la verificare."
    body=f'<main><div class="k">PEOPLE INTELLIGENCE</div><h1>Oameni</h1><p class="dek">{esc(desc)}</p><div class="grid">{"".join(cards)}</div></main>'
    target=RUNTIME/"oameni/index.html"; target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(shell("Oameni",desc,body,BASE+"/oameni/"),encoding="utf-8")

def source_list(p):
    rows=[]
    for s in p.get("public_sources",[]):
        if s.get("url"):
            rows.append(f'<li><a href="{esc(s["url"])}" rel="nofollow noopener" target="_blank">{esc(s.get("name") or "Sursă publică")}</a> <small>{esc(s.get("tier") or "")}</small></li>')
    return "".join(rows)

def render_profile(p):
    tags="".join(f'<span class="tag">{esc(str(x).replace("_"," "))}</span>' for x in p.get("profile_types",[]))
    roles="".join(f"<li>{esc(role_label(r))}</li>" for r in p.get("roles",[]))
    elections="".join(f'<li>{esc(r.get("label") or "Participare electorală")}{" — "+esc(r.get("result")) if r.get("result") else ""}</li>' for r in p.get("election_history",[]))
    legal="".join(f"<li>{esc(legal_label(r))}</li>" for r in p.get("legal_cases",[]))
    companies="".join(f"<li>{esc((r.get('organization') or r.get('company')))} — {esc(r.get('role'))}</li>" for r in p.get("public_companies_and_organizations",[]))
    rel="".join(f"<li>{esc(r.get('person_name'))} — {esc(r.get('relation'))}</li>" for r in p.get("relationships",[]))
    chronological="".join(f"<li>{esc(r.get('date') or 'dată neprecizată')} — {esc(r.get('label'))}</li>" for r in p.get("timeline",[]))
    sections=[]
    if roles: sections.append(f'<section class="box"><h2>Funcții și roluri</h2><ul>{roles}</ul></section>')
    if elections: sections.append(f'<section class="box"><h2>Istoric electoral</h2><ul>{elections}</ul></section>')
    if companies: sections.append(f'<section class="box"><h2>Companii și organizații documentate public</h2><ul>{companies}</ul></section>')
    if rel: sections.append(f'<section class="box"><h2>Relații public documentate și relevante</h2><ul>{rel}</ul></section>')
    if legal:
        sections.append('<section class="box"><h2>Dosare și istoric juridic</h2><div class="notice">Existența unui dosar nu dovedește vinovăția. Rolul procesual și stadiul sunt afișate separat, exact cum rezultă din sursele admise.</div><ul>'+legal+'</ul></section>')
    if chronological: sections.append(f'<section class="box"><h2>Cronologie</h2><ul>{chronological}</ul></section>')
    desc=str(p.get("summary") or f"Profil public {p.get('name')}.")
    body=f'''<main><article><div class="k">PROFIL PUBLIC</div><h1>{esc(p.get("name"))}</h1><p class="dek">{esc(desc)}</p><p>{tags}</p>
<div class="notice">Profil în dezvoltare continuă. VÂLCEA CLAR separă faptele publice verificate de pistele de investigație și nu publică surse editoriale private.</div>
{"".join(sections)}
<section class="box"><h2>Surse publice</h2><ul>{source_list(p)}</ul></section>
<p><a href="/oameni/">← Toate profilurile</a></p></article></main>'''
    target=RUNTIME/p["path"].strip("/")/"index.html"; target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(shell(p["name"],desc[:280],body,BASE+p["path"]),encoding="utf-8")

def update_indexing(profiles):
    d=load(INDEXING)
    base=[str(r) for r in d.get("routes",[]) if not str(r).startswith("/oameni/")]
    person=["/oameni/",*[p["path"] for p in profiles]]
    d["routes"]=list(dict.fromkeys(base+person))
    pol=d.setdefault("policy",{})
    pol["people_routes_owned_by_people_intelligence"]=True
    pol["people_identity_and_sensitive_claims_fail_closed"]=True
    INDEXING.write_text(json.dumps(d,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
    d=load(PEOPLE)
    profiles=[p for p in d.get("profiles",[]) if p.get("publication_status")=="public" and p.get("identity",{}).get("status")=="RESOLVED" and p.get("path")]
    profiles.sort(key=lambda p:p["name"].casefold())
    if not profiles: raise SystemExit("No public people profiles")
    render_index(profiles)
    for p in profiles: render_profile(p)
    update_indexing(profiles)
    print(json.dumps({"status":"PASS","profiles":len(profiles),"routes":len(profiles)+1},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
