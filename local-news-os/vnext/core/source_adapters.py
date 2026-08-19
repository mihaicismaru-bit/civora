#!/usr/bin/env python3
"""Configuration-driven source adapter core for LOCAL NEWS OS vNext."""

from __future__ import annotations
import argparse, hashlib, html as html_lib, json, re
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
import xml.etree.ElementTree as ET

SUPPORTED_ADAPTERS={"RSS_ATOM","HTML_LIST","HTML_ARTICLE","WORDPRESS_REST","JSON_API","SITEMAP","PDF_REGISTER"}
SUPPORTED_ROLES={"DISCOVERY","PRIMARY","BOTH"}
MAX_ITEMS_DEFAULT=200

class SourceAdapterError(ValueError): pass

@dataclass(frozen=True)
class SourceItem:
    source_id:str; external_id:str; url:str; title:str
    published_at:str|None=None; summary:str|None=None; body:str|None=None
    author:str|None=None; media_urls:tuple[str,...]=(); metadata:dict[str,Any]|None=None
    fingerprint:str=""
    def to_dict(self):
        d=asdict(self); d["media_urls"]=list(self.media_urls); return d

@dataclass(frozen=True)
class SourceDefinition:
    source_id:str; adapter:str; role:str; url:str; enabled:bool; max_items:int; config:dict[str,Any]
    @classmethod
    def from_dict(cls, raw):
        if not isinstance(raw,dict): raise SourceAdapterError("source definition must be an object")
        source_id=_required_text(raw,"source_id"); adapter=_required_text(raw,"adapter").upper()
        role=str(raw.get("role","DISCOVERY")).upper(); url=_required_text(raw,"url")
        enabled=raw.get("enabled",True); max_items=raw.get("max_items",MAX_ITEMS_DEFAULT); config=raw.get("config",{})
        if adapter not in SUPPORTED_ADAPTERS: raise SourceAdapterError(f"unsupported adapter: {adapter}")
        if role not in SUPPORTED_ROLES: raise SourceAdapterError(f"unsupported role: {role}")
        if not isinstance(enabled,bool): raise SourceAdapterError("enabled must be boolean")
        if not isinstance(max_items,int) or not 1<=max_items<=1000: raise SourceAdapterError("max_items must be between 1 and 1000")
        if not isinstance(config,dict): raise SourceAdapterError("config must be an object")
        p=urlparse(url)
        if p.scheme not in {"https","http"} or not p.netloc: raise SourceAdapterError("source url must be absolute http(s)")
        if p.scheme=="http" and config.get("allow_insecure_http") is not True:
            raise SourceAdapterError("http sources require config.allow_insecure_http=true")
        return cls(source_id,adapter,role,url,enabled,max_items,config)

def validate_source_pack(pack, expected_instance_id=None):
    if not isinstance(pack,dict): raise SourceAdapterError("source pack must be an object")
    if pack.get("schema_version")!="2.0": raise SourceAdapterError("source pack schema_version must be 2.0")
    if pack.get("pack_type")!="sources": raise SourceAdapterError("pack_type must be sources")
    instance_id=_required_text(pack,"instance_id")
    if expected_instance_id and instance_id!=expected_instance_id: raise SourceAdapterError("source pack instance_id mismatch")
    sources=pack.get("sources")
    if not isinstance(sources,list): raise SourceAdapterError("sources must be an array")
    defs=[SourceDefinition.from_dict(x) for x in sources]; ids=[x.source_id for x in defs]
    if len(ids)!=len(set(ids)): raise SourceAdapterError("source_id values must be unique")
    return defs

def adapt_payload(source,payload):
    s=source if isinstance(source,SourceDefinition) else SourceDefinition.from_dict(source)
    if not s.enabled: return []
    fn={"RSS_ATOM":_adapt_rss_atom,"HTML_LIST":_adapt_html_list,"HTML_ARTICLE":_adapt_html_article,
        "WORDPRESS_REST":_adapt_wordpress,"JSON_API":_adapt_json_api,"SITEMAP":_adapt_sitemap,
        "PDF_REGISTER":_adapt_pdf_register}[s.adapter]
    data=_as_json(payload) if s.adapter in {"WORDPRESS_REST","JSON_API"} else _as_text(payload)
    return _dedupe_and_limit(fn(s,data),s.max_items)

def _required_text(raw,key):
    v=raw.get(key)
    if not isinstance(v,str) or not v.strip(): raise SourceAdapterError(f"{key} must be non-empty text")
    return v.strip()

def _as_text(payload):
    if isinstance(payload,bytes): return payload.decode("utf-8",errors="replace")
    if isinstance(payload,str): return payload
    raise SourceAdapterError("adapter expects text payload")

def _as_json(payload):
    if isinstance(payload,(dict,list)): return payload
    if isinstance(payload,bytes): payload=payload.decode("utf-8")
    if isinstance(payload,str):
        try: return json.loads(payload)
        except json.JSONDecodeError as e: raise SourceAdapterError(f"invalid JSON payload: {e.msg}") from e
    raise SourceAdapterError("adapter expects JSON payload")

