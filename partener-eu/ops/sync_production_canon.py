#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "partener-eu" / "PRODUCTION_CANON.json"
DEPLOYMENT = ROOT / "partener-eu" / "deployment" / "latest.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def verified_live_sha(deployment: dict) -> str:
    if deployment.get("status") != "LIVE":
        raise SystemExit("deployment record is not LIVE")
    if deployment.get("readback_outcome") != "success":
        raise SystemExit("deployment readback did not succeed")
    if (deployment.get("public_readback") or {}).get("status") != "PASS":
        raise SystemExit("public readback is not PASS")
    sha = str(deployment.get("git_sha") or "").strip()
    if not sha:
        raise SystemExit("deployment record has no git_sha")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    deployment = load(DEPLOYMENT)
    canon = load(CANON)
    sha = verified_live_sha(deployment)

    if args.check:
        if canon.get("liveArtifactGitSha") != sha:
            raise SystemExit("production canon does not match verified live artifact")
        if canon.get("productionRecord") != "partener-eu/deployment/latest.json":
            raise SystemExit("productionRecord is not canonical")
        if canon.get("productionRecordStatus") != "LIVE":
            raise SystemExit("productionRecordStatus is not LIVE")
        print("PASS production canon matches verified live artifact")
        return 0

    canon["liveArtifactGitSha"] = sha
    canon["productionRecord"] = "partener-eu/deployment/latest.json"
    canon["productionRecordStatus"] = "LIVE"
    encoded = json.dumps(canon, ensure_ascii=False, indent=2) + "\n"
    before = CANON.read_text(encoding="utf-8")
    if encoded != before:
        CANON.write_text(encoded, encoding="utf-8")
        print("UPDATED production canon to " + sha)
    else:
        print("CURRENT production canon already matches " + sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
