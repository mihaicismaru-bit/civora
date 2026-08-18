#!/usr/bin/env python3
"""Bounded historical source discovery for VÂLCEA CLAR People Intelligence.

Discovery has ZERO publication authority. It collects candidate public URLs for
resolved identities, preserves prior observations, extracts date hints, and
prefers older material so profiles can be backfilled over time. Candidates do
not become profile facts until a separate evidence/identity gate admits them.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "editorial" / "person_source_discovery_queue.json"
SEEDS = ROOT / "editorial" / "person_profile_seeds.json"
STATE = ROOT / "editorial" / "person_source_discovery_state.json"
UA = "ValceaClar-PeopleIntelligence/1.0 (+https://valceaclar.ro/)"
YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")
KEYS = (
    "arhiv", "archive", "stiri", "știri", "news", "comunicat", "hotar", "deciz",
    "aleger", "candidat", "rezultat", "declarat", "integritate", "dosar", "instanta",
    "instanță", "sentinta", "sentință", "mandat", "primar", "consili", "deputat",
    "senator", "partid", "cv", "curriculum", "firma", "societ", "asociat", "administrator",
)


class Links(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.rows=[]; self.href=None; self.text=[]
    def handle_starttag(self, tag, attrs):
        d=dict(attrs)
        if tag=="a" and d.get("href"):
            self.href=str(d["href"]); self.text=[]
        if tag=="link" and d.get("href"):
            self.rows.append((str(d["href"]), "link:"+str(d.get("rel") or "")))
    def handle_data(self, data):
        if self.href is not None: self.text.append(data)
    def handle_endtag(self, tag):
        if tag=="a" and self.href is not None:
            self.rows.append((self.href," ".join(self.text))); self.href=None; self.text=[]


def load(path: Path) -> dict[str,Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def norm_url(url: str) -> str:
    p=urllib.parse.urlsplit(url)
    path=re.sub(r"/{2,}","/",p.path or "/")
    return urllib.parse.urlunsplit((p.scheme.lower(),p.netloc.lower(),path,p.query,""))


def fetch(url: str, timeout: int=16) -> tuple[str,bytes,str]:
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xml;q=0.9,*/*;q=0.2"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.geturl(),r.read(1_250_000),(r.headers.get("Content-Type") or "").lower()


def names_by_person() -> dict[str,list[str]]:
    out={}
    for p in load(SEEDS).get("people",[]):
        if not isinstance(p,dict): continue
        pid=str(p.get("id") or "").strip()
        name=str(p.get("canonical_name") or "").strip()
        if pid and name:
            out[pid]=[name,*[str(a).strip() for a in p.get("aliases",[]) if str(a).strip()]]
    return out


def seed_urls_by_person() -> dict[str,list[str]]:
    out={}
    for p in load(SEEDS).get("people",[]):
        if not isinstance(p,dict): continue
        pid=str(p.get("id") or "").strip()
        urls=[]
        for s in p.get("public_sources",[]):
            u=str((s or {}).get("url") or "").strip() if isinstance(s,dict) else ""
            if u.startswith(("http://","https://")): urls.append(u)
        if pid: out[pid]=list(dict.fromkeys(urls))
    return out


def date_hints(text: str) -> list[int]:
    return sorted({int(x) for x in YEAR.findall(text) if 1900 <= int(x) <= 2100})


def candidate(pid: str,url: str,reason: str,label: str,names: list[str]) -> dict[str,Any]:
    hay=(url+" "+label).casefold()
    matched=[n for n in names if n.casefold() in hay]
    years=date_hints(hay)
    return {
        "candidate_id":hashlib.sha256((pid+"\0"+url).encode()).hexdigest()[:24],
        "person_id":pid,"url":url,"discovered_by":reason,
        "matched_identity_terms":matched,"year_hints":years,
        "oldest_year_hint":min(years) if years else None,
        "lifecycle":"DISCOVERED_UNRATED","publication_authority":"NONE",
        "public_projection":False,"auto_publication":False,
    }


def probe_url(pid: str, seed_url: str, names: list[str]) -> dict[str,Any]:
    row={"person_id":pid,"seed_url":seed_url,"checked_at_epoch":int(time.time()),"status":"DEGRADED","final_url":None,"content_sha256":None,"http_error":None,"candidates":[]}
    try:
        final,body,ctype=fetch(seed_url)
        row.update(status="PASS",final_url=final,content_sha256=hashlib.sha256(body).hexdigest())
        p=urllib.parse.urlsplit(final); host=p.netloc.lower().removeprefix("www.")
        origin=urllib.parse.urlunsplit((p.scheme,p.netloc,"/","",""))
        found={}
        for rel,reason in (("robots.txt","standard:robots"),("sitemap.xml","standard:sitemap"),("feed/","standard:feed"),("rss/","standard:rss")):
            u=norm_url(urllib.parse.urljoin(origin,rel)); found[u]=candidate(pid,u,reason,"",names)
        html_like="html" in ctype or b"<html" in body[:1200].lower()
        if html_like:
            parser=Links(); parser.feed(body.decode("utf-8",errors="replace"))
            for href,label in parser.rows:
                try: u=norm_url(urllib.parse.urljoin(final,href))
                except Exception: continue
                q=urllib.parse.urlsplit(u)
                if q.scheme not in {"http","https"} or not q.netloc: continue
                uhost=q.netloc.lower().removeprefix("www.")
                hay=(q.path+" "+q.query+" "+label).casefold()
                same=uhost==host or uhost.endswith("."+host)
                name_hit=any(n.casefold() in hay for n in names)
                key_hit=any(k in hay for k in KEYS)
                if same and (name_hit or key_hit):
                    found[u]=candidate(pid,u,"html:historical_internal",label,names)
        row["candidates"]=list(found.values())[:160]
    except (urllib.error.URLError,urllib.error.HTTPError,TimeoutError,ValueError) as exc:
        row["http_error"]=str(exc)[:400]
    return row


def research_endpoints(queue: dict[str,Any]) -> list[dict[str,Any]]:
    out=[]
    for person in queue.get("tasks",[]):
        if not isinstance(person,dict) or person.get("identity_status")!="RESOLVED": continue
        for task in person.get("tasks",[]):
            if not isinstance(task,dict): continue
            out.append({
                "person_id":person.get("person_id"),"canonical_name":person.get("canonical_name"),
                "source_class":task.get("source_class"),"domains":task.get("domains") or [],
                "query":task.get("query"),"target":task.get("target"),
                "publication_authority":"NONE","auto_publication":False,
            })
    return out


def self_test() -> int:
    c=candidate("p1","https://example.test/archive/2004/person","test","Person 2004",["Person"])
    assert c["publication_authority"]=="NONE" and c["public_projection"] is False and c["auto_publication"] is False
    assert c["oldest_year_hint"]==2004 and c["matched_identity_terms"]==["Person"]
    q={"tasks":[{"person_id":"p","canonical_name":"P","identity_status":"RESOLVED","tasks":[{"source_class":"official_court","domains":["portal.just.ro"],"query":"P","target":"cases"}]}]}
    r=research_endpoints(q); assert len(r)==1 and r[0]["publication_authority"]=="NONE"
    print("VÂLCEA CLAR People source discovery self-test: PASS"); return 0


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument("--self-test",action="store_true"); ap.add_argument("--limit",type=int,default=6); ap.add_argument("--offset",type=int,default=0); a=ap.parse_args()
    if a.self_test:return self_test()
    queue=load(QUEUE); names=names_by_person(); urls=seed_urls_by_person()
    work=[(pid,u) for pid,rows in urls.items() for u in rows]
    selected=[]
    if work:
        off=a.offset%len(work); selected=[work[(off+i)%len(work)] for i in range(min(max(1,a.limit),len(work)))]
    observed=[probe_url(pid,u,names.get(pid,[])) for pid,u in selected]
    previous=load(STATE) if STATE.is_file() else {}
    by_key={(r.get("person_id"),r.get("seed_url")):r for r in previous.get("observations",[]) if isinstance(r,dict)}
    for r in observed:by_key[(r["person_id"],r["seed_url"])]=r
    candidates={}
    for r in by_key.values():
        for c in r.get("candidates",[]): candidates[c["candidate_id"]]=c
    ordered=sorted(candidates.values(),key=lambda c:(c.get("oldest_year_hint") is None,c.get("oldest_year_hint") or 9999,c.get("person_id") or "",c.get("url") or ""))
    out={
      "schema_version":"1.0","product":"VÂLCEA CLAR People Intelligence Historical Discovery State","publication_authority":"NONE",
      "observations":sorted(by_key.values(),key=lambda r:(r.get("person_id") or "",r.get("seed_url") or "")),
      "candidate_count":len(ordered),"candidates":ordered,"research_endpoints":research_endpoints(queue),
      "policy":{"oldest_first_candidate_order":True,"candidate_never_equals_fact":True,"auto_publication":False,"private_evidence_scanned":False}
    }
    STATE.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","probed":len(observed),"candidates":len(ordered),"publication_authority":"NONE"},ensure_ascii=False)); return 0

if __name__=="__main__": raise SystemExit(main())