def _clean_text(v):
    if v is None:return None
    if not isinstance(v,str):v=str(v)
    v=re.sub(r"<[^>]+>"," ",v); v=html_lib.unescape(v); v=re.sub(r"\s+"," ",v).strip()
    return v or None

def _normalize_date(v):
    t=_clean_text(v)
    if not t:return None
    try:d=datetime.fromisoformat(t.replace("Z","+00:00"))
    except ValueError:return t
    if d.tzinfo is None:return d.isoformat()
    return d.astimezone(timezone.utc).isoformat().replace("+00:00","Z")

def _field(obj,path,default=None):
    if not path:return default
    cur=obj
    for part in path.split("."):
        if isinstance(cur,dict):cur=cur.get(part,default)
        elif isinstance(cur,list) and part.isdigit():
            i=int(part)
            if i>=len(cur):return default
            cur=cur[i]
        else:return default
    return cur

def _abs(base,v):
    t=_clean_text(v); return urljoin(base,t) if t else ""

def _fp(source_id,external_id,url,title):
    return hashlib.sha256("\n".join((source_id,external_id,url,title)).encode()).hexdigest()

def _make_item(s,external_id,url,title,published_at=None,summary=None,body=None,author=None,media_urls=(),metadata=None):
    u=_abs(s.url,url); t=_clean_text(title)
    if not u or not t:return None
    eid=_clean_text(external_id) or u
    media=tuple(x for x in (_abs(s.url,m) for m in media_urls) if x)
    return SourceItem(s.source_id,eid,u,t,_normalize_date(published_at),_clean_text(summary),_clean_text(body),
                      _clean_text(author),media,metadata or {},_fp(s.source_id,eid,u,t))

def _dedupe_and_limit(items,limit):
    seen=set(); out=[]
    for item in items:
        if item is None or item.fingerprint in seen:continue
        seen.add(item.fingerprint); out.append(item)
        if len(out)>=limit:break
    return out

def _lname(tag):return tag.rsplit("}",1)[-1].lower()
def _children(node):
    d={}
    for c in list(node):d.setdefault(_lname(c.tag),[]).append(c)
    return d
def _first(d,*names):
    for n in names:
        for node in d.get(n,[]):
            v="".join(node.itertext()).strip()
            if v:return v
    return None

def _adapt_rss_atom(s,payload):
    try:root=ET.fromstring(payload)
    except ET.ParseError as e:raise SourceAdapterError(f"invalid RSS/Atom XML: {e}") from e
    out=[]
    for node in root.iter():
        if _lname(node.tag) not in {"item","entry"}:continue
        c=_children(node); link=_first(c,"link")
        if not link:
            for ln in c.get("link",[]):
                link=ln.attrib.get("href")
                if link:break
        out.append(_make_item(s,_first(c,"guid","id") or link,link,_first(c,"title"),
                              _first(c,"pubdate","published","updated"),_first(c,"description","summary","content"),
                              author=_first(c,"author","creator"),metadata={"adapter":s.adapter}))
    return out

def _regex_rows(s,payload,key):
    pat=s.config.get(key)
    if not isinstance(pat,str) or not pat:raise SourceAdapterError(f"{s.adapter} requires config.{key}")
    try:r=re.compile(pat,re.I|re.S)
    except re.error as e:raise SourceAdapterError(f"invalid {key}: {e}") from e
    out=[]
    for m in r.finditer(payload):
        d={k:(v or "") for k,v in m.groupdict().items()}
        if not d:raise SourceAdapterError(f"{key} must use named capture groups")
        out.append(d)
    return out

def _adapt_html_list(s,payload):
    return [_make_item(s,d.get("id") or d.get("url"),d.get("url"),d.get("title"),d.get("published_at"),
                       d.get("summary"),metadata={"adapter":s.adapter}) for d in _regex_rows(s,payload,"item_regex")]

def _adapt_html_article(s,payload):
    fields=s.config.get("fields")
    if not isinstance(fields,dict):raise SourceAdapterError("HTML_ARTICLE requires config.fields regex map")
    d={}
    for name in ("id","url","title","published_at","summary","body","author"):
        pat=fields.get(name)
        if pat is None:continue
        if not isinstance(pat,str):raise SourceAdapterError(f"HTML_ARTICLE field {name} must be regex text")
        m=re.search(pat,payload,re.I|re.S)
        if m:d[name]=m.groupdict().get("value") or m.group(1)
    url=d.get("url") or s.url
    return [_make_item(s,d.get("id") or url,url,d.get("title"),d.get("published_at"),d.get("summary"),
                       d.get("body"),d.get("author"),metadata={"adapter":s.adapter})]

def _adapt_wordpress(s,payload):
    if not isinstance(payload,list):raise SourceAdapterError("WORDPRESS_REST expects a JSON array")
    return [_make_item(s,o.get("id"),o.get("link"),_field(o,"title.rendered"),o.get("date_gmt") or o.get("date"),
                       _field(o,"excerpt.rendered"),_field(o,"content.rendered"),o.get("author"),
                       metadata={"adapter":s.adapter,"status":o.get("status")}) for o in payload if isinstance(o,dict)]

