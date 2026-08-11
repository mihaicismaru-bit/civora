#!/usr/bin/env python3
import json, pathlib, tempfile
from p10_validate import atomic_json, static_frontend_checks

with tempfile.TemporaryDirectory() as d:
    p=pathlib.Path(d)/'state.json'
    obj={'schema_version':1,'sources':{'A':{'sha256':'abc'}}}
    atomic_json(p,obj)
    assert json.loads(p.read_text())==obj
checks=static_frontend_checks()
assert all(x['pass'] for x in checks), checks
print(json.dumps({'atomic_state_write':'PASS','frontend_static_checks':f"{sum(x['pass'] for x in checks)}/{len(checks)} PASS"},indent=2))
