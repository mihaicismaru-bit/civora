#!/usr/bin/env python3
"""Real Git regression for the staged Newsroom transaction. No external remotes."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
TX=SCRIPTS/'newsroom_tx_safe_candidate.sh'
GUARD=SCRIPTS/'newsroom_tx_integrity_candidate.py'
P='valcea-clar/'

def run(cwd,*args,expect=True,env=None):
    result=subprocess.run(args,cwd=cwd,env=env,capture_output=True,text=True,timeout=40)
    if expect and result.returncode:
        raise AssertionError(f'{args}: {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result

def save(repo,path,value):
    p=repo/path;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(value,ensure_ascii=False)+'\n' if not isinstance(value,str) else value,encoding='utf-8')

def bundle(repo,fp,changed):
    ids=['story-one']
    ts='2026-10-11T08:00:00+03:00'
    save(repo,P+'site/newsroom_decision.json',dict(changed=changed,fingerprint=fp,publishable_story_ids=ids,new_story_ids=ids if changed else [],evaluated_local=ts))
    save(repo,P+'site/newsroom_state.json',dict(last_published_fingerprint=fp,last_published_story_ids=ids,last_published_at=ts))
    save(repo,P+'site/story_publication_event.json',dict(event='story_publication',fingerprint=fp,story_ids=ids,new_story_ids=ids if changed else [],published_at=ts,canonical_urls={'story-one':'https://valceaclar.ro/stiri/story-one/'}))
    save(repo,P+'site/current_edition.json',dict(json_source='editions/test.json',publication_intent='publish',status='auto_approved'))
    save(repo,P+'editions/test.json',dict(publication_intent='publish',status='auto_approved'))
    save(repo,P+'site/runtime/stiri/manifest.json',dict(stories=[{'id':'story-one','path':'/stiri/story-one/','canonical':'https://valceaclar.ro/stiri/story-one/'}]))
    save(repo,P+'site/runtime/stiri/story-one/index.html','<html>story</html>')
    save(repo,P+'site/runtime/live-feed.json',dict(stories=ids))

class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='vc_f0_ci_')
        d=Path(self.tmp.name);self.d=d
        self.origin=d/'origin.git';self.seed=d/'seed';self.runner=d/'runner';self.peer=d/'peer'
        run(d,'git','init','--bare','--initial-branch=main',str(self.origin))
        run(d,'git','clone',str(self.origin),str(self.seed))
        bundle(self.seed,'old',False)
        save(self.seed,P+'site/story_archive.json',{'stories':[]})
        save(self.seed,P+'editorial/auto_facts.json',{'facts':[]})
        save(self.seed,P+'editorial/news_discovery_state.json',{'signals':[]})
        save(self.seed,P+'site/runtime/media/social/card.json',{'version':'old'})
        save(self.seed,'partener-eu/index.txt','PARTENER-BASE\n')
        run(self.seed,'git','add','-A')
        run(self.seed,'git','-c','user.name=CI','-c','user.email=ci@example.invalid','commit','-m','initial')
        run(self.seed,'git','push','origin','main')
        for target in (self.runner,self.peer):
            run(d,'git','clone',str(self.origin),str(target))
            run(target,'git','config','user.name','CI')
            run(target,'git','config','user.email','ci@example.invalid')
        self.base=run(self.runner,'git','rev-parse','HEAD').stdout.strip()
        bundle(self.runner,'new',True)
    def tearDown(self):
        self.tmp.cleanup()
    def candidate(self):
        env={**os.environ,'BASE_SHA':self.base,'TX_GUARD_SCRIPT':str(GUARD)}
        return run(self.runner,'bash',str(TX),expect=False,env=env)
    def peer_commit(self,path,value):
        save(self.peer,path,value)
        run(self.peer,'git','add','-A')
        run(self.peer,'git','commit','-m','peer change')
        run(self.peer,'git','push','origin','main')
    def remote(self,path):
        return run(self.d,'git','--git-dir',str(self.origin),'show','main:'+path).stdout
    def test_atomic_promotion(self):
        r=self.candidate()
        self.assertEqual(r.returncode,0,(r.stdout,r.stderr))
        self.assertEqual(json.loads(self.remote(P+'site/story_publication_event.json'))['fingerprint'],'new')
    def test_independent_peer_preserved(self):
        self.peer_commit('partener-eu/index.txt','PARTENER-NEW\n')
        r=self.candidate()
        self.assertEqual(r.returncode,0,(r.stdout,r.stderr))
        self.assertEqual(self.remote('partener-eu/index.txt'),'PARTENER-NEW\n')
    def test_archive_changed_during_render_blocks(self):
        self.peer_commit(P+'site/story_archive.json',{'stories':['peer-new-story']})
        r=self.candidate()
        self.assertEqual(r.returncode,12,(r.stdout,r.stderr))
        self.assertIn('TX_HOLD_INPUT_STALE',r.stderr)
    def test_renderer_data_changed_during_render_blocks(self):
        self.peer_commit(P+'data/places.json',{'places':['peer-change']})
        r=self.candidate()
        self.assertEqual(r.returncode,12,(r.stdout,r.stderr))
    def test_invalid_event_never_commits(self):
        save(self.runner,P+'site/story_publication_event.json',{'fingerprint':'wrong'})
        r=self.candidate()
        self.assertEqual(r.returncode,4,(r.stdout,r.stderr))
        self.assertEqual(json.loads(self.remote(P+'site/newsroom_decision.json'))['fingerprint'],'old')

if __name__=='__main__':
    unittest.main()
