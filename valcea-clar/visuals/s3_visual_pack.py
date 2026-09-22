#!/usr/bin/env python3
"""S3 deterministic editorial visual pack for VÂLCEA CLAR.

Creates original newsroom graphics from already verified story text. These are
editorial layouts, not photographs and not synthetic depictions of real scenes.
They are social-distribution products only (Facebook/Instagram/OpenGraph where
the channel pack calls for a card) and MUST NOT be projected as visible site
article/homepage media. TikTok remains fail-closed unless current subject media
is independently available.
"""
from __future__ import annotations
import argparse, hashlib, json, textwrap
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
BRIEFS=ROOT/"visuals"/"s3_visual_briefs.json"
CURRENT=ROOT/"site"/"current_edition.json"
OUT=ROOT/"site"/"runtime"/"media"/"social"/"editorial"/"s3"
MANIFEST=ROOT/"visuals"/"s3_visual_manifest.json"
PUBLIC_BASE="https://valceaclar.ro/media/social/editorial/s3/"

def load(path: Path)->dict[str,Any]:
    value=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value,dict): raise ValueError(f"{path} must contain object")
    return value

def sha256(path: Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024),b""): h.update(block)
    return h.hexdigest()

def digest(value: Any)->str:
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")).hexdigest()

def font(size:int,bold:bool=False):
    candidates=[
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate,size=size)
    return ImageFont.load_default()

def wrap(draw:ImageDraw.ImageDraw,text:str,font_obj,max_width:int)->list[str]:
    words=" ".join(str(text or "").split()).split()
    lines=[]; current=[]
    for word in words:
        trial=" ".join(current+[word])
        if draw.textlength(trial,font=font_obj)<=max_width or not current:
            current.append(word)
        else:
            lines.append(" ".join(current)); current=[word]
    if current: lines.append(" ".join(current))
    return lines

def story_index()->dict[str,dict[str,Any]]:
    pointer=load(CURRENT)
    edition=load(ROOT/str(pointer["json_source"]))
    return {str(x.get("id")):x for x in edition.get("items",[]) if isinstance(x,dict) and x.get("id")}

def render_card(story:dict[str,Any],brief:dict[str,Any],size:tuple[int,int],suffix:str)->dict[str,Any]:
    w,h=size
    bg=(247,247,244); ink=(20,27,38); accent=(155,32,38); muted=(92,100,112)
    image=Image.new("RGB",size,bg); draw=ImageDraw.Draw(image)
    margin=max(48,int(w*0.055))
    kicker=font(max(22,int(w*0.025)),True)
    headline_font=font(max(42,int(w*0.052)),True)
    body_font=font(max(24,int(w*0.026)),False)
    small=font(max(18,int(w*0.019)),True)
    draw.rectangle((0,0,w,max(16,int(h*0.025))),fill=accent)
    draw.text((margin,margin),str(brief.get("label") or story.get("section") or "ȘTIRI"),font=kicker,fill=accent)
    y=margin+max(46,int(h*0.08))
    maxw=w-2*margin
    lines=wrap(draw,str(story.get("headline") or ""),headline_font,maxw)
    for line in lines[:5]:
        draw.text((margin,y),line,font=headline_font,fill=ink)
        y+=int(headline_font.size*1.18)
    metrics=brief.get("metrics") or []
    if metrics:
        y+=int(h*0.035)
        for metric in metrics[:3]:
            draw.text((margin,y),"• "+str(metric),font=body_font,fill=ink)
            y+=int(body_font.size*1.55)
    elif brief.get("card_note"):
        y+=int(h*0.045)
        for line in wrap(draw,str(brief["card_note"]),body_font,maxw):
            draw.text((margin,y),line,font=body_font,fill=muted)
            y+=int(body_font.size*1.35)
    disclosure="CARD EDITORIAL VÂLCEA CLAR • NU ESTE FOTOGRAFIE A EVENIMENTULUI"
    draw.text((margin,h-margin-int(small.size*1.5)),disclosure,font=small,fill=muted)
    draw.text((w-margin-int(draw.textlength("VALCEA CLAR",font=small)),margin),"VALCEA CLAR",font=small,fill=ink)
    identity={
      "story_id":story["id"],"concept":brief.get("concept"),"headline":story.get("headline"),
      "label":brief.get("label"),"metrics":metrics,"note":brief.get("card_note"),
      "size":[w,h],"renderer":"s3-editorial-card-v1"
    }
    fp=digest(identity)
    filename=f"{story['id']}-{suffix}-{fp[:12]}.jpg"
    path=OUT/filename; OUT.mkdir(parents=True,exist_ok=True)
    image.save(path,format="JPEG",quality=91,optimize=True)
    sources=[str(s.get("url")) for s in story.get("sources",[]) if isinstance(s,dict) and str(s.get("url") or "").startswith("http")]
    return {
      "kind":"editorial_card","synthetic":False,"ai_generated":False,"depicts_real_scene":False,
      "site_visible":False,"distribution_role":"social_only",
      "story_id":story["id"],"concept":brief.get("concept"),"variant":suffix,
      "filename":filename,"public_url":PUBLIC_BASE+filename,"relative_url":"/media/social/editorial/s3/"+filename,
      "sha256":sha256(path),"bytes":path.stat().st_size,"rights_basis":"original_editorial_layout",
      "creator_or_owner":"VÂLCEA CLAR","source_urls":sources,"source_fact_kernel":"canonical_verified_story",
      "credit":"VÂLCEA CLAR — card editorial","provenance_status":"VERIFIED",
      "editorial_note":"Card editorial construit din informații verificate; nu este o fotografie a evenimentului sau a persoanelor descrise.",
      "alt_text":f"Card editorial VÂLCEA CLAR: {story.get('headline')}",
      "product_fingerprint_sha256":fp
    }

