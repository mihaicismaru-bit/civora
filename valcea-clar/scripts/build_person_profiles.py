#!/usr/bin/env python3
"""Build fail-closed public-person profiles for VÂLCEA CLAR.

Public profiles grow incrementally. Private newsroom evidence (including ONRC
extracts) may contribute to research, but raw private content never enters the
public artifact and private-only claims never auto-publish.
"""
from __future__ import annotations
import argparse, copy, hashlib, json, os, re, unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT/"editorial/person_profile_policy.json"
SEEDS = ROOT/"editorial/person_profile_seeds.json"
OVERRIDES = ROOT/"editorial/person_profile_overrides.json"
OUT = ROOT/"site/runtime/people.json"
QUEUE = ROOT/"editorial/person_source_discovery_queue.json"
PRIVATE_ENV = "VALCEA_CLAR_PRIVATE_EVIDENCE_MANIFEST"

LEGAL = {
    "PLAINTIFF","DEFENDANT_CIVIL","PETITIONER","RESPONDENT","SUSPECT",
    "DEFENDANT_CRIMINAL","INDICTED","CONVICTED_NOT_FINAL","CONVICTED_FINAL",
    "ACQUITTED","CASE_DISMISSED","PROCEEDINGS_TERMINATED",
    "IMPRISONMENT_SERVED_VERIFIED","UNKNOWN",
}

def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def norm(v: object) -> str:
    s=unicodedata.normalize("NFKD",str(v or "")).encode("ascii","ignore").decode().casefold()
    return re.sub(r"[^a-z0-9]+"," ",s).strip()

def source_map(seed: dict) -> dict[str, dict]:
    return {str(s["url"]):s for s in seed.get("public_sources",[]) if isinstance(s,dict) and s.get("url")}

def urls(row: dict) -> list[str]:
    return [str(u).strip() for u in row.get("source_urls",[]) if str(u).startswith(("http://","https://"))]

def sourced(row: dict, sources: dict[str,dict]) -> bool:
    u=urls(row)
    return bool(u) and all(x in sources for x in u)

def legal_gate(row: dict, sources: dict[str,dict]) -> tuple[bool,str]:
    status=str(row.get("legal_status") or "UNKNOWN").upper()
    if status not in LEGAL: return False,"invalid_legal_status"
    if status=="UNKNOWN": return False,"unknown_legal_status"
    if not str(row.get("role") or "").strip(): return False,"missing_legal_role"
    if not sourced(row,sources): return False,"missing_or_unregistered_public_source"
    if status=="IMPRISONMENT_SERVED_VERIFIED":
        if row.get("final_legal_basis") is not True:
            return False,"imprisonment_requires_final_legal_basis"
        authoritative=any(
            sources[u].get("tier")=="T1" and sources[u].get("source_class") in
            {"official_court","official_gazette","public_authority"}
            for u in urls(row)
        )
        if not authoritative: return False,"imprisonment_requires_authoritative_source"
    return True,"PASS"

def relation_gate(row: dict, sources: dict[str,dict]) -> tuple[bool,str]:
    if row.get("publicly_documented") is not True: return False,"not_publicly_documented"
    if row.get("public_interest_relevance") is not True: return False,"not_public_interest"
    if not row.get("person_name") or not row.get("relation"): return False,"missing_relation"
    return (True,"PASS") if sourced(row,sources) else (False,"missing_public_source")

def company_gate(row: dict, sources: dict[str,dict]) -> tuple[bool,str]:
    if not (row.get("organization") or row.get("company")) or not row.get("role"):
        return False,"missing_company_role"
    if not sourced(row,sources): return False,"missing_public_source"
    if row.get("beneficial_owner") is True and row.get("beneficial_owner_explicitly_documented") is not True:
        return False,"beneficial_owner_inference_forbidden"
    if row.get("shareholder") is True and row.get("shareholding_explicitly_documented") is not True:
        return False,"shareholding_inference_forbidden"
    return True,"PASS"

