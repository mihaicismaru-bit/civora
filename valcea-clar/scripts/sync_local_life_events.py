#!/usr/bin/env python3
from __future__ import annotations

import argparse, hashlib, html, json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
TRIGGER = ROOT / "ops" / "live-newsroom-trigger.json"
REGISTRY = ROOT / "editorial" / "local_life_events.json"
RUNTIME = ROOT / "site" / "runtime" / "unde-iesim" / "index.html"
TZ = ZoneInfo("Europe/Bucharest")
ALLOWED_STATUS = {"scheduled","changed","cancelled","sold_out","past","unknown"}

def load(path: Path, default: dict) -> dict:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))

def norm(v) -> str:
    return " ".join(str(v or "").strip().lower().split())

def fingerprint(row: dict) -> str:
    parts=[norm(row.get(k)) for k in ("title","event_start","start_time","venue","locality","organiser")]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]

def identity_key(row: dict) -> str:
    """Stable manifestation identity independent of source/organiser wording.

    The same public event is often discovered from the organiser, a venue and a
    ticketing page with slightly different organiser/category strings. Those are
    corroborating sources, not separate events. Time + place + normalized title
    define the reader-facing manifestation identity; material changes to any of
    those fields remain distinct and must be reconciled explicitly.
    """
    parts=[norm(row.get(k)) for k in ("title","event_start","start_time","venue","locality")]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]

def stable_id(row: dict) -> str:
    raw=str(row.get("event_id") or "").strip()
    if raw:
        return raw
    return "evt-"+identity_key(row)

def validate(row: dict) -> dict:
    required=("title","event_start","venue","locality")
    missing=[k for k in required if not str(row.get(k) or "").strip()]
    if missing:
        raise ValueError("missing_required:"+",".join(missing))
    status=str(row.get("status") or "scheduled").strip().lower()
    if status not in ALLOWED_STATUS:
        raise ValueError("invalid_status:"+status)
    checked=str(row.get("checked_at") or "").strip()
    if not checked:
        raise ValueError("missing_checked_at")
    source_url=str(row.get("source_url") or "").strip()
    source_tier=str(row.get("source_tier") or "").strip()
    if not source_url or not source_tier:
        raise ValueError("missing_source_provenance")
    out={
        "event_id": stable_id(row),
        "fingerprint": fingerprint(row),
        "identity_key": identity_key(row),
        "title": str(row["title"]).strip(),
        "event_start": str(row["event_start"]).strip(),
        "event_end": str(row.get("event_end") or "").strip() or None,
        "start_time": str(row.get("start_time") or "").strip() or None,
        "doors_time": str(row.get("doors_time") or "").strip() or None,
        "venue": str(row["venue"]).strip(),
        "locality": str(row["locality"]).strip(),
        "category": str(row.get("category") or "eveniment").strip(),
        "price": row.get("price","unknown"),
        "free": row.get("free") if isinstance(row.get("free"), bool) else None,
        "ticket_url": str(row.get("ticket_url") or "").strip() or None,
        "reservation_url": str(row.get("reservation_url") or "").strip() or None,
        "organiser": str(row.get("organiser") or "").strip() or None,
        "source_url": source_url,
        "source_tier": source_tier,
        "checked_at": checked,
        "status": status,
    }
    return out

def checked_rank(row: dict) -> tuple:
    tier=str(row.get("source_tier") or "").upper()
    tier_rank=0 if tier.startswith("T1") else 1 if tier.startswith("T2") else 2
    checked=str(row.get("checked_at") or "")
    return (tier_rank, "" if checked is None else checked)

def preferred(a: dict, b: dict) -> dict:
    """Prefer stronger provenance; within same tier prefer fresher verification."""
    ar=checked_rank(a)
    br=checked_rank(b)
    if ar[0] != br[0]:
        return a if ar[0] < br[0] else b
    return a if ar[1] >= br[1] else b

def normalize_existing(row: dict) -> dict:
    out=dict(row)
    out.setdefault("fingerprint", fingerprint(out))
    out["identity_key"]=identity_key(out)
    if not out.get("event_id"):
        out["event_id"]="evt-"+out["identity_key"]
    return out

def merge(registry: dict, deltas: list[dict]) -> tuple[dict,int]:
    existing=[normalize_existing(r) for r in registry.get("events",[]) if isinstance(r,dict)]
    changed=0

    # Collapse historical duplicates before applying new deltas. The same event
    # may previously have been stored once from an organiser and once from a
    # venue/ticketing source because organiser wording affected fingerprinting.
    collapsed={}
    for row in existing:
        key=row["identity_key"]
        if key in collapsed:
            chosen=preferred(collapsed[key], row)
            if chosen != collapsed[key]:
                collapsed[key]=chosen
            changed += 1
        else:
            collapsed[key]=row
    existing=list(collapsed.values())

    for raw in deltas:
        row=validate(raw)
        matches=[r for r in existing if r.get("event_id")==row["event_id"] or r.get("fingerprint")==row["fingerprint"] or r.get("identity_key")==row["identity_key"]]
        old=None
        for candidate in matches:
            old=candidate if old is None else preferred(old,candidate)
        if old is None or old != row:
            changed += 1
        existing=[r for r in existing if r not in matches]
        existing.append(preferred(old,row) if old else row)

    uniq={}
    for row in existing:
        key=row.get("identity_key") or identity_key(row)
        row["identity_key"]=key
        if key in uniq:
            uniq[key]=preferred(uniq[key],row)
            changed += 1
        else:
            uniq[key]=row
    events=sorted(uniq.values(), key=lambda r:(str(r.get("event_start") or ""),str(r.get("start_time") or ""),str(r.get("title") or "")))
    return {
        "schema_version":"1.1",
        "updated_at":datetime.now(TZ).isoformat(timespec="seconds"),
        "events":events,
        "policy":{
            "operator_delta_is_structured":True,
            "dedupe_by_event_id_fingerprint_and_manifestation_identity":True,
            "manifestation_identity_fields":["title","event_start","start_time","venue","locality"],
            "source_wording_does_not_create_duplicate_event":True,
            "prefer_primary_then_fresher_verification":True,
            "unknown_price_never_invented":True,
            "status_requires_provenance":True,
        }
    }, changed

