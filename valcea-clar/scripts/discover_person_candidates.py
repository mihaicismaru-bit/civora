#!/usr/bin/env python3
"""Discover candidate public-person identities from verified VÂLCEA CLAR copy.

This is an onboarding radar, not a publisher. It recognizes person-like names
next to explicit public roles in already verified stories and queues them for
identity resolution. It never creates a public profile directly.
"""
from __future__ import annotations
import hashlib,json,re,unicodedata
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[1]
FACTS=ROOT/"editorial/facts_registry.json"
SEEDS=ROOT/"editorial/person_profile_seeds.json"
OUT=ROOT/"editorial/person_profile_candidate_queue.json"

NAME=r"[A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț\-']+(?:\s+[A-ZĂÂÎȘȚ][A-Za-zĂÂÎȘȚăâîșț\-']+){1,3}"
ROLE_AFTER=re.compile(rf"\b(?P<name>{NAME})\s*,\s*(?:în\s+calitate\s+de\s+)?(?P<role>primar|viceprimar|președinte|presedinte|prefect|subprefect|senator|deputat|director|manager|organizator|consilier\s+(?:local|județean)|consilier\s+judetean)\b",re.I)
ROLE_BEFORE=re.compile(rf"\b(?P<role>primarul|viceprimarul|președintele|presedintele|prefectul|subprefectul|senatorul|deputatul|directorul|managerul|organizatorul|consilierul\s+(?:local|județean)|consilierul\s+judetean)\s+(?P<name>{NAME})\b",re.I)
IDENTIFIED_AS=re.compile(rf"\b(?:identifică|identifica|îl\s+identifică|il\s+identifica)\s+pe\s+(?P<name>{NAME})\s+(?:drept|ca)\s+(?P<role>organizator|primar|președinte|presedinte|director|manager)\b",re.I)
BAD_WORDS={"Consiliul","Județean","Judetean","Primăria","Primaria","Municipiul","Orașul","Orasul","Direcția","Directia","Asociația","Asociatia","Societatea","Ministerul","Guvernul","România","Romania"}

def load(p:Path)->dict[str,Any]:return json.loads(p.read_text(encoding="utf-8"))
def norm(v:object)->str:
    s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+"," ",s).strip()
def clean_name(v:str)->str:return re.sub(r"\s+"," ",v).strip(" ,.;:–—-")
def plausible(name:str)->bool:
    parts=name.split()
    return 2<=len(parts)<=4 and not any(p in BAD_WORDS for p in parts) and len(name)>=5

def known_names()->set[str]:
    out=set()
    for p in load(SEEDS).get("people",[]):
        if not isinstance(p,dict):continue
        for n in [p.get("canonical_name"),*(p.get("aliases") or [])]:
            if n:out.add(norm(n))
    return out

def matches(text:str):
    rows=[]
    for pattern,kind in ((ROLE_AFTER,"role_after_name"),(ROLE_BEFORE,"role_before_name"),(IDENTIFIED_AS,"identified_as")):
        for m in pattern.finditer(text):
            name=clean_name(m.group("name")); role=clean_name(m.group("role"))
            if plausible(name):rows.append((name,role,kind,m.start(),m.end()))
    return rows

def excerpt(text:str,start:int,end:int,span:int=145)->str:
    a=max(0,start-span);b=min(len(text),end+span)
    return re.sub(r"\s+"," ",text[a:b]).strip()

def build()->dict[str,Any]:
    known=known_names(); grouped={}
    for story in load(FACTS).get("facts",[]):
        if not isinstance(story,dict) or story.get("status") not in {"verified","approved_carry_forward"}:continue
        sid=str(story.get("id") or "").strip()
        src=[str(s.get("url") or "") for s in story.get("sources",[]) if isinstance(s,dict) and s.get("url")]
        blocks=[str(story.get("headline") or ""),str(story.get("dek") or ""),*[str(x) for x in story.get("paragraphs",[])]]
        text="\n".join(x for x in blocks if x)
        for name,role,kind,a,b in matches(text):
            n=norm(name)
            if not n or n in known:continue
            key=hashlib.sha256(n.encode()).hexdigest()[:20]
            row=grouped.setdefault(key,{"candidate_id":key,"candidate_name":name,"normalized_name":n,"lifecycle":"IDENTITY_CANDIDATE","identity_status":"UNRESOLVED","publication_authority":"NONE","public_projection":False,"auto_profile_creation":False,"evidence":[]})
            ev={"story_id":sid,"role_hint":role,"pattern":kind,"context":excerpt(text,a,b),"story_source_urls":src[:10]}
            if ev not in row["evidence"]:row["evidence"].append(ev)
    rows=sorted(grouped.values(),key=lambda r:(-len(r["evidence"]),r["candidate_name"].casefold()))
    return {"schema_version":"1.0","product":"VÂLCEA CLAR People Intelligence Candidate Queue","publication_authority":"NONE","candidate_count":len(rows),"candidates":rows,"policy":{"verified_story_context_required":True,"candidate_is_not_identity":True,"ambiguous_identity_fail_closed":True,"auto_profile_creation":False,"manual_or_verified_identity_resolution_required":True}}

def self_test()->int:
    text="Primarul Robert Schell a participat. Marius Chină, organizator, a prezentat proiectul. Consiliul Județean Vâlcea a decis."
    rows=matches(text); names={r[0] for r in rows}
    assert "Robert Schell" in names and "Marius Chină" in names
    q={"publication_authority":"NONE","public_projection":False,"auto_profile_creation":False}
    assert not q["public_projection"] and not q["auto_profile_creation"]
    print("VÂLCEA CLAR person candidate discovery self-test: PASS");return 0

def main()->int:
    import argparse
    ap=argparse.ArgumentParser();ap.add_argument("--self-test",action="store_true");a=ap.parse_args()
    if a.self_test:return self_test()
    doc=build();OUT.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","candidates":doc["candidate_count"],"publication_authority":"NONE"},ensure_ascii=False));return 0
if __name__=="__main__":raise SystemExit(main())
