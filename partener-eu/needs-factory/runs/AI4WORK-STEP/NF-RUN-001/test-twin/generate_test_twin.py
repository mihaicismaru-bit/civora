#!/usr/bin/env python3
"""Generate synthetic AI4WORK TEST-TWIN-001 data. NON-EVIDENCE ONLY."""
import csv, random, hashlib, json
from pathlib import Path

SEED = 367944
random.seed(SEED)
OUT = Path(__file__).parent
regions=["Sud-Vest Oltenia","Sud-Muntenia","Centru"]
statuses=["șomer înregistrat","persoană ocupată potențial eligibilă"]
ages=["30-39","40-49","50-59","60+"]
jobs=["administrativ","producție/tehnic","servicii clienți","vânzări/marketing","logistică","financiar-contabil","IT/digital"]
barriers=["costul","lipsa timpului","program incompatibil","lipsa unei oferte relevante","distanța/deplasarea","lipsa informației","lipsa sprijinului angajatorului","nu am considerat necesar"]
problems=["rezultate factual greșite","rezultate greu de verificat","probleme privind datele/confidențialitatea","nu am știut cum să formulez cererea","integrare dificilă în aplicațiile/procesele folosite","nu am putut evalua calitatea rezultatului","nu am întâlnit probleme","nu am folosit AI"]
outcomes=["adaptare mai bună la postul actual","acces la un loc de muncă nou","schimbare de ocupație","productivitate/calitate mai bună"]
base_skill={"Sud-Vest Oltenia":2.25,"Sud-Muntenia":2.55,"Centru":2.85}
base_aiuse={"Sud-Vest Oltenia":1.0,"Sud-Muntenia":1.3,"Centru":1.6}

def likert(mu):
    return max(1,min(5,round(random.gauss(mu,0.85))))

def write_csv(path, rows):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    return hashlib.sha256(path.read_bytes()).hexdigest()

adults=[]
for ri,region in enumerate(regions):
    for i in range(80):
        rid=f"TTA-{ri+1}-{i+1:03d}"
        status=random.choices(statuses,weights=[0.55,0.45])[0]
        age=random.choices(ages,weights=[0.25,0.32,0.28,0.15])[0]
        job=random.choice(jobs)
        q01=likert(base_skill[region] + (0.25 if status.startswith("persoană") else -0.1))
        q02=max(0,min(4,round(random.gauss(base_aiuse[region],1.0))))
        q03=likert(base_skill[region]-0.25 + q02*0.15)
        q04=likert(base_skill[region]-0.35 + q02*0.08)
        q05=likert(base_skill[region]-0.2)
        q06=likert(base_skill[region]-0.3 + q02*0.1)
        q07="da" if random.random() < {"Sud-Vest Oltenia":0.22,"Sud-Muntenia":0.32,"Centru":0.38}[region] else "nu"
        selected=random.sample(barriers,k=random.choice([1,2,3]))
        if q07=="da" and random.random()<0.35:
            selected=[b for b in selected if b!="nu am considerat necesar"] or ["lipsa timpului"]
        selected_problems=["nu am folosit AI"] if q02==0 else random.sample(problems[:-2],k=random.choice([1,2,3]))
        needs=[likert(5.2-q01),likert(5.1-(q03+q02/4)/1.2),likert(5.2-q04),likert(5.0-q05),likert(5.2-q06)]
        adults.append({
            "respondent_id":rid,"region":region,"status":status,"age_band":age,"job_family":job,
            "Q01":q01,"Q02":q02,"Q03":q03,"Q04":q04,"Q05":q05,"Q06":q06,"Q07":q07,
            "Q08":"|".join(selected),"Q09":"|".join(selected_problems),"Q10_digital":needs[0],"Q10_AI":needs[1],
            "Q10_verification":needs[2],"Q10_privacy":needs[3],"Q10_workflow":needs[4],"Q11":random.choice(outcomes),
            "Q12":"TEST_TWIN_NON_EVIDENCE"})

