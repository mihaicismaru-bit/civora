#!/usr/bin/env python3
"""Materialize YouTube/Shorts editorial v1 into canonical outbox/state.

Outbox-only. No upload credentials or network calls are used.
"""
from __future__ import annotations

import argparse, json
from pathlib import Path
from typing import Any
import youtube_editorial_v1 as editorial

ROOT=Path(__file__).resolve().parents[2]
VC=ROOT/'valcea-clar'
OUTBOX=VC/'social'/'youtube_outbox.json'
STATE=VC/'social'/'youtube_state.json'

def load(path:Path, default:dict[str,Any])->dict[str,Any]:
    if not path.exists(): return default
    value=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(value,dict): raise ValueError(f'{path} must contain an object')
    return value

def write(path:Path,value:dict[str,Any])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def canonical_item(product:dict[str,Any])->dict[str,Any]:
    sid=str(product['story_id'])
    common={
        'id':f'youtube-story-{sid}','story_id':sid,'publication_mode':'durable_outbox_only',
        'canonical_url':product['canonical_url'],'source_preserving':True,
        'real_video_required':True,'synthetic_filler_forbidden':True,'archive_as_current_forbidden':True,
        'verbatim_cross_platform_reuse_allowed':False,'direct_publication_enabled':False,
        'direct_publication_blocker':'youtube_verified_upload_access_not_configured',
        'generation_mode':'youtube_editorial_v1','edition_gate':False,
    }
    if product.get('status')=='HOLD':
        return {**common,'status':'hold','native_format':'short','format_family':'youtube_hold','hold_reason':product.get('hold_reason')}
    return {**common,
        'status':'hold_media' if product.get('status')=='HOLD_MEDIA' else 'outbox_ready',
        'native_format':product['native_format'],'format_family':product['format_family'],
        'hold_reason':product.get('hold_reason'),'title':product['title'],'thumbnail_text':product['thumbnail_text'],
        'chapters':product['chapters'],'title_thumbnail_pair_required':True,
        'product_fingerprint_sha256':product['product_fingerprint_sha256'],
    }

def build()->dict[str,Any]:
    preview=editorial.build(); products=[canonical_item(p) for p in preview.get('products',[])]
    outbox=load(OUTBOX,{'schema_version':'1.0','platform':'youtube','items':[]})
    existing={str(i.get('id')):i for i in outbox.get('items',[]) if isinstance(i,dict) and i.get('id')}
    for p in products: existing[p['id']]=p
    outbox.update({'schema_version':'1.1','platform':'youtube','publication_model':'continuous_story_first','editorial_product_version':'youtube-editorial-v1.0','edition_recaps_are_publication_gates':False,'items':list(existing.values())})
    write(OUTBOX,outbox)
    state=load(STATE,{'schema_version':'1.0','platform':'youtube','execution_owner':'civora_site_engine','published':{},'failures':{}})
    state.update({'schema_version':'1.1','platform':'youtube','execution_owner':'civora_site_engine','publication_model':'continuous_story_first','editorial_product_version':'youtube-editorial-v1.0','direct_publication_enabled':False,'direct_publication_blocker':'youtube_verified_upload_access_not_configured'})
    state.setdefault('published',{}); state.setdefault('failures',{}); write(STATE,state)
    return {'status':'PASS','platform':'youtube','products':len(products),'ready':sum(p.get('status')=='outbox_ready' for p in products),'held':sum(p.get('status')!='outbox_ready' for p in products),'direct_publication_enabled':False}

def self_test()->int:
    p=canonical_item({'story_id':'x','status':'HOLD_MEDIA','hold_reason':'video_required','native_format':'long_video','format_family':'document_explainer','title':'Titlu','thumbnail_text':'THUMB','chapters':[],'canonical_url':'https://valceaclar.ro/stiri/x/','product_fingerprint_sha256':'a'*64})
    assert p['status']=='hold_media' and p['direct_publication_enabled'] is False and p['generation_mode']=='youtube_editorial_v1'
    print('VÂLCEA CLAR YouTube editorial materializer self-test: PASS'); return 0

def main()->int:
    parser=argparse.ArgumentParser(); parser.add_argument('--self-test',action='store_true'); args=parser.parse_args()
    if args.self_test: return self_test()
    print(json.dumps(build(),ensure_ascii=False,indent=2)); return 0

if __name__=='__main__': raise SystemExit(main())