def build()->dict[str,Any]:
    cfg=load(BRIEFS); stories=story_index()
    assets=[]; packs=[]
    for brief in cfg.get("stories",[]):
        sid=str(brief.get("story_id") or "")
        story=stories.get(sid)
        if not story:
            packs.append({"story_id":sid,"status":"HOLD","reason":"story_not_in_current_edition"}); continue
        og=render_card(story,brief,(1200,630),"og")
        ig=render_card(story,brief,(1080,1350),"ig")
        assets.extend([og,ig])
        packs.append({
          "story_id":sid,"status":"READY","concept":brief.get("concept"),
          "master_asset":og["public_url"],"instagram_asset":ig["public_url"],
          "channels":brief.get("channels") or {},
          "tiktok_blocker":"current_subject_media_required"
        })
    doc={
      "schema_version":"1.0","stage":"S3_VISUALS_CHANNELS","renderer":"s3-editorial-card-v1",
      "publication_authority":"none","generated_from":"current verified edition",
      "policy":{
        "cards_are_photographs":False,"cards_depict_real_scene":False,
        "cards_visible_on_site":False,"cards_social_only":True,
        "fake_documentary_imagery_forbidden":True,"provenance_required":True,
        "tiktok_current_subject_media_required":True
      },
      "assets":assets,"packs":packs,
      "summary":{"stories_ready":sum(1 for x in packs if x.get("status")=="READY"),"assets":len(assets)}
    }
    MANIFEST.parent.mkdir(parents=True,exist_ok=True)
    MANIFEST.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return doc

def self_test()->int:
    assert PUBLIC_BASE.startswith("https://valceaclar.ro/")
    cfg=load(BRIEFS)
    assert len(cfg.get("stories") or [])>=3
    for b in cfg["stories"]:
        assert (b.get("channels") or {}).get("tiktok")=="HOLD_CURRENT_MEDIA_REQUIRED"
    print("VÂLCEA CLAR S3 visual pack self-test: PASS")
    return 0

def main()->int:
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); args=p.parse_args()
    if args.self_test:return self_test()
    print(json.dumps(build(),ensure_ascii=False))
    return 0
if __name__=="__main__": raise SystemExit(main())
