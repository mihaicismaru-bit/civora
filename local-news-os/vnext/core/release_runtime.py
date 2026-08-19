#!/usr/bin/env python3
"""Private release-health projection for LOCAL NEWS OS vNext P16."""
from __future__ import annotations
import argparse, html, hmac, json, tempfile
from pathlib import Path
from typing import Any, Callable, Iterable
from release_control import ensure_release_schema, initialize_release_state, register_candidate, release_snapshot
from runtime_store import connect, initialize, register_instance
StartResponse=Callable[[str,list[tuple[str,str]]],Any]
class ReleaseRuntimeError(RuntimeError):pass
class ReleaseNewsroomApp:
    def __init__(self,*,db_path:str|Path,instance_id:str,newsroom_token:str|None):self.db_path=str(db_path);self.instance_id=instance_id;self.token=newsroom_token or None
    def _resp(self,sr,status,body,ctype):
        sr(status,[('Content-Type',ctype),('Content-Length',str(len(body))),('Cache-Control','no-store, private'),('X-Robots-Tag','noindex, nofollow, noarchive'),('X-Content-Type-Options','nosniff')]);return [body]
    def _json(self,sr,status,p):return self._resp(sr,status,json.dumps(p,ensure_ascii=False,sort_keys=True).encode(),'application/json; charset=utf-8')
    def _auth(self,e):
        h=str(e.get('HTTP_AUTHORIZATION') or '');return bool(self.token and h.startswith('Bearer ') and hmac.compare_digest(h[7:],self.token))
    def __call__(self,environ,sr)->Iterable[bytes]:
        path=str(environ.get('PATH_INFO') or '');method=str(environ.get('REQUEST_METHOD') or 'GET').upper()
        if path not in {'/newsroom/releases','/newsroom/api/releases'}:return self._json(sr,'404 Not Found',{'error':'not_found'})
        if method!='GET':return self._json(sr,'405 Method Not Allowed',{'error':'method_not_allowed'})
        if not self.token:return self._json(sr,'503 Service Unavailable',{'error':'newsroom_auth_not_configured'})
        if not self._auth(environ):return self._json(sr,'401 Unauthorized',{'error':'unauthorized'})
        c=connect(self.db_path)
        try:ensure_release_schema(c);snap=release_snapshot(c,instance_id=self.instance_id)
        finally:c.close()
        if path.endswith('/api/releases'):return self._json(sr,'200 OK',snap)
        s=snap['state'];rows=''.join(f"<tr><td>{html.escape(str(x['engine_version']))}</td><td>{html.escape(str(x['status']))}</td><td><code>{html.escape(str(x['artifact_fingerprint'])[:16])}</code></td></tr>" for x in snap['candidates']) or '<tr><td colspan=3>No candidates</td></tr>'
        body=f"<!doctype html><html><head><meta charset=utf-8><title>Releases · Newsroom</title></head><body><p><a href=/newsroom>← Newsroom</a></p><h1>Release health</h1><p>Current: <strong>{html.escape(str(s['current_engine_version']))}</strong> · rollback: <strong>{html.escape(str(s.get('previous_engine_version') or 'none'))}</strong> · generation {s['generation']}</p><table><thead><tr><th>Version</th><th>Status</th><th>Artifact</th></tr></thead><tbody>{rows}</tbody></table></body></html>".encode()
        return self._resp(sr,'200 OK',body,'text/html; charset=utf-8')
def _invoke(app,path,token=None):
    cap={}
    def sr(s,h):cap['s']=s;cap['h']=dict(h)
    env={'PATH_INFO':path,'REQUEST_METHOD':'GET'}
    if token:env['HTTP_AUTHORIZATION']='Bearer '+token
    b=b''.join(app(env,sr));return cap['s'],cap['h'],b
def _manifest(i,d):return {'instance_id':i,'publication':{'canonical_domain':d},'config_sha256':'a'*64,'runtime':{'owner':'site_application','repository_runtime_state_enabled':False}}
def self_test():
    with tempfile.TemporaryDirectory() as td:
        db=Path(td)/'r.db';c=connect(db);initialize(c);register_instance(c,_manifest('alpha-local','alpha.invalid'),engine_version='1.0.0');ensure_release_schema(c);initialize_release_state(c,instance_id='alpha-local',current_engine_version='1.0.0')
        from release_control import _candidate
        register_candidate(c,instance_id='alpha-local',manifest=_candidate('1.1.0','x'),engine_version='test');c.close()
        app=ReleaseNewsroomApp(db_path=db,instance_id='alpha-local',newsroom_token='secret');s,h,b=_invoke(app,'/newsroom/releases','secret');assert s=='200 OK' and b'Release health' in b and h['Cache-Control']=='no-store, private'
        s,_,b=_invoke(app,'/newsroom/api/releases','secret');assert s=='200 OK' and json.loads(b)['state']['current_engine_version']=='1.0.0'
        assert _invoke(app,'/newsroom/api/releases','wrong')[0]=='401 Unauthorized'
        assert _invoke(ReleaseNewsroomApp(db_path=db,instance_id='alpha-local',newsroom_token=None),'/newsroom/releases')[0]=='503 Service Unavailable'
        print('VNEXT_P16_RELEASE_NEWSROOM_SELF_TEST_PASS')
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');a=p.parse_args()
    if a.self_test:self_test();return 0
    raise ReleaseRuntimeError('mount ReleaseNewsroomApp in the site application')
if __name__=='__main__':raise SystemExit(main())
