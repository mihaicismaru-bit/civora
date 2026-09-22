#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
import urllib.error
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("p10_validate.py")
spec = importlib.util.spec_from_file_location("p10_validate", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)

class FakeHeaders:
    def items(self): return []

class FakeResponse:
    status = 200
    headers = FakeHeaders()
    def __init__(self, url: str, body: bytes = b"<html><body>Regiunea Centru program regional funding action content sufficient for markers and semantic validation.</body></html>"):
        self.url=url; self.body=body
    def __enter__(self): return self
    def __exit__(self, exc_type, exc, tb): return False
    def read(self, _limit: int): return self.body
    def geturl(self): return self.url

def main() -> int:
    src={"id":"SRC-PR-CENTRU-ACTIUNI","url":"https://www.regiocentru.ro/actiuni/","markers_any":["Regiunea Centru"]}
    assert mod.source_transport_urls(src)==[
        "https://www.regiocentru.ro/actiuni/",
        "https://regiocentru.ro/actiuni/",
    ]
    other={"id":"OTHER","url":"https://example.org/official/","markers_any":[]}
    assert mod.source_transport_urls(other)==["https://example.org/official/"]

    original_urlopen=mod.urllib.request.urlopen
    original_subprocess=mod.subprocess.run
    original_sleep=mod.time.sleep
    try:
        mod.time.sleep=lambda _seconds: None
        urllib_calls=[]; curl_calls=[]
        def forbidden_www_then_alias(req, timeout=35):
            url=req.full_url; urllib_calls.append(url)
            if url.startswith("https://www.regiocentru.ro"):
                raise urllib.error.HTTPError(url,403,"Forbidden",{},None)
            return FakeResponse(url)
        def curl_forbidden(args, capture_output=True, timeout=50):
            curl_calls.append(args)
            return subprocess.CompletedProcess(args,0,b"Forbidden\n__PARTENER_HTTP_STATUS__:403",b"")
        mod.urllib.request.urlopen=forbidden_www_then_alias
        mod.subprocess.run=curl_forbidden
        obs=mod.fetch_source(src,attempts=3)
        assert obs["ok"] is True,obs
        assert obs["final_url"]=="https://regiocentru.ro/actiuni/",obs
        assert obs["fetch_method"]=="urllib",obs
        assert obs["attempts"]==3,obs
        assert urllib_calls==["https://www.regiocentru.ro/actiuni/","https://regiocentru.ro/actiuni/"],urllib_calls
        assert len(curl_calls)==1,curl_calls

        transient_calls=[]
        def transient_then_success(req, timeout=35):
            transient_calls.append(req.full_url)
            if len(transient_calls)==1:
                raise urllib.error.HTTPError(req.full_url,503,"Unavailable",{},None)
            return FakeResponse(req.full_url)
        mod.urllib.request.urlopen=transient_then_success
        mod.subprocess.run=lambda *args,**kwargs: (_ for _ in ()).throw(AssertionError("curl must not run after urllib retry success"))
        obs=mod.fetch_source(src,attempts=3)
        assert obs["ok"] is True,obs
        assert obs["attempts"]==2,obs
        assert transient_calls==[src["url"],src["url"]],transient_calls

        deterministic_calls=[]
        def all_forbidden(req, timeout=35):
            deterministic_calls.append(req.full_url)
            raise urllib.error.HTTPError(req.full_url,403,"Forbidden",{},None)
        def all_forbidden_curl(args, capture_output=True, timeout=50):
            return subprocess.CompletedProcess(args,0,b"Forbidden\n__PARTENER_HTTP_STATUS__:403",b"")
        mod.urllib.request.urlopen=all_forbidden
        mod.subprocess.run=all_forbidden_curl
        obs=mod.fetch_source(src,attempts=3)
        assert obs["ok"] is False,obs
        assert obs["http_status"]==403,obs
        assert obs["attempts"]==4,obs
        assert deterministic_calls==["https://www.regiocentru.ro/actiuni/","https://regiocentru.ro/actiuni/"],deterministic_calls
    finally:
        mod.urllib.request.urlopen=original_urlopen
        mod.subprocess.run=original_subprocess
        mod.time.sleep=original_sleep

    print("PASS P10 transport policy is bounded, same-authority and fail-fast on deterministic 4xx")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
