#!/usr/bin/env python3
from __future__ import annotations
import datetime as dt, hashlib, html as h, json, re, ssl, urllib.parse, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PRODUCTS=ROOT/"partener-eu"/"ingest"/"state"/"decision_products.json"
OUT_JS=ROOT/"partener-eu"/"web"/"decision-products.js"
URL="https://regionordvest.ro/prioritati-de-finantare/prioritatea-de-finantare-9/"
GUIDE="https://regionordvest.ro/961-sprijinirea-proiectelor-cu-aplicabilitate-in-domeniile-step-din-regiunea-de-dezvoltare-nord-vest/"
CODE="PRNV/2026/961/1"; DID="prnv-2026-961-1-step"; VER="PRNV_STEP_961_SOURCE_BOUND_V1"
RO=dt.timezone(dt.timedelta(hours=3))
OPEN=dt.datetime(2026,8,28,10,0,tzinfo=RO); CLOSE=dt.datetime(2026,10,12,10,0,tzinfo=RO)

def utcnow(): return dt.datetime.now(dt.timezone.utc)
def iso(x): return x.astimezone(dt.timezone.utc).isoformat().replace("+00:00","Z")
def strip_html(s):
    s=re.sub(r"(?is)<script\\b.*?</script>|<style\\b.*?</style>"," ",s)
    s=re.sub(r"(?s)<[^>]+>"," ",s)
    return re.sub(r"\\s+"," ",h.unescape(s)).strip()
def fold(s):
    import unicodedata
    s="".join(c for c in unicodedata.normalize("NFKD",str(s or "")) if not unicodedata.combining(c)).lower()
    return re.sub(r"\\s+"," ",s).strip()
def markers(text):
    f=fold(text)
    need={
      "call_code":fold(CODE),
      "status_window":fold("Apel deschis în perioada 28.08.2026, ora 10:00 - 12.10.2026, ora 10:00"),
      "allocation":fold("Alocarea financiară (FEDR): 20.950.000,00 EUR"),
      "action":fold("Sprijin pentru dezvoltarea de tehnologii strategice pentru Europa – STEP"),
    }
    missing=[k for k,v in need.items() if v not in f]
    return not missing,missing
def fetch():
    p=urllib.parse.urlparse(URL)
    if p.scheme!="https" or p.hostname!="regionordvest.ro": raise RuntimeError("canonical URL drift")
    req=urllib.request.Request(URL,headers={"User-Agent":"PARTENER.EU-CIVORA-PRNV-STEP/1.0 (+https://partener.eu)","Accept":"text/html"})
    with urllib.request.urlopen(req,timeout=25,context=ssl.create_default_context()) as r:
        raw=r.read(2000001)
        if len(raw)>2000000: raise RuntimeError("source too large")
        if "html" not in str(r.headers.get("Content-Type") or "").lower(): raise RuntimeError("unexpected content type")
    return raw.decode("utf-8",errors="replace"),hashlib.sha256(raw).hexdigest()
