from __future__ import annotations
import argparse, json
from pathlib import Path
from public_presence_os.rehearsal import run_synthetic_rehearsal, report_dict


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",default=".")
    p.add_argument("--output")
    args=p.parse_args()
    root=Path(args.root).resolve()
    payload=report_dict(run_synthetic_rehearsal(root))
    text=json.dumps(payload,indent=2,sort_keys=True)+"\n"
    if args.output:
        out=Path(args.output); out.parent.mkdir(parents=True,exist_ok=True); out.write_text(text,encoding="utf-8")
    print(text,end="")
    return 0 if payload["control_plane_state"]=="PASS_SYNTHETIC_CONTROL_PLANE" else 2

if __name__=="__main__":
    raise SystemExit(main())
