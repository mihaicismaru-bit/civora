#!/usr/bin/env python3
"""Detect a material PARTENER.EU publish gap without producing routine commits.

Deployment source of truth: deployment/latest.json (successful LKG only).
Repository-source freshness: GitHub commits API scoped to partener-eu/web.
Release authorization: unchanged; this script NEVER deploys or approves Pages.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
LATEST = REPO_ROOT / "partener-eu" / "deployment" / "latest.json"
MARKER = "[PARTENER-DEPLOY-STALLED]"
WINDOW = dt.timedelta(hours=12)
UTC = dt.timezone.utc


def timestamp(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include timezone")
    return parsed.astimezone(UTC)


def assess(last: dict, web_date: str, now: dt.datetime) -> dict:
    deployed = timestamp(last["observed_at"])
    changed = timestamp(web_date)
    if now.tzinfo is None:
        raise ValueError("Current time must include timezone")
    readback = last.get("public_readback") or {}
    is_lkg = (
        last.get("status") == "LIVE"
        and last.get("deploy_outcome") == "success"
        and last.get("readback_outcome") == "success"
        and readback.get("status") == "PASS"
    )
    if not is_lkg:
        raise ValueError("Latest deployment lacks a successful public readback (fail-closed)")
    if deployed > now + dt.timedelta(minutes=5):
        raise ValueError("Deployment timestamp is in the future")
    if changed > now + dt.timedelta(minutes=5):
        raise ValueError("Web commit timestamp is in the future")
    web_ahead = changed > deployed
    age = now - deployed
    return {
        "status": "BLOCKED_STALE_DEPLOYMENT" if web_ahead and age >= WINDOW else "PASS",
        "web_changed_since_deployment": web_ahead,
        "stale_for_hours": round(age.total_seconds() / 3600, 2),
        "lkg_sha": last.get("git_sha"),
        "lkg_utc": deployed.isoformat(),
        "last_web_change_utc": changed.isoformat(),
    }


def api(method: str, suffix: str, token: str, payload: dict | None = None):
    repo = os.environ["GITHUB_REPOSITORY"]
    url = f"https://api.github.com/repos/{repo}/{suffix}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PARTENER-deployment-freshness-watch/1.0",
    }
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=25) as res:
        return json.loads(res.read().decode("utf-8"))


def open_issue(token: str) -> dict | None:
    # Paginate instead of accidentally creating duplicate issues if page 1 fills up.
    for page in range(1, 11):
        rows = api("GET", f"issues?{urlencode({'state':'open','per_page':100,'page':page})}", token)
        if not isinstance(rows, list):
            raise RuntimeError("GitHub issue listing is not a list")
        for row in rows:
            if "pull_request" not in row and str(row.get("title", "")).startswith(MARKER):
                return row
        if len(rows) < 100:
            return None
    raise RuntimeError("Unable to exhaust open issue pagination; refuse duplicate issue")


def issue_body(info: dict, waiting: list[dict]) -> str:
    waiting_lines = "\n".join(
        f"- [run {r['id']}]({r['html_url']}) — {r['status']} since {r['created_at']}"
        for r in waiting[:8]
    ) or "- No waiting Pages run in the API page; inspect workflow/environment protection."
    return (
        "## Automated deployment drift (fail-closed)\n"
        f"- LKG: \\x60{info['lkg_sha']}\\x60, last deploy/readback: {info['lkg_utc']}.\n"
        f"- Latest web change: {info['last_web_change_utc']}.\n"
        f"- LKG age: {info['stale_for_hours']} hours, threshold 12h.\n"
        "- The live site may be missing new funding projections. Do NOT auto-promote facts.\n\n"
        "## Pages waits\n" + waiting_lines + "\n\n"
        "## Recovery\n"
        "1. Check GitHub Actions and the \\x60github-pages\\x60 required-reviewer gate. "
        "Approve only if authorized, or cancel the obsolete waiting run.\n"
        "2. Dispatch PARTENER.EU Pages on latest \\x60main\\x60.\n"
        "3. Require full build, PUBLISHABLE/OPEN safety gates and **public readback PASS**.\n"
        "4. Confirm deployment/latest.json has a newer artifact SHA and evidence.\n\n"
        "Checkpoint: PARTENER-PAGES-FRESHNESS-WATCH; no automatic release, no data mutation."
    ).replace("\\x60", "`")


def waiting_pages(token: str) -> list[dict]:
    result = api("GET", "actions/runs?status=waiting&per_page=100", token)
    rows = result.get("workflow_runs") or []
    if not isinstance(rows, list):
        raise RuntimeError("Invalid waiting runs response")
    return [
        {"id": r["id"], "html_url": r["html_url"],
         "status": r["status"], "created_at": r["created_at"]}
        for r in rows
        if r.get("name") == "PARTENER.EU Pages"
    ]


def self_test() -> None:
    now = timestamp("2026-10-10T16:00:00Z")
    good = {
        "status": "LIVE",
        "deploy_outcome": "success",
        "readback_outcome": "success",
        "public_readback": {"status": "PASS"},
        "git_sha": "demo_sha",
        "observed_at": "2026-10-09T00:00:00Z",
    }
    assert assess(good, "2026-10-09T12:00:00Z", now)["status"] == "BLOCKED_STALE_DEPLOYMENT"
    assert assess(good, "2026-10-08T12:00:00Z", now)["status"] == "PASS"
    recent = {**good, "observed_at": "2026-10-10T10:00:00Z"}
    assert assess(recent, "2026-10-10T12:00:00Z", now)["status"] == "PASS"
    try:
        assess({**good, "readback_outcome": "failure"}, "2026-10-10T12:00:00Z", now)
    except ValueError:
        pass
    else:
        raise AssertionError("Unproven LKG was accepted")
    print("PASS deployment freshness: stale+changed, unchanged, fresh, invalid LKG")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    token = os.environ["GH_TOKEN"]
    if not token or not os.getenv("GITHUB_REPOSITORY"):
        raise RuntimeError("GitHub Actions context required")
    last = json.loads(LATEST.read_text(encoding="utf-8"))
    params = urlencode({"path": "partener-eu/web", "per_page": 1})
    commits = api("GET", f"commits?{params}", token)
    if not isinstance(commits, list) or not commits:
        raise RuntimeError("Latest web commit unavailable (fail-closed)")
    changed = (commits[0].get("commit") or {}).get("committer") or {}
    info = assess(last, changed["date"], dt.datetime.now(UTC))
    info["last_web_sha"] = commits[0]["sha"]
    print(json.dumps(info, ensure_ascii=False, indent=2))
    if args.no_write:
        return 0

    existing = open_issue(token)
    if info["status"] == "BLOCKED_STALE_DEPLOYMENT":
        if existing:
            print(f"EXISTING_OPEN_ISSUE: {existing['html_url']} (no duplicate alert)")
        else:
            waiting = waiting_pages(token)
            created = api("POST", "issues", token, {
                "title": f"{MARKER} P0 — public web behind verified source",
                "body": issue_body(info, waiting),
            })
            print(f"ISSUE_CREATED: {created['html_url']}")
    elif existing:
        # Recovery must be backed by newer SUCCESSFUL LKG with public readback,
        # not merely by the disappearance/cancellation of the waiting run.
        closed = api("PATCH", f"issues/{existing['number']}", token, {
            "state": "closed",
            "state_reason": "completed",
        })
        print(f"ISSUE_CLOSED_AFTER_READBACK_PASS: {closed['html_url']}")
    else:
        print("CURRENT_NO_CHANGE_NO_ALERT")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"FAIL_CLOSED_DEPLOYMENT_FRESHNESS: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(2)
