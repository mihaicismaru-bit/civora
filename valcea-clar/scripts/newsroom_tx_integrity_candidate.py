#!/usr/bin/env python3
"""Fail-closed Newsroom Git-bundle integrity gate. This does NOT prove public delivery."""
import json
import sys
from pathlib import Path

def validate(root: Path) -> None:
    vc=root/'valcea-clar'
    def read(rel):
        p=vc/rel
        if not p.is_file():
            raise ValueError('missing:'+rel)
        return json.loads(p.read_text(encoding='utf-8'))
    decision=read('site/newsroom_decision.json')
    state=read('site/newsroom_state.json')
    event=read('site/story_publication_event.json')
    pointer=read('site/current_edition.json')
    manifest=read('site/runtime/stiri/manifest.json')
    if decision.get('changed') is not True:
        raise ValueError('not_publishable_change')
    ids=decision.get('publishable_story_ids')
    if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)):
        raise ValueError('invalid_story_ids')
    fingerprint=decision.get('fingerprint')
    if not fingerprint or state.get('last_published_fingerprint')!=fingerprint or event.get('fingerprint')!=fingerprint:
        raise ValueError('fingerprint_mismatch')
    if ids!=state.get('last_published_story_ids') or ids!=event.get('story_ids'):
        raise ValueError('story_ids_mismatch')
    if decision.get('new_story_ids')!=event.get('new_story_ids'):
        raise ValueError('new_story_ids_mismatch')
    if event.get('event')!='story_publication':
        raise ValueError('wrong_event_type')
    if state.get('last_published_at')!=event.get('published_at') or event.get('published_at')!=decision.get('evaluated_local'):
        raise ValueError('publication_timestamp_mismatch')
    if pointer.get('publication_intent')!='publish' or pointer.get('status') not in ('auto_approved','editor_approved'):
        raise ValueError('pointer_not_publishable')
    source=pointer.get('json_source') or ''
    if not source.startswith('editions/') or '..' in Path(source).parts or not (vc/source).is_file():
        raise ValueError('edition_source_missing')
    edition=read(source)
    if edition.get('publication_intent')!='publish' or edition.get('status') not in ('auto_approved','editor_approved'):
        raise ValueError('edition_not_publishable')
    manifest_rows={r.get('id'):r for r in manifest.get('stories',[])}
    for sid in ids:
        row=manifest_rows.get(sid)
        if row is None:
            raise ValueError('missing_manifest_story:'+sid)
        path=row.get('path') or ''
        canon=row.get('canonical') or ''
        if path!=f'/stiri/{sid}/' or canon!=f'https://valceaclar.ro{path}':
            raise ValueError('bad_canonical:'+sid)
        if event.get('canonical_urls',{}).get(sid)!=canon:
            raise ValueError('event_canonical_mismatch:'+sid)
        target=vc/'site/runtime'/path.lstrip('/')/'index.html'
        if not target.is_file():
            raise ValueError('missing_html:'+sid)
    if not (vc/'site/runtime/live-feed.json').is_file():
        raise ValueError('missing_live_feed')

if __name__=='__main__':
    try:
        validate(Path(sys.argv[1] if len(sys.argv)>1 else '.'))
    except (ValueError,TypeError,KeyError,json.JSONDecodeError) as ex:
        print('TX_INTEGRITY_HOLD:'+str(ex),file=sys.stderr)
        sys.exit(4)
    print('TX_INTEGRITY_PASS (Git bundle only, NOT public delivery)')
