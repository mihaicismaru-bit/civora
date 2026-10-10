#!/usr/bin/env python3
"""Read-only production RPM lead API health; never submits customer information."""
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT="https://partener-rpm-leads.mihai-cismaru.workers.dev/health"

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--url",default=DEFAULT)
    args=parser.parse_args()
    if not args.url.startswith("https://") or not args.url.endswith("/health"):
        raise ValueError("Read-only HTTPS /health URL required")
    req=Request(args.url,headers={"User-Agent":"PARTENER-RPM-READONLY-HEALTH/1.0","Accept":"application/json"},method="GET")
    try:
        with urlopen(req,timeout=20) as response:
            status=response.status
            data=json.loads(response.read(2048))
    except HTTPError as exc:
        status=exc.code
        try:data=json.loads(exc.read(2048))
        except Exception:data={}
    except URLError as exc:
        print(f"BLOCKED_NETWORK_UNREACHABLE: {type(exc).__name__}",file=sys.stderr)
        return 2
    if status==200 and data.get("ok") is True and data.get("status")=="READY":
        print("PASS_READONLY_D1_TABLE_HEALTH — not proof of real lead INSERT")
        return 0
    if status==405:
        print("BLOCKED_HEALTH_ROUTE_NOT_DEPLOYED — runtime may precede repository source",file=sys.stderr)
    else:
        print(f"BLOCKED_RPM_D1_HEALTH status={status} state={str(data.get('status') or data.get('error') or 'UNKNOWN')[:80]}",file=sys.stderr)
    return 2

if __name__=="__main__":
    try:sys.exit(main())
    except Exception as exc:
        print(f"BLOCKED_RPM_HEALTH_UNVERIFIED: {type(exc).__name__}: {str(exc)[:100]}",file=sys.stderr)
        sys.exit(2)
