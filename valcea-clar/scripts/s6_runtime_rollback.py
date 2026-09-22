#!/usr/bin/env python3
"""Validate S6 runtime rollback targets.

Actual file restoration is performed only inside the manual GitHub Actions
workflow after exact human confirmation. This helper never mutates files.
"""
from __future__ import annotations
import argparse,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASELINES=ROOT/"ops"/"rollback_baselines.json"

def load():
    return json.loads(BASELINES.read_text(encoding="utf-8"))

def resolve(value:str)->dict:
    doc=load()
    wanted=doc.get("current_lkg") if value in {"","lkg","current_lkg"} else value
    row=next((x for x in doc.get("baselines") or [] if str(x.get("id"))==wanted),None)
    if not isinstance(row,dict): raise SystemExit(f"Unknown rollback baseline: {wanted}")
    if row.get("rollback_eligible") is not True or row.get("scope")!="runtime_only":
        raise SystemExit(f"Baseline is not executable for runtime rollback: {wanted}")
    sha=str(row.get("commit") or "")
    if not re.fullmatch(r"[0-9a-f]{40}",sha): raise SystemExit("Invalid rollback commit")
    return row

def main():
    p=argparse.ArgumentParser(); p.add_argument("--target",default="lkg"); p.add_argument("--json",action="store_true"); args=p.parse_args()
    row=resolve(args.target)
    print(json.dumps(row,ensure_ascii=False) if args.json else row["commit"])
    return 0
if __name__=="__main__": raise SystemExit(main())
