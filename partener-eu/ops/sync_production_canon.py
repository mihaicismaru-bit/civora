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


def expected_sha(deployment: dict) -> str:
    if deployment.get("status") != "LIVE":
        raise SystemExit("deployment/latest.json is not LIVE")
    if deployment.get("readback_outcome") != "success":
        raise SystemExit("deployment/latest.json readback_outcome is not success")
    if (deployment.get("public_readback") or {}).get("status") != "PASS":
        raise SystemExit("deployment/latest.json public_readback is not PASS")
    sha = str(deployment.get("git_sha") or "").strip()
    if not sha:
        raise SystemExit("deployment/latest.json has no git_sha")
    return sha


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    deployment = load(DEPLOYMENT)
    canon = load(CANON)
    sha = expected_sha(deployment)

    if args.check:
        if canon.get("liveArtifactGitSha") != sha:
            raise SystemExit(
                "production canon drift: "
                + str(canon.get("liveArtifactGitSha"))
                + " != "
                + sha
            )
        if canon.get("productionRecord") != "partener-eu/deployment/latest.json":
            raise SystemExit("productionRecord drift")
        if canon.get("productionRecordStatus") != "LIVE":
            raise SystemExit("productionRecordStatus drift")
        print("PASS production canon matches verified Pages LKG")
        return 0

    changed = False
    if canon.get("liveArtifactGitSha") != sha:
        canon["liveArtifactGitSha"] = sha
        changed = True
    if canon.get("productionRecord") != "partener-eu/deployment/latest.json":
        canon["productionRecord"] = "partener-eu/deployment/latest.json"
        changed = True
    if canon.get("productionRecordStatus") != "LIVE":
        canon["productionRecordStatus"] = "LIVE"
        changed = True

    if changed:
        CANON.write_text(json.dumps(canon, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("UPDATED production canon to verified Pages LKG " + sha)
    else:
        print("CURRENT production canon already matches verified Pages LKG " + sha)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