def sec(title,items,**extra): return {"title":title,"items":items,"empty":False,**extra}
def build(clock,ok,rawsha,semsha,missing):
    current=OPEN.astimezone(dt.timezone.utc)<=clock<=CLOSE.astimezone(dt.timezone.utc)
    live=bool(ok and current); status="OPEN" if live else "REVIEW"
    who="Neconfirmat în pagina-sinteză oficială; categoriile eligibile se verifică exclusiv în Ghidul Solicitantului 961."
    action="Sprijin pentru dezvoltarea de tehnologii strategice pentru Europa – STEP."
    decide=("Verifică eligibilitatea în Ghidul 961 și pregătește depunerea înainte de 12 octombrie 2026, ora 10:00."
            if live else "Reverifică pagina oficială ADR Nord-Vest și Ghidul 961 înainte de orice decizie de depunere.")
    summary=[
      f"Stare apel: {'OPEN' if live else 'ÎN VERIFICARE'}.",
      "Deschidere: 28 august 2026, ora 10:00.","Închidere: 12 octombrie 2026, ora 10:00.",
      f"Cine poate aplica: {who}",f"Activități finanțate: {action}",
      "Valoarea apelului: 20.950.000 EUR alocare FEDR.",
      "Valoarea proiectului individual: Neconfirmat în pagina-sinteză oficială.",
      "Cofinanțare / contribuție proprie: Neconfirmat în pagina-sinteză oficială.","Regiune: Nord-Vest."]
    src=[{"label":"ADR Nord-Vest — Prioritatea 9 STEP","url":URL,"tier":"T1","observedAt":iso(clock),"rawSha256":rawsha or None,"semanticSha256":semsha or None,"parserVersion":VER,"supports":["status","opening","deadline","budget","activities"]},
         {"label":"ADR Nord-Vest — Ghidul Solicitantului 961","url":GUIDE,"tier":"T1","observedAt":iso(clock),"parserVersion":VER,"supports":["documents"]}]
    verified=["opening","deadline","budget","activities"]+(["status"] if ok else [])
    blocked=["beneficiaries","eligibility","grant","cofinancing","scoring"]+([] if ok else ["status"])
    return {
      "id":DID,"sourceType":"ADR_NORD_VEST_CANONICAL","title":"PRNV/2026/961/1 — Sprijin pentru dezvoltarea de tehnologii strategice pentru Europa – STEP",
      "slug":DID,"programme":"Program Regional Nord-Vest 2021-2027","code":CODE,"region":"Regiunea Nord-Vest",
      "status":status,"statusLabel":"DESCHIS" if live else "ÎN VERIFICARE","decision":"APLICĂ" if live else "VERIFICĂ",
      "decisionLabel":"APLICĂ" if live else "VERIFICĂ STAREA","decisionAction":decide,"publicationState":"PUBLISHABLE",
      "standfirst":("ADR Nord-Vest confirmă apelul STEP PRNV/2026/961/1 deschis până la 12 octombrie 2026, ora 10:00, cu alocare FEDR de 20,95 milioane EUR."
                    if live else "Apelul STEP PRNV/2026/961/1 este păstrat fail-closed în verificare până la o reconciliere oficială curentă."),
      "audience":[],"quickFacts":[
        {"label":"Status","value":"DESCHIS" if live else "ÎN VERIFICARE","confidence":"CONFIRMED" if live else "FAIL_CLOSED"},
        {"label":"Deschidere","value":"28 august 2026, 10:00","confidence":"CONFIRMED"},
        {"label":"Termen","value":"12 octombrie 2026, 10:00","confidence":"CONFIRMED"},
        {"label":"Buget","value":"20.950.000 EUR — alocare FEDR","confidence":"CONFIRMED"},
        {"label":"Grant","value":"Neconfirmat în pagina-sinteză oficială","confidence":"UNKNOWN"},
        {"label":"Completitudine critică","value":"61%","confidence":"SYSTEM"}],
      "sections":[
        sec("Rezumat executiv",summary,schemaVersion=1),sec("Decizia rapidă",[decide]),sec("Cine poate aplica",[who],policy="GUIDE_EXPLICIT_ONLY"),
        sec("Condiții esențiale de eligibilitate",["Neconfirmat în pagina-sinteză; verifică Ghidul 961 și Corrigendum nr. 1 din 27 august 2026."]),
        sec("Ce finanțează și în ce condiții",[action]),sec("Costuri, cofinanțare și ajutor de stat",["Alocarea FEDR confirmată este 20.950.000 EUR.","Grantul individual și contribuția proprie se verifică în Ghidul 961."]),
        sec("Documente de pregătit",["Ghidul 961 actualizat prin Corrigendum nr. 1 și anexele editabile publicate de ADR Nord-Vest."]),
        sec("Cum se punctează",["Neconfirmat în pagina-sinteză; verifică grila oficială."]),sec("Indicatori și obligații",["Neconfirmat în pagina-sinteză; verifică documentația oficială."]),
        sec("Riscuri de respingere sau implementare",["Folosirea unei versiuni anterioare Corrigendumului nr. 1.","Presupunerea eligibilității ori cofinanțării din surse secundare."]),
        sec("Ce trebuie făcut acum",[decide,"Descarcă forma curentă a Ghidului 961 și anexele editabile."]),
        sec("Ce nu este confirmat",[f"Beneficiarii, grantul individual, cofinanțarea și punctajul nu sunt promovate. Markeri nereconciliați: {', '.join(missing) if missing else 'niciunul'}." ])],
      "timeline":[{"date":"2026-08-27","kind":"CORRIGENDUM","text":"Corrigendum nr. 1 pentru Ghidul 961."},{"date":"2026-08-28T10:00:00+03:00","kind":"OPENED","text":"Deschiderea oficială."},{"date":"2026-10-12T10:00:00+03:00","kind":"DEADLINE","text":"Termenul oficial ADR Nord-Vest."}],
      "sources":src,"quality":{"completeness":61,"depthCompleteness":61,"dossierLevel":"DOSAR ÎN CONSTRUCȚIE","verifiedFactClasses":verified,"blockedFactClasses":blocked,
        "evidenceCount":len(src),"failClosed":True,"applicantListPolicy":"GUIDE_EXPLICIT_ONLY","applicantEvidenceAuthorized":False,"executiveSummaryPresent":True,"requiresMaterialFactReconciliation":not ok},
      "updatedAt":iso(clock),"canonicalLinks":[URL,GUIDE],
      "executiveSummary":{"status":status,"opens":"2026-08-28T10:00:00+03:00","closes":"2026-10-12T10:00:00+03:00","applicants":[],"targetGroup":[],"activities":[action],"callBudget":"20.950.000 EUR FEDR","projectValue":"Neconfirmat","cofinancing":"Neconfirmat","region":"Regiunea Nord-Vest","sourcePolicy":"GUIDE_EXPLICIT_ONLY","sourceBound":True},
      "dossierConstruction":{"autonomous":True,"depthCompleteness":61,"level":"DOSAR ÎN CONSTRUCȚIE","missing":blocked,"nextPass":"ENRICH_FROM_GUIDE_961"}}
