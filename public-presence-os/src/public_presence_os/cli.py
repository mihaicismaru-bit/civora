from __future__ import annotations
import argparse, json
from pathlib import Path
from .control import validate_repo, build_source_manifest, manifest_hash
from .radar import RadarObservation, RadarSourceClass, RadarKind, ingest_observations, signals_json


def _load_radar_input(path: Path):
    raw=json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw,list):
        raise ValueError("radar input must be a JSON array")
    out=[]
    for row in raw:
        if not isinstance(row,dict):
            raise ValueError("radar input rows must be JSON objects")
        row=dict(row)
        row["source_class"]=RadarSourceClass(row["source_class"])
        row["kind"]=RadarKind(row["kind"])
        out.append(RadarObservation(**row))
    return tuple(out)


def main(argv=None):
    p=argparse.ArgumentParser(prog="public-presence-os")
    sub=p.add_subparsers(dest="cmd",required=True)
    v=sub.add_parser("validate"); v.add_argument("--root",default=".")
    m=sub.add_parser("manifest"); m.add_argument("--root",default=".")
    r=sub.add_parser("radar"); r.add_argument("--input",required=True)
    args=p.parse_args(argv)
    if args.cmd=="radar":
        signals=ingest_observations(_load_radar_input(Path(args.input)))
        print(signals_json(signals))
        return 0
    root=Path(args.root).resolve()
    if args.cmd=="validate":
        result=validate_repo(root)
        print(json.dumps({"ok":result.ok,"checks":list(result.checks),"errors":list(result.errors)},indent=2,sort_keys=True))
        return 0 if result.ok else 2
    manifest=build_source_manifest(root)
    print(json.dumps({"manifest":manifest,"manifest_hash":manifest_hash(manifest)},indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