def parse_start(row: dict):
    try:
        d=datetime.fromisoformat(str(row["event_start"]))
        return d.date()
    except Exception:
        return None

def render(doc: dict) -> str:
    today=datetime.now(TZ).date()
    upcoming=[]
    for row in doc.get("events",[]):
        d=parse_start(row)
        if d is None or d < today or row.get("status")=="past":
            continue
        upcoming.append(row)
    cards=[]
    for e in upcoming:
        when=html.escape(str(e.get("event_start")))
        if e.get("start_time"):
            when += " · " + html.escape(str(e["start_time"]))
        price=e.get("price","unknown")
        price_text="Preț necunoscut" if price in (None,"","unknown") else html.escape(str(price))
        badge=str(e.get("status") or "scheduled").upper()
        cards.append(f"""<article class='event'><div class='badge'>{html.escape(badge)}</div><h2>{html.escape(e['title'])}</h2><p><strong>{when}</strong></p><p>{html.escape(e['venue'])} · {html.escape(e['locality'])}</p><p>{price_text}</p><p class='src'><a href='{html.escape(e['source_url'], quote=True)}' rel='nofollow noopener'>Sursă verificată</a> · verificat {html.escape(e['checked_at'])}</p></article>""")
    body="".join(cards) or "<p>Nu există evenimente viitoare verificate în inventarul curent.</p>"
    return f"""<!doctype html><html lang='ro'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Unde ieșim — VÂLCEA CLAR</title><meta name='description' content='Agenda verificată VÂLCEA CLAR pentru evenimente din județul Vâlcea.'><link rel='canonical' href='https://valceaclar.ro/unde-iesim/'><style>body{{font:16px/1.5 system-ui;margin:0;color:#101828}}main{{max-width:980px;margin:auto;padding:28px}}.event{{border-top:1px solid #ddd;padding:18px 0}}h1{{font:700 42px Georgia,serif}}h2{{font:700 26px Georgia,serif;margin:6px 0}}.badge{{font-size:12px;font-weight:800;color:#b42318}}.src{{font-size:12px;color:#667085}}</style></head><body><main><p><a href='/'>← Acasă</a></p><h1>Unde ieșim</h1><p>Inventar editorial verificat. Datele, prețurile și statusul sunt afișate numai când există dovadă; necunoscutele rămân necunoscute.</p>{body}</main></body></html>"""

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    args=ap.parse_args()
    if args.self_test:
        base={"events":[]}
        row={"title":"Test","event_start":"2026-09-24","start_time":"19:00","venue":"Casa","locality":"Drăgășani","category":"teatru","price":"unknown","organiser":"Org A","source_url":"https://example.test/e","source_tier":"T2","checked_at":"2026-09-23T17:00:00+03:00","status":"scheduled"}
        out,c=merge(base,[row])
        assert c==1 and len(out["events"])==1
        out2,c2=merge(out,[row])
        assert c2==0 and len(out2["events"])==1
        corroborating={**row,"event_id":"different-id","organiser":"Org B","source_url":"https://official.test/e","source_tier":"T1","checked_at":"2026-09-23T18:00:00+03:00"}
        out3,c3=merge(out2,[corroborating])
        assert c3>=1 and len(out3["events"])==1
        assert out3["events"][0]["source_url"]=="https://official.test/e"
        bad=dict(row); bad.pop("source_url")
        try:
            validate(bad)
            raise AssertionError("missing source must fail")
        except ValueError:
            pass
        print("Local Life event sync self-test: PASS")
        return 0
    trigger=load(TRIGGER,{})
    deltas=trigger.get("event_deltas") or []
    if not isinstance(deltas,list):
        raise SystemExit("event_deltas must be a list")
    registry=load(REGISTRY,{"events":[]})
    merged,changed=merge(registry,deltas)
    REGISTRY.parent.mkdir(parents=True,exist_ok=True)
    REGISTRY.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    RUNTIME.parent.mkdir(parents=True,exist_ok=True)
    RUNTIME.write_text(render(merged),encoding="utf-8")
    print(json.dumps({"status":"UPDATED" if changed else "NO_CHANGE","event_deltas":len(deltas),"changed":changed,"event_count":len(merged["events"])},ensure_ascii=False))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
