#!/usr/bin/env python3
"""Fail-closed GitHub Pages artifact-visibility barrier (same workflow run only)."""
import argparse
import json
import os
import time
import urllib.request


def exact_visible(payload, expected_name):
    if not isinstance(payload, dict) or not isinstance(payload.get('artifacts'), list):
        return False
    for item in payload['artifacts']:
        if (isinstance(item, dict)
                and item.get('name') == expected_name
                and isinstance(item.get('id'), int) and item['id'] > 0
                and isinstance(item.get('size_in_bytes'), int) and item['size_in_bytes'] > 0
                and item.get('expired') is False):
            return True
    return False


def wait_visible(fetch, sleep, expected_name, attempts, delay):
    if attempts < 1 or delay < 0:
        raise ValueError('invalid retry budget')
    for index in range(attempts):
        try:
            if exact_visible(fetch(), expected_name):
                return index + 1
        except (OSError, ValueError, KeyError, TimeoutError) as error:
            print(f'Artifact metadata unavailable, attempt {index + 1}/{attempts}: {type(error).__name__}', flush=True)
        if index + 1 < attempts:
            sleep(delay)
    return None


def github_fetch(repo, run_id, token):
    url = f'https://api.github.com/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100'
    request = urllib.request.Request(url, headers={
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {token}',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'PARTENER.EU-Pages-Artifact-Barrier/1.0',
    })
    with urllib.request.urlopen(request, timeout=12) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--artifact-name', required=True)
    parser.add_argument('--max-attempts', type=int, default=9)
    parser.add_argument('--delay-seconds', type=float, default=4)
    parser.add_argument('--settle-seconds', type=float, default=3)
    args = parser.parse_args()
    token = os.environ.get('GH_TOKEN', '')
    if (not token or args.repo != os.environ.get('GITHUB_REPOSITORY')
            or args.run_id != os.environ.get('GITHUB_RUN_ID')
            or args.artifact_name != f"github-pages-{os.environ.get('GITHUB_RUN_ATTEMPT', '')}"
            or not args.run_id.isdigit() or int(args.run_id) <= 0
            or not 1 <= args.max_attempts <= 20
            or not 0 <= args.delay_seconds <= 15
            or not 0 <= args.settle_seconds <= 15):
        parser.error('missing credentials or invalid exact-run parameters')
    count = wait_visible(
        lambda: github_fetch(args.repo, args.run_id, token), time.sleep,
        args.artifact_name, args.max_attempts, args.delay_seconds,
    )
    if count is None:
        print('BLOCKED: matching Pages artifact is not visible on this run; no deployment', flush=True)
        return 2
    print(f'Artifact metadata visible on run {args.run_id} after {count} probe(s)', flush=True)
    # Metadata can appear before Pages' own artifact lookup is fully consistent.
    time.sleep(args.settle_seconds)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
