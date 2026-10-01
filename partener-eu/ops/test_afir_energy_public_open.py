#!/usr/bin/env python3
import datetime as dt, importlib.util, json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCRIPT=ROOT/"partener-eu/ingest/reconcile_afir_energy_public_open.py"
spec=importlib.util.spec_from_file_location("energy_reconcile",SCRIPT)
mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)

fresh={"status":"PASS","sourceUrl":mod.URL,"observedAt":"2026-10-01T14:00:00Z","semanticCheck":"PASS","sha256":"a"*64}
stale=dict(fresh,observedAt="2026-10-01T05:00:00Z")
now=dt.datetime(2026,10,1,15,0,tzinfo=dt.timezone.utc)
assert mod.status(fresh,now)=="OPEN"
assert mod.status(stale,now)=="REVIEW"
assert mod.status({},now)=="REVIEW"
assert mod.status(fresh,dt.datetime(2026,9,27,9,0,tzinfo=dt.timezone.utc))=="UPCOMING"
assert mod.status(fresh,dt.datetime(2026,11,21,10,0,tzinfo=dt.timezone.utc))=="REVIEW"
print(json.dumps({"status":"PASS","fresh":"OPEN","stale":"REVIEW","calendarOnly":"REVIEW"}))
