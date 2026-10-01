#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, json, re
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[2]
PRODUCTS=ROOT/"partener-eu/ingest/state/decision_products.json"
OUT_JS=ROOT/"partener-eu/web/decision-products.js"
EVIDENCE=ROOT/"partener-eu/ingest/state/afir_energy_public_open_evidence.json"
URL="https://www.afir.ro/comunicate/depunere-in-curs-a-proiectelor-in-energie-a-entitatilor-publice/"
TARGETS={"afir-fm-public-autoconsum-2026","afir-fm-public-storage-2026"}
RO=ZoneInfo("Europe/Bucharest")
OPEN_AT=dt.datetime(2026,9,28,10,0,tzinfo=RO)
CLOSE_AT=dt.datetime(2026,11,20,23,59,tzinfo=RO)
MAX_AGE=dt.timedelta(hours=4)

def ts(v):
    if not v:return None
    v=str(v).replace("Z","+00:00")
    try:x=dt.datetime.fromisoformat(v)
    except ValueError:return None
    if x.tzinfo is None:x=x.replace(tzinfo=dt.timezone.utc)
    return x.astimezone(dt.timezone.utc)

def status(ev,now):
    local=now.astimezone(RO)
    if local<OPEN_AT:return "UPCOMING"
    if local>CLOSE_AT:return "REVIEW"
    observed=ts(ev.get("observedAt"))
    fresh=bool(observed and dt.timedelta(0)<=now-observed<=MAX_AGE)
    valid=ev.get("status")=="PASS" and ev.get("sourceUrl")==URL and ev.get("semanticCheck")=="PASS" and re.fullmatch(r"[0-9a-f]{64}",str(ev.get("sha256") or ""))
    return "OPEN" if fresh and valid else "REVIEW"

def set_fact(d,label,value,confidence):
    for row in d.get("quickFacts") or []:
        if row.get("label")==label:
            row.update(value=value,confidence=confidence);return

def set_section(d,title,items):
    for row in d.get("sections") or []:
        if row.get("title")==title:
            row["items"]=items;row["empty"]=False;return

def main():
    now=dt.datetime.now(dt.timezone.utc)
    ev=json.loads(EVIDENCE.read_text(encoding="utf-8")) if EVIDENCE.exists() else {}
    wanted=status(ev,now)
    data=json.loads(PRODUCTS.read_text(encoding="utf-8"))
    found=set()
    for d in data.get("dossiers") or []:
        if d.get("id") not in TARGETS:continue
        found.add(d["id"]); opened=wanted=="OPEN"
        label={"OPEN":"DESCHIS","UPCOMING":"ÎN PREGĂTIRE","REVIEW":"ÎN VERIFICARE"}[wanted]
        d["status"]=wanted;d["statusLabel"]=label
        d["decision"]="APLICĂ" if opened else ("PREGĂTEȘTE" if wanted=="UPCOMING" else "VERIFY")
        d["decisionLabel"]="APLICĂ" if opened else ("PREGĂTEȘTE" if wanted=="UPCOMING" else "VERIFICĂ STAREA")
        d["decisionAction"]="Sesiunea este în derulare în sistemul AFIR. Folosește formularul curent și depune înainte de 20 noiembrie 2026, ora 23:59." if opened else "Nu presupune că apelul este OPEN fără dovadă AFIR post-lansare curentă."
        set_fact(d,"Status",label,"CONFIRMED" if opened else "FAIL_CLOSED")
        set_fact(d,"Deschidere","28 septembrie 2026, 10:00 — confirmată post-lansare de AFIR" if opened else "28 septembrie 2026, 10:00 — necesită dovadă post-lansare curentă","CONFIRMED" if opened else "FAIL_CLOSED")
        ex=d.setdefault("executiveSummary",{});ex["status"]=wanted;ex["opens"]="2026-09-28T10:00:00+03:00 — confirmat post-lansare de AFIR" if opened else "2026-09-28T10:00:00+03:00 — necesită dovadă curentă";ex["closes"]="2026-11-20T23:59:00+02:00"
        set_section(d,"Rezumat executiv",[f"Stare apel: {label}.","Deschidere: 28 septembrie 2026, ora 10:00 — confirmată explicit de AFIR post-lansare." if opened else "Deschidere: 28 septembrie 2026, ora 10:00 — necesită dovadă post-lansare curentă.","Închidere: 20 noiembrie 2026, ora 23:59, conform AFIR.","Cine poate aplica: "+"; ".join(d.get("audience") or []),"Activități finanțate: "+"; ".join(ex.get("activities") or []),"Valoarea apelului: "+str(ex.get("callBudget") or "Neconfirmat")+".","Valoarea proiectului individual: "+str(ex.get("projectValue") or "Neconfirmat")+".","Cofinanțare / contribuție proprie: "+str(ex.get("cofinancing") or "Neconfirmat")+".","Regiune: România."])
        set_section(d,"Decizia rapidă",[d["decisionAction"],"Calendarul singur nu poate promova apelul la OPEN."])
        q=d.setdefault("quality",{});verified=set(q.get("verifiedFactClasses") or []);blocked=set(q.get("blockedFactClasses") or [])
        if opened:verified.add("status");blocked.discard("open_status");q["dossierLevel"]="DOSAR DESCHIS"
        else:blocked.add("open_status")
        q["verifiedFactClasses"]=sorted(verified);q["blockedFactClasses"]=sorted(blocked);q["failClosed"]=True;q["afirEnergyOpenEvidence"]={k:ev.get(k) for k in ("status","sourceUrl","observedAt","sha256","fetchedAt","parserVersion")}
        sources=[s for s in d.get("sources") or [] if str(s.get("url") or "").rstrip("/")!=URL.rstrip("/")]
        if ev.get("semanticCheck")=="PASS" and ev.get("sha256") and ev.get("observedAt"):
            sources.append({"label":"AFIR — depunere în curs proiecte energie entități publice","url":URL,"tier":"T1","observedAt":ev["observedAt"],"fetchedAt":ev.get("fetchedAt",ev["observedAt"]),"sha256":ev["sha256"],"parserVersion":ev.get("parserVersion","afir-energy-open/1.0"),"supports":["status","opening","deadline","budget"]})
        d["sources"]=sources;d["canonicalLinks"]=list(dict.fromkeys(s.get("url") for s in sources if s.get("url")));d["updatedAt"]=ev.get("observedAt") or now.isoformat()
    if found!=TARGETS:raise SystemExit("missing AFIR energy dossiers")
    data.setdefault("policy",{})["afirEnergyOpenRequiresFreshPostLaunchEvidence"]=True
    PRODUCTS.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS="+json.dumps(data,ensure_ascii=False,separators=(",",":"))+";\n",encoding="utf-8")
    print(json.dumps({"status":"PASS","energyStatus":wanted},ensure_ascii=False))
if __name__=="__main__":main()