def private_records(path: str|None) -> list[dict]:
    if not path: return []
    rows=load(Path(path).expanduser().resolve()).get("records",[])
    if not isinstance(rows,list): raise ValueError("private manifest records must be list")
    return [r for r in rows if isinstance(r,dict)]

def receipts(pid: str, records: list[dict]) -> list[dict]:
    out=[]
    for r in records:
        if r.get("person_id")!=pid: continue
        rec={k:str(r.get(k) or "") for k in ("opaque_evidence_id","sha256","evidence_class","verification_state")}
        if not rec["opaque_evidence_id"] or not re.fullmatch(r"[a-fA-F0-9]{64}",rec["sha256"]):
            raise ValueError(f"{pid}: invalid private evidence receipt")
        out.append(rec)
    return out

def tasks(seed: dict) -> list[dict]:
    names=[seed["canonical_name"],*seed.get("aliases",[])]
    q=" OR ".join(f'"{n}"' for n in names if n)
    base=[
      ("official_court",["portal.just.ro"],"case history and procedural status"),
      ("official_gazette",["monitoruloficial.ro"],"appointments, dismissals and official acts"),
      ("public_authority_archives",["gov.ro","senat.ro","cdep.ro","cjvalcea.ro","primariavl.ro","primariabrezoi.ro"],"roles, CVs and archive mentions"),
      ("press_archives",[],"historical context and contemporaneous reporting"),
    ]
    if set(seed.get("profile_types",[])) & {"politician","public_official"}:
        base += [
          ("elections",["roaep.ro","prezenta.roaep.ro","bec.ro"],"candidacies and results"),
          ("integrity_and_declarations",["integritate.eu","old-declaratii.integritate.eu"],"historical public declarations and integrity findings"),
        ]
    return [{"source_class":c,"domains":d,"query":q,"target":t,"publication_authority":"NONE"} for c,d,t in base]

def timeline(p: dict) -> list[dict]:
    out=[]
    for r in p.get("roles",[]):
        out.append({"date":r.get("from"),"end_date":r.get("to"),"type":"role","label":f"{r.get('title')} — {r.get('organization')}","source_urls":r.get("source_urls",[])})
    for r in p.get("election_history",[]):
        out.append({"date":r.get("date"),"type":"election","label":r.get("label") or "Participare electorală","source_urls":r.get("source_urls",[])})
    for r in p.get("legal_cases",[]):
        out.append({"date":r.get("date") or r.get("registered_at"),"type":"legal_case","label":r.get("public_label") or f"Dosar {r.get('case_number','')}","legal_status":r.get("legal_status"),"role":r.get("role"),"source_urls":r.get("source_urls",[])})
    return sorted(out,key=lambda r:(str(r.get("date") or "9999"),str(r.get("type") or ""),str(r.get("label") or "")))

def set_path(obj: dict,path: str,value: Any):
    parts=path.split("."); node=obj
    for p in parts[:-1]: node=node.setdefault(p,{})
    node[parts[-1]]=copy.deepcopy(value)

def get_path(obj: dict,path: str):
    node:Any=obj
    for p in path.split("."):
        if not isinstance(node,dict) or p not in node: return None
        node=node[p]
    return node

def del_path(obj: dict,path: str):
    parts=path.split("."); node:Any=obj
    for p in parts[:-1]:
        if not isinstance(node,dict): return
        node=node.get(p)
    if isinstance(node,dict): node.pop(parts[-1],None)

def overlay(profile: dict, rule: dict) -> dict:
    if not rule: return profile
    note=str(rule.get("audit_note") or "").strip()
    if not note: raise ValueError(f"{profile['id']}: override requires audit_note")
    for p,v in rule.get("set",{}).items(): set_path(profile,p,v)
    for p,vals in rule.get("append",{}).items():
        cur=get_path(profile,p)
        if cur is None: set_path(profile,p,[]); cur=get_path(profile,p)
        if not isinstance(cur,list): raise ValueError(f"{profile['id']}: append target must be list")
        for v in vals if isinstance(vals,list) else [vals]:
            if v not in cur: cur.append(copy.deepcopy(v))
    for p in rule.get("suppress",[]): del_path(profile,p)
    profile["manual_override"]={"applied":True,"audit_note":note,"updated_at":rule.get("updated_at")}
    return profile