sectors=["manufacturing","professional services","retail/wholesale","transport/logistics","hospitality","construction","ICT"]
sizes=["1-9","10-49","50-249","250+"]
roles=["management","HR","operațional/tehnic"]
use_states=["da, în producție/activitate curentă","pilot/test","intenție în următoarele 12 luni","nu"]
areas=["redactare/comunicare","analiză date","suport clienți","marketing/vânzări","operațiuni/producție","HR","documente/compliance","automatizare fluxuri"]
emp=[]
for ri,region in enumerate(regions):
    for i in range(30):
        oid=f"TTE-{ri+1}-{i+1:03d}"
        sector=random.choice(sectors); size=random.choices(sizes,weights=[.25,.4,.27,.08])[0]; role=random.choice(roles)
        e01=random.choices(use_states,weights={"Sud-Vest Oltenia":[.12,.24,.33,.31],"Sud-Muntenia":[.16,.27,.34,.23],"Centru":[.23,.30,.30,.17]}[region])[0]
        e02="|".join(random.sample(areas,k=random.choice([1,2,3]))) if e01!="nu" else ""
        sb={"Sud-Vest Oltenia":3.8,"Sud-Muntenia":3.55,"Centru":3.25}[region]
        el=lambda mu:max(1,min(5,round(random.gauss(mu,.75))))
        vals=[el(sb),el(sb+.15),el(sb+.1),el(sb),el(sb+.2),el(sb+.15),el(sb-.15)]
        e04="da" if random.random() < {"Sud-Vest Oltenia":.62,"Sud-Muntenia":.56,"Centru":.48}[region] else "nu"
        e05=random.choices(["da, intern","da, extern","ambele","nu"],weights=[.18,.24,.13,.45])[0]
        eb=["cost","timp disponibil","lipsa furnizorilor/ofertei potrivite","conținut prea general","schimbare tehnologică rapidă","dificultate de măsurare a rezultatelor","lipsa unei politici clare privind AI"]
        caps=["formularea și rafinarea instrucțiunilor","verificarea factuală/calității","analiză și interpretare de date","protecția datelor","securitate digitală","automatizarea unor pași de lucru","integrarea AI în aplicații/procese","documentarea și trasabilitatea rezultatelor","supraveghere umană/decizie"]
        emp.append({"organisation_id":oid,"region":region,"sector":sector,"size":size,"respondent_type":role,"E01":e01,"E02":e02,
                    "E03_prompt":vals[0],"E03_verification":vals[1],"E03_privacy":vals[2],"E03_limits":vals[3],"E03_integration":vals[4],
                    "E03_workflow":vals[5],"E03_general_digital":vals[6],"E04":e04,"E05":e05,
                    "E06":"|".join(random.sample(eb,k=random.choice([1,2,3]))),
                    "E07":random.choices(["semnificativ","moderat","puțin","deloc","nu putem estima"],weights=[.25,.4,.2,.06,.09])[0],
                    "E08":"|".join(random.sample(caps,k=5)),"E09":"TEST_TWIN_NON_EVIDENCE","E10":random.choices(["da","posibil","nu"],weights=[.38,.43,.19])[0]})

adult_sha=write_csv(OUT/"adults_synthetic_NON_EVIDENCE.csv",adults)
employer_sha=write_csv(OUT/"employers_synthetic_NON_EVIDENCE.csv",emp)
(OUT/"generated_hashes.json").write_text(json.dumps({"classification":"SYNTHETIC_NON_EVIDENCE","seed":SEED,"adult_sha256":adult_sha,"employer_sha256":employer_sha},indent=2),encoding="utf-8")
print(json.dumps({"adult_rows":len(adults),"employer_rows":len(emp),"adult_sha256":adult_sha,"employer_sha256":employer_sha},indent=2))
