#!/usr/bin/env python3
from __future__ import annotations

import html
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
REGISTRY=ROOT/"editorial"/"local_life_events.json"
RUNTIME=ROOT/"site"/"runtime"/"unde-iesim"/"index.html"
TZ=ZoneInfo("Europe/Bucharest")


def norm(v) -> str:
    s=str(v or "").lower().strip()
    s=re.sub(r"[^0-9a-zăâîșț]+"," ",s)
    return " ".join(s.split())


def venue_equivalent(a,b) -> bool:
    na,nb=norm(a),norm(b)
    if not na or not nb:
        return na==nb
    return na==nb or na in nb or nb in na


def base_key(r:dict):
    return tuple(norm(r.get(k)) for k in ("title","event_start","start_time","locality"))


def rank(r:dict):
    tier=str(r.get("source_tier") or "").upper()
    tr=0 if tier.startswith("T1") else 1 if tier.startswith("T2") else 2
    return (tr, str(r.get("checked_at") or ""))


def preferred(a:dict,b:dict)->dict:
    ra,rb=rank(a),rank(b)
    if ra[0]!=rb[0]:
        return a if ra[0]<rb[0] else b
    return a if ra[1]>=rb[1] else b


def merge_cluster(rows:list[dict])->dict:
    chosen=rows[0]
    for row in rows[1:]:
        chosen=preferred(chosen,row)
    out=dict(chosen)
    sources=[]
    for row in rows:
        src={"url":row.get("source_url"),"tier":row.get("source_tier"),"checked_at":row.get("checked_at")}
        if src["url"] and src not in sources:
            sources.append(src)
    if len(sources)>1:
        out["corroborating_sources"]=sources
    return out


def dedupe(events:list[dict])->tuple[list[dict],int]:
    groups={}
    for row in events:
        groups.setdefault(base_key(row),[]).append(row)
    out=[]; removed=0
    for rows in groups.values():
        clusters=[]
        for row in rows:
            for cluster in clusters:
                if venue_equivalent(cluster[0].get("venue"),row.get("venue")):
                    cluster.append(row)
                    break
            else:
                clusters.append([row])
        for cluster in clusters:
            out.append(merge_cluster(cluster))
            removed += len(cluster)-1
    out.sort(key=lambda r:(str(r.get("event_start") or ""),str(r.get("start_time") or ""),str(r.get("title") or "")))
    return out,removed


def render(events:list[dict])->str:
    today=datetime.now(TZ).date().isoformat()
    cards=[]
    for e in events:
        if str(e.get("event_start") or "") < today or e.get("status")=="past":
            continue
        when=html.escape(str(e.get("event_start") or ""))
        if e.get("start_time"):
            when += " · "+html.escape(str(e.get("start_time")))
        price=e.get("price","unknown")
        price_text="Preț necunoscut" if price in (None,"","unknown") else html.escape(str(price))
        src=html.escape(str(e.get("source_url") or ""),quote=True)
        cards.append(f"<article class='event'><div class='badge'>{html.escape(str(e.get('status') or 'scheduled').upper())}</div><h2>{html.escape(str(e.get('title') or ''))}</h2><p><strong>{when}</strong></p><p>{html.escape(str(e.get('venue') or ''))} · {html.escape(str(e.get('locality') or ''))}</p><p>{price_text}</p><p class='src'><a href='{src}' rel='nofollow noopener'>Sursă verificată</a> · verificat {html.escape(str(e.get('checked_at') or ''))}</p></article>")
    body="".join(cards) or "<p>Nu există evenimente viitoare verificate în inventarul curent.</p>"
    return f"<!doctype html><html lang='ro'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Unde ieșim — VÂLCEA CLAR</title><meta name='description' content='Agenda verificată VÂLCEA CLAR pentru evenimente din județul Vâlcea.'><link rel='canonical' href='https://valceaclar.ro/unde-iesim/'><style>body{{font:16px/1.5 system-ui;margin:0;color:#101828}}main{{max-width:980px;margin:auto;padding:28px}}.event{{border-top:1px solid #ddd;padding:18px 0}}h1{{font:700 42px Georgia,serif}}h2{{font:700 26px Georgia,serif;margin:6px 0}}.badge{{font-size:12px;font-weight:800;color:#b42318}}.src{{font-size:12px;color:#667085}}</style></head><body><main><p><a href='/'>← Acasă</a></p><h1>Unde ieșim</h1><p>Inventar editorial verificat. Aceeași manifestare descoperită în mai multe surse este afișată o singură dată.</p>{body}</main></body></html>"


def main()->int:
    doc=json.loads(REGISTRY.read_text(encoding="utf-8"))
    events,removed=dedupe([x for x in doc.get("events",[]) if isinstance(x,dict)])
    doc["events"]=events
    doc["updated_at"]=datetime.now(TZ).isoformat(timespec="seconds")
    doc.setdefault("policy",{})["projection_dedupe_venue_equivalence"]=True
    REGISTRY.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    RUNTIME.parent.mkdir(parents=True,exist_ok=True)
    RUNTIME.write_text(render(events),encoding="utf-8")
    print(json.dumps({"status":"UPDATED","deduplicated":removed,"event_count":len(events)},ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