def summary(seed: dict) -> str:
    current=next((r for r in seed.get("roles",[]) if str(r.get("status","")).startswith("current")),None)
    if current:
        lead=f"{seed['canonical_name']} este documentat de VÂLCEA CLAR ca {str(current.get('title') or '').lower()} în cadrul {current.get('organization')}."
    else:
        lead=f"{seed['canonical_name']} are un profil public VÂLCEA CLAR construit din documente și apariții verificabile."
    return " ".join(x for x in (lead,str(seed.get("public_interest_basis") or "").strip()) if x)

def profile(seed: dict, rule: dict, priv: list[dict]) -> dict:
    pid=str(seed.get("id") or "").strip()
    name=str(seed.get("canonical_name") or "").strip()
    identity=seed.get("identity") if isinstance(seed.get("identity"),dict) else {}
    if not pid or not name: raise ValueError("seed missing id/name")
    if identity.get("status")!="RESOLVED": raise ValueError(f"{pid}: identity must be RESOLVED")
    sm=source_map(seed)
    if not sm: raise ValueError(f"{pid}: public source required")
    roles=copy.deepcopy(seed.get("roles",[]))
    for i,r in enumerate(roles):
        if not sourced(r,sm): raise ValueError(f"{pid}.roles[{i}]: public source binding required")
    holds=[]

    elections=[]
    for i,r in enumerate(copy.deepcopy(seed.get("election_history",[]))):
        if sourced(r,sm): elections.append(r)
        else: holds.append({"kind":"election","index":i,"reason":"missing_public_source"})

    legal=[]
    for i,r in enumerate(copy.deepcopy(seed.get("legal_cases",[]))):
        ok,why=legal_gate(r,sm)
        (legal if ok else holds).append(r if ok else {"kind":"legal_case","index":i,"reason":why})

    rel=[]
    for i,r in enumerate(copy.deepcopy(seed.get("relationships",[]))):
        ok,why=relation_gate(r,sm)
        (rel if ok else holds).append(r if ok else {"kind":"relationship","index":i,"reason":why})

    companies=[]
    for i,r in enumerate(copy.deepcopy(seed.get("public_companies_and_organizations",seed.get("companies",[])))):
        ok,why=company_gate(r,sm)
        (companies if ok else holds).append(r if ok else {"kind":"company","index":i,"reason":why})

    p={
      "id":pid,"name":name,"aliases":seed.get("aliases",[]),"path":f"/oameni/{norm(pid).replace(' ','-')}/",
      "publication_status":"public","identity":copy.deepcopy(identity),"profile_types":seed.get("profile_types",["public_personality"]),
      "public_interest_basis":seed.get("public_interest_basis"),"summary":summary(seed),"roles":roles,
      "election_history":elections,"legal_cases":legal,"public_companies_and_organizations":companies,
      "relationships":rel,"story_refs":seed.get("story_refs",[]),"public_sources":list(sm.values()),
      "research_holds":holds,"private_evidence_receipts":receipts(pid,priv),
      "source_discovery":{"status":"QUEUED","oldest_first_backfill":True,"tasks":tasks(seed)},
    }
    p["timeline"]=timeline(p)
    p=overlay(p,rule)
    p["timeline"]=timeline(p)
    return p

