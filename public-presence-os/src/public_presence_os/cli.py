from __future__ import annotations
import argparse, json
from pathlib import Path
from .control import validate_repo, build_source_manifest, manifest_hash

def main(argv=None):
    p=argparse.ArgumentParser(prog="public-presence-os")
    sub=p.add_subparsers(dest="cmd",required=True)
    v=sub.add_parser("validate"); v.add_argument("--root",default=".")
    m=sub.add_parser("manifest"); m.add_argument("--root",default=".")
    args=p.parse_args(argv)
    root=Path(args.root).resolve()
    if args.cmd=="validate":
        r=validate_repo(root)
        print(json.dumps({"ok":r.ok,"checks":list(r.checks),"errors":list(r.errors)},indent=2,sort_keys=True))
        return 0 if r.ok else 2
    manifest=build_source_manifest(root)
    print(json.dumps({"manifest":manifest,"manifest_hash":manifest_hash(manifest)},indent=2,sort_keys=True))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
