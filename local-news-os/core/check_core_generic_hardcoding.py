#!/usr/bin/env python3
"""Fail closed when production-instance identity leaks into CORE_GENERIC source."""
from __future__ import annotations
import ast, json, re, unicodedata
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; CORE_ROOT=ROOT/"local-news-os"/"core"; INSTANCES_ROOT=ROOT/"local-news-os"/"instances"
ALLOWLIST={
 "local-news-os/core/discover_primary_source_facts.py":"TEMPORARY_COMPATIBILITY_ADAPTER",
 "local-news-os/core/discover_primary_source_facts_fast.py":"TEMPORARY_COMPATIBILITY_ADAPTER",
}
GENERIC_IDENTITY_WORDS={"romania","romanian","county","judetul","local","news","clar"}
def normalize(v:str)->str:
 f=unicodedata.normalize("NFKD",v.casefold()); return "".join(c for c in f if not unicodedata.combining(c))
def identity_strings(cfg:dict)->list[str]:
 vals=[]
 for k in ("instance_id","canonical_domain"):
  if isinstance(cfg.get(k),str): vals.append(cfg[k])
 b=cfg.get("brand") or {}
 for k in ("name","short_name"):
  if isinstance(b.get(k),str): vals.append(b[k])
 g=cfg.get("geography") or {}
 for k in ("primary_name","county"):
  if isinstance(g.get(k),str): vals.append(g[k])
 for k in ("settlements","aliases"):
  if isinstance(g.get(k),list): vals.extend(x for x in g[k] if isinstance(x,str))
 return vals
def forbidden_tokens()->tuple[str,...]:
 tokens=set()
 for p in sorted(INSTANCES_ROOT.glob("*/instance.json")):
  cfg=json.loads(p.read_text(encoding="utf-8"))
  if cfg.get("environment")!="production": continue
  for raw in identity_strings(cfg):
   v=normalize(raw).strip()
   if len(v)>=5: tokens.add(v)
   tokens.update(x for x in re.findall(r"[a-z0-9.-]+",v) if len(x)>=5)
 tokens.difference_update(GENERIC_IDENTITY_WORDS)
 return tuple(sorted(tokens,key=lambda x:(-len(x),x)))
def docstrings(tree):
 out=set()
 for n in ast.walk(tree):
  b=getattr(n,"body",None)
  if isinstance(b,list) and b and isinstance(b[0],ast.Expr) and isinstance(b[0].value,ast.Constant) and isinstance(b[0].value.value,str): out.add(id(b[0].value))
 return out
class Visitor(ast.NodeVisitor):
 def __init__(self,tokens,docs): self.tokens=tokens; self.docs=docs; self.hits=set()
 def visit_FunctionDef(self,n):
  if n.name=="self_test" or n.name.startswith("test_"): return
  self.generic_visit(n)
 def visit_AsyncFunctionDef(self,n):
  if n.name=="self_test" or n.name.startswith("test_"): return
  self.generic_visit(n)
 def visit_Constant(self,n):
  if id(n) in self.docs or not isinstance(n.value,str): return
  v=normalize(n.value); self.hits.update(t for t in self.tokens if t in v)
def scan()->list[str]:
 tokens=forbidden_tokens(); errors=[]; me=Path(__file__).resolve()
 for p in sorted(CORE_ROOT.rglob("*.py")):
  if p.resolve()==me: continue
  rel=p.relative_to(ROOT).as_posix()
  if rel in ALLOWLIST: continue
  try: tree=ast.parse(p.read_text(encoding="utf-8"),filename=rel)
  except SyntaxError as e: errors.append(f"{rel}: cannot scan invalid Python: {e}"); continue
  v=Visitor(tokens,docstrings(tree)); v.visit(tree)
  if v.hits: errors.append(f"{rel}: production identity in CORE_GENERIC executable literals: {', '.join(sorted(v.hits)[:8])}")
 return errors
def self_test():
 assert forbidden_tokens(); tree=ast.parse("VALUE='synthetic-instance'\ndef self_test():\n x='fixture-only'\n"); v=Visitor(("synthetic-instance","fixture-only"),docstrings(tree)); v.visit(tree); assert v.hits=={"synthetic-instance"}; print("CORE_GENERIC_HARDCODING_GUARD_SELF_TEST_PASS")
def main():
 import argparse
 p=argparse.ArgumentParser(); p.add_argument("--self-test",action="store_true"); a=p.parse_args()
 if a.self_test: self_test()
 errors=scan(); print(json.dumps({"status":"PASS" if not errors else "FAIL","production_identity_token_count":len(forbidden_tokens()),"allowlist":ALLOWLIST,"errors":errors},ensure_ascii=False,indent=2)); return 0 if not errors else 1
if __name__=="__main__": raise SystemExit(main())