def build(policy: dict,seeds: dict,overrides: dict,priv: list[dict]) -> tuple[dict,dict]:
    people=seeds.get("people",[])
    if not isinstance(people,list): raise ValueError("people must be list")
    seen=set(); profiles=[]
    rules=overrides.get("overrides",{})
    for s in people:
        pid=str(s.get("id") or "")
        if pid in seen: raise ValueError(f"duplicate person id {pid}")
        seen.add(pid); profiles.append(profile(s,rules.get(pid,{}),priv))
    profiles.sort(key=lambda p:p["name"].casefold())
    public={
      "schema_version":"1.0","product":"VÂLCEA CLAR People Intelligence","profile_count":len(profiles),"profiles":profiles,
      "policy":{"public_route_root":policy.get("public_route_root","/oameni/"),"ambiguous_identity_fail_closed":True,
                "legal_case_existence_never_implies_guilt":True,"private_evidence_public_projection_forbidden":True,
                "manual_override_applied_last":True,"historical_discovery_enabled":True}
    }
    queue={"schema_version":"1.0","product":"VÂLCEA CLAR People Intelligence Source Discovery Queue","publication_authority":"NONE",
           "profile_count":len(profiles),"tasks":[{"person_id":p["id"],"canonical_name":p["name"],"identity_status":p["identity"]["status"],"tasks":p["source_discovery"]["tasks"]} for p in profiles],
           "policy":{"candidate_source_never_equals_verified_fact":True,"historical_discovery_is_incremental":True,"sensitive_claims_require_dedicated_gate":True}}
    return public,queue

def self_test() -> int:
    src={"name":"Official","url":"https://official.example/p","tier":"T1","source_class":"public_authority"}
    seed={"id":"ana-test","canonical_name":"Ana Test","aliases":[],"profile_types":["politician"],"public_interest_basis":"Test",
          "identity":{"status":"RESOLVED","disambiguators":["Test"]},
          "roles":[{"title":"Primar","organization":"Test","from":"2024","to":None,"status":"current_as_of_source","source_urls":[src["url"]]}],
          "election_history":[],"legal_cases":[],"relationships":[],"public_companies_and_organizations":[],"story_refs":["x"],"public_sources":[src]}
    h=hashlib.sha256(b"private").hexdigest()
    priv=[{"person_id":"ana-test","opaque_evidence_id":"onrc-1","sha256":h,"evidence_class":"ONRC_EXTRACT","verification_state":"REVIEWED_INTERNAL","raw_content":"LEAK","claims":[{"text":"LEAK2"}]}]
    p=profile(seed,{},priv); raw=json.dumps(p)
    assert "LEAK" not in raw and "LEAK2" not in raw and p["private_evidence_receipts"][0]["sha256"]==h

    bad=copy.deepcopy(seed); bad["identity"]["status"]="AMBIGUOUS"
    try: profile(bad,{},[])
    except ValueError: pass
    else: raise AssertionError("ambiguous identity must fail closed")

    sm=source_map(seed)
    assert legal_gate({"role":"DEFENDANT","legal_status":"UNKNOWN","source_urls":[src["url"]]},sm)[0] is False
    prison={"role":"DEFENDANT_CRIMINAL","legal_status":"IMPRISONMENT_SERVED_VERIFIED","final_legal_basis":False,"source_urls":[src["url"]]}
    assert legal_gate(prison,sm)[0] is False
    prison["final_legal_basis"]=True
    assert legal_gate(prison,sm)[0] is True

    p2=profile(seed,{"audit_note":"test","set":{"summary":"manual"},"append":{"profile_types":["manual"]},"suppress":["relationships"]},[])
    assert p2["summary"]=="manual" and "manual" in p2["profile_types"] and "relationships" not in p2
    print("VÂLCEA CLAR People Intelligence self-test: PASS")
    return 0

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--check",action="store_true")
    ap.add_argument("--private-evidence-manifest",default=os.getenv(PRIVATE_ENV))
    a=ap.parse_args()
    if a.self_test: return self_test()
    public,queue=build(load(POLICY),load(SEEDS),load(OVERRIDES),private_records(a.private_evidence_manifest))
    if a.check:
        if public["profile_count"]<1: raise SystemExit("no public profiles")
        raw=json.dumps(public,ensure_ascii=False)
        if "raw_content" in raw: raise SystemExit("private content leak")
        print(json.dumps({"status":"PASS","profiles":public["profile_count"]},ensure_ascii=False)); return 0
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(public,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    QUEUE.write_text(json.dumps(queue,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","profiles":public["profile_count"],"output":str(OUT.relative_to(ROOT))},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
