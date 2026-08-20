#!/usr/bin/env python3
'''Attach resolved People Intelligence profiles to relevant VÂLCEA CLAR stories.'''
from __future__ import annotations
import html,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/"site/runtime"
PEOPLE=RUNTIME/"people.json"
FEED=RUNTIME/"live-feed.json"
MANIFEST=RUNTIME/"stiri/manifest.json"
START='<section class="person-profiles" data-people-intelligence="verified">'
END='</section><!-- /person-profiles -->'

def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def esc(v): return html.escape(str(v or ""),quote=True)

def grouped(doc):
    out={}
    for p in doc.get("profiles",[]):
        if p.get("publication_status")!="public" or p.get("identity",{}).get("status")!="RESOLVED": continue
        if not str(p.get("path") or "").startswith("/oameni/"): continue
        row={"id":p["id"],"name":p["name"],"path":p["path"],"profile_types":p.get("profile_types",[]),"identity_resolved":True}
        for sid in p.get("story_refs",[]):
            if sid: out.setdefault(str(sid),[]).append(row)
    for sid,rows in out.items():
        out[sid]=sorted({r["path"]:r for r in rows}.values(),key=lambda r:r["name"].casefold())
    return out

def section(rows):
    if not rows:return ""
    lis="".join(f'<li><a href="{esc(r["path"])}">{esc(r["name"])}</a> <small>{esc(", ".join(str(x).replace("_"," ") for x in r["profile_types"][:3]))}</small></li>' for r in rows)
    return START+'<h2>Oameni din acest material</h2><p>Profiluri publice VÂLCEA CLAR cu identitate rezolvată și istoric construit incremental din surse verificabile.</p><ul>'+lis+'</ul>'+END

def inline(fragment,rows):
    cand=[r for r in rows if r.get("name") and str(r.get("path","")).startswith("/oameni/")]
    if not cand:return fragment
    cand.sort(key=lambda r:(-len(r["name"]),r["name"].casefold()))
    mapping={esc(r["name"]):r for r in cand}
    pattern=re.compile("|".join(re.escape(x) for x in mapping))
    parts=re.split(r"(<[^>]+>)",fragment)
    inside_anchor=False
    for i,part in enumerate(parts):
        if i%2:
            low=part.lower()
            if low.startswith("<a "): inside_anchor=True
            elif low.startswith("</a"): inside_anchor=False
            continue
        if inside_anchor or not part: continue
        def repl(m):
            r=mapping[m.group(0)]
            return f'<a class="person-inline-link" href="{esc(r["path"])}" data-person-profile="{esc(r["id"])}">{m.group(0)}</a>'
        parts[i]=pattern.sub(repl,part)
    return "".join(parts)

def patch_static(path,rows):
    if not path.is_file(): return False
    before=path.read_text(encoding="utf-8")
    # Consume whitespace left by the previous generated block so repeated
    # runs are byte-stable instead of adding a blank line on every schedule.
    text=re.sub(r"\s*"+re.escape(START)+r".*?"+re.escape(END),"",before,flags=re.S)
    m=re.search(r"<article>(.*?)</article>",text,re.S)
    if m and rows:
        body=inline(m.group(1),rows)
        text=text[:m.start()]+"<article>"+body+"</article>"+text[m.end():]
    block=section(rows)
    if block:
        anchor='<section class="sources">'
        if anchor in text:text=text.replace(anchor,block+"\n"+anchor,1)
        else:text=text.replace("</article>",block+"\n</article>",1)
    if text==before:return False
    path.write_text(text,encoding="utf-8"); return True

def main():
    if not PEOPLE.is_file() or not FEED.is_file(): raise SystemExit("people.json and live-feed.json required")
    g=grouped(load(PEOPLE)); feed=load(FEED); changed=0; static=0
    for s in feed.get("stories",[]):
        sid=str(s.get("id") or ""); rows=g.get(sid,[])
        old=s.get("person_profiles",[])
        if rows:s["person_profiles"]=rows
        else:s.pop("person_profiles",None)
        if old!=rows:changed+=1
        if patch_static(RUNTIME/"stiri"/sid/"index.html",rows):static+=1
    feed.setdefault("extensions",{})["people_intelligence"]={
      "enabled":True,"profile_directory":"/oameni/","story_links_bidirectional":True,
      "inline_story_mentions_linked":True,"identity_resolution_fail_closed":True,
      "sensitive_claims_fail_closed":True,"private_evidence_public_projection":False
    }
    FEED.write_text(json.dumps(feed,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if MANIFEST.is_file():
        m=load(MANIFEST)
        for r in m.get("stories",[]):
            rows=g.get(str(r.get("id") or ""),[])
            if rows:
                r["person_profile_ids"]=[p["id"] for p in rows]
                r["person_profile_paths"]=[p["path"] for p in rows]
                r["person_inline_links"]=True
            else:
                for k in ("person_profile_ids","person_profile_paths","person_inline_links"):r.pop(k,None)
        m.setdefault("cross_linking",{})["people_intelligence"]="resolved_public_profiles_inline_and_index"
        MANIFEST.write_text(json.dumps(m,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","stories_with_people":len(g),"feed_changed":changed,"static_changed":static},ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