def apply(payload,dossier):
    payload["dossiers"]=[dossier]+[x for x in payload.get("dossiers") or [] if str(x.get("id") or "")!=DID and str(x.get("code") or "")!=CODE]
    payload.setdefault("policy",{})["prnvStep961SourceBoundCoverage"]=True
    q=payload.setdefault("qualityPass",{}); q["prnvStep961CanonicalDossier"]=DID; q["executiveSummaryCoverage"]=len(payload["dossiers"]); q["strictApplicantListCoverage"]=len(payload["dossiers"])
def self_test():
    fixture="<p>Sprijin pentru dezvoltarea de tehnologii strategice pentru Europa – STEP</p><p>PRNV/2026/961/1</p><p>Apel deschis în perioada 28.08.2026, ora 10:00 - 12.10.2026, ora 10:00</p><p>Alocarea financiară (FEDR): 20.950.000,00 EUR</p>"
    text=strip_html(fixture); ok,missing=markers(text); assert ok and not missing
    clock=dt.datetime(2026,9,24,16,30,tzinfo=dt.timezone.utc); sem=hashlib.sha256(fold(text).encode()).hexdigest()
    d=build(clock,True,"a"*64,sem,[]); assert d["status"]=="OPEN" and d["audience"]==[] and "status" in d["quality"]["verifiedFactClasses"]
    ok2,mis2=markers(text.replace("12.10.2026","13.10.2026")); assert not ok2 and "status_window" in mis2; assert build(clock,False,"b"*64,sem,mis2)["status"]=="REVIEW"
    assert build(dt.datetime(2026,10,12,8,1,tzinfo=dt.timezone.utc),True,"c"*64,sem,[])["status"]=="REVIEW"
    print("PASS PRNV STEP 961 source-bound lifecycle regression")
def main():
    import argparse
    ap=argparse.ArgumentParser(); ap.add_argument("--self-test",action="store_true"); a=ap.parse_args()
    if a.self_test: self_test(); return 0
    clock=utcnow(); rawsha=sem=""; missing=["source_unavailable"]; ok=False
    try:
        raw,rawsha=fetch(); text=strip_html(raw); sem=hashlib.sha256(fold(text).encode()).hexdigest(); ok,missing=markers(text)
    except Exception as e: missing=[f"transport:{type(e).__name__}"]
    payload=json.loads(PRODUCTS.read_text(encoding="utf-8")); d=build(clock,ok,rawsha,sem,missing); apply(payload,d)
    PRODUCTS.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\\n",encoding="utf-8")
    OUT_JS.write_text("window.PARTENER_DECISION_PRODUCTS="+json.dumps(payload,ensure_ascii=False,separators=(",",":"))+";\\n",encoding="utf-8")
    print(json.dumps({"ok":ok,"dossier":DID,"status":d["status"],"observedAt":d["updatedAt"],"rawSha256":rawsha or None,"semanticSha256":sem or None,"missingMarkers":missing,"publishAuthorized":d["status"]=="OPEN"},ensure_ascii=False)); return 0
if __name__=="__main__": raise SystemExit(main())