def _adapt_json_api(s,payload):
    items=_field(payload,s.config.get("item_path"),payload) if s.config.get("item_path") else payload
    if not isinstance(items,list):raise SourceAdapterError("JSON_API item_path must resolve to an array")
    f=s.config.get("fields",{})
    if not isinstance(f,dict):raise SourceAdapterError("JSON_API config.fields must be an object")
    if not f.get("title") or not f.get("url"):raise SourceAdapterError("JSON_API requires fields.title and fields.url")
    out=[]
    for o in items:
        if not isinstance(o,dict):continue
        mv=_field(o,f.get("media_urls"),[]) if f.get("media_urls") else []
        if isinstance(mv,str):mv=[mv]
        if not isinstance(mv,list):mv=[]
        out.append(_make_item(s,_field(o,f.get("id")) or _field(o,f["url"]),_field(o,f["url"]),_field(o,f["title"]),
                              _field(o,f.get("published_at")),_field(o,f.get("summary")),_field(o,f.get("body")),
                              _field(o,f.get("author")),mv,{"adapter":s.adapter}))
    return out

def _adapt_sitemap(s,payload):
    try:root=ET.fromstring(payload)
    except ET.ParseError as e:raise SourceAdapterError(f"invalid sitemap XML: {e}") from e
    out=[]
    for node in root.iter():
        if _lname(node.tag)!="url":continue
        c=_children(node); loc=_first(c,"loc")
        if loc:out.append(_make_item(s,loc,loc,loc,_first(c,"lastmod"),metadata={"adapter":s.adapter,"sitemap_only":True}))
    return out

def _adapt_pdf_register(s,payload):
    return [_make_item(s,d.get("id") or d.get("url"),d.get("url") or s.url,d.get("title"),
                       d.get("published_at"),d.get("summary"),metadata={"adapter":s.adapter,"source_document":s.url})
            for d in _regex_rows(s,payload,"record_regex")]

def _self_test():
    rss=adapt_payload({"source_id":"feed","adapter":"RSS_ATOM","url":"https://example.test/feed","config":{}},
                      "<rss><channel><item><guid>a1</guid><title>Alpha</title><link>https://example.test/a</link></item></channel></rss>")
    assert len(rss)==1 and rss[0].title=="Alpha"
    js=adapt_payload({"source_id":"api","adapter":"JSON_API","role":"PRIMARY","url":"https://api.example.test/items",
                      "config":{"item_path":"results","fields":{"id":"id","url":"url","title":"headline","published_at":"published","media_urls":"images"}}},
                     {"results":[{"id":7,"url":"/seven","headline":"Seven","published":"2026-08-19T09:00:00+03:00","images":["/photo.jpg"]}]})
    assert js[0].url=="https://api.example.test/seven" and js[0].published_at=="2026-08-19T06:00:00Z"
    html=adapt_payload({"source_id":"html","adapter":"HTML_LIST","url":"https://example.test/news/",
                        "config":{"item_regex":r'<a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>'}},
                       '<a href="/one">One</a><a href="/two">Two</a>')
    assert [x.title for x in html]==["One","Two"]
    wp=adapt_payload({"source_id":"wp","adapter":"WORDPRESS_REST","role":"BOTH","url":"https://example.test/wp-json/wp/v2/posts","config":{}},
                     [{"id":3,"link":"https://example.test/post","title":{"rendered":"Post"},"excerpt":{"rendered":"<p>Excerpt</p>"},"content":{"rendered":"<p>Body</p>"},"status":"publish"}])
    assert wp[0].summary=="Excerpt"
    sm=adapt_payload({"source_id":"map","adapter":"SITEMAP","url":"https://example.test/sitemap.xml","config":{}},
                     "<urlset><url><loc>https://example.test/story</loc><lastmod>2026-08-19</lastmod></url></urlset>")
    assert sm[0].metadata["sitemap_only"] is True
    pdf=adapt_payload({"source_id":"reg","adapter":"PDF_REGISTER","role":"PRIMARY","url":"https://example.test/register.pdf",
                       "config":{"record_regex":r'ID=(?P<id>\d+)\s+TITLE=(?P<title>[^|]+)\|URL=(?P<url>\S+)'}},
                      "ID=42 TITLE=Decision title |URL=https://example.test/doc/42")
    assert pdf[0].external_id=="42"
    pack={"schema_version":"2.0","pack_type":"sources","instance_id":"fixture",
          "sources":[{"source_id":"one","adapter":"RSS_ATOM","url":"https://example.test/feed","config":{}}]}
    assert len(validate_source_pack(pack,"fixture"))==1
    try:SourceDefinition.from_dict({"source_id":"bad","adapter":"CUSTOM_LOCAL_PARSER","url":"https://example.test","config":{}})
    except SourceAdapterError:pass
    else:raise AssertionError("custom parser must fail closed")
    print("VNEXT_GENERIC_SOURCE_ADAPTER_CORE_PASS")

def main():
    p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
    if a.self_test:_self_test(); return 0
    p.error("--self-test is required"); return 2

if __name__=="__main__": raise SystemExit(main())
