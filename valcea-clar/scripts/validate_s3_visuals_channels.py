#!/usr/bin/env python3
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def load(p): return json.loads(p.read_text(encoding="utf-8"))
def main():
    cfg=load(ROOT/"visuals"/"s3_visual_briefs.json")
    assert len(cfg.get("stories") or [])==7
    ids=[x["story_id"] for x in cfg["stories"]]; assert len(ids)==len(set(ids))
    for row in cfg["stories"]:
        ch=row["channels"]
        assert ch["site"]=="SITE_OG_CARD"
        assert ch["facebook"]=="TEXT_LINK_WITH_OG_CARD"
        assert ch["instagram"]=="VERIFIED_FACT_CARD"
        assert ch["threads"]=="TEXT_FIRST"
        assert ch["tiktok"]=="HOLD_CURRENT_MEDIA_REQUIRED"
    print(json.dumps({"status":"PASS","stories":len(ids),"tiktok_fail_closed":True}))
if __name__=="__main__": main()
