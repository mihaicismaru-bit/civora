from __future__ import annotations
import argparse, json, os
from pathlib import Path
from .control import validate_repo, build_source_manifest, manifest_hash
from .radar import RadarObservation, RadarSourceClass, RadarKind, ingest_observations, signals_json
from .meta_live_runtime import (
    MetaEventStore,
    MetaLiveHold,
    MetaReadClient,
    MetaReadRuntime,
    MetaRuntimeConfig,
    environment_presence,
    preflight_report as meta_preflight_report,
)
from .meta_shadow_runtime import MetaShadowStore, run_shadow


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
    mp=sub.add_parser("meta-preflight")
    mp.add_argument("--db",default="var/meta-events.sqlite3")
    mp.add_argument("--live",action="store_true")
    ms=sub.add_parser("meta-sync")
    ms.add_argument("--db",default="var/meta-events.sqlite3")
    sh=sub.add_parser("meta-shadow")
    sh.add_argument("--events-db",default="var/meta-events.sqlite3")
    sh.add_argument("--shadow-db",default="var/meta-shadow.sqlite3")
    cap=sub.add_parser("meta-capabilities"); cap.add_argument("--root",default=".")
    args=p.parse_args(argv)
    if args.cmd=="radar":
        signals=ingest_observations(_load_radar_input(Path(args.input)))
        print(signals_json(signals))
        return 0
    if args.cmd=="meta-preflight":
        report=meta_preflight_report(db_path=args.db,run_live_read=args.live)
        for name,value in report.items():
            print(f"{name:<24} {value}")
        presence=environment_presence()
        missing=[]
        if not presence["META_USER_ACCESS_TOKEN"] and not presence["META_PAGE_ACCESS_TOKEN"]:
            missing.append("META_READ_TOKEN")
        if os.getenv("META_THREADS_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"}:
            if not presence["META_THREADS_ACCESS_TOKEN"]:
                missing.append("META_THREADS_ACCESS_TOKEN")
        if missing:
            print("SETUP".ljust(24)+" MISSING:"+",".join(missing))
        return 0 if report["READ CAPABILITIES"]=="PASS" or not args.live else 2
    if args.cmd=="meta-sync":
        try:
            config=MetaRuntimeConfig.from_env()
            summary=MetaReadRuntime(config,MetaReadClient(),MetaEventStore(args.db)).sync_once()
        except MetaLiveHold as exc:
            print(json.dumps({"state":"HOLD","reason":exc.reason},sort_keys=True))
            return 2
        print(json.dumps({
            "state":summary.state,
            "identities":dict(summary.identities),
            "accepted":summary.accepted,
            "duplicates":summary.duplicates,
            "holds":list(summary.holds),
            "write_count":summary.write_count,
        },indent=2,sort_keys=True))
        return 0 if summary.state=="READ_ONLY_REAL_SYNC_PASS" else 2
    if args.cmd=="meta-shadow":
        report=run_shadow(MetaEventStore(args.events_db),MetaShadowStore(args.shadow_db))
        print(json.dumps(report,indent=2,sort_keys=True))
        return 0
    if args.cmd=="meta-capabilities":
        path=Path(args.root).resolve()/"config"/"meta_capability_matrix_live.json"
        print(json.dumps(json.loads(path.read_text(encoding="utf-8")),indent=2,sort_keys=True))
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
