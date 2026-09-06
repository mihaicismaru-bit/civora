from __future__ import annotations
from pathlib import Path
import json, re, subprocess, sys, os
from public_presence_os.control import *

ROOT=Path(__file__).resolve().parents[1]

def test_repo_layout():
    r=validate_repo(ROOT)
    assert r.ok, r.errors

def test_platforms_exact():
    p=load_json(ROOT/"config"/"runtime_policy.json")
    assert tuple(p["active_platforms"])==EXPECTED_ACTIVE
    assert p["deferred_platforms"]["LINKEDIN"]=="PRODUCTION_API_ACCESS_REQUIRED"
    assert p["deferred_platforms"]["X"]=="EXCLUDED_WHILE_API_PAID"
    assert p["deferred_platforms"]["BLUESKY"]=="HOLD_ROI"

def test_fail_closed_policy():
    p=load_json(ROOT/"config"/"runtime_policy.json")
    assert validate_policy(p).ok
    assert p["global_kill_switch_engaged"] is True

def test_authority_split():
    p=load_json(ROOT/"config"/"runtime_policy.json")
    assert p["source_authority"]=="GITHUB_EXECUTABLE_SOURCE"
    assert p["evidence_authority"]=="GOOGLE_DRIVE_CHECKPOINT_EVIDENCE"

def test_manifest_deterministic():
    a=build_source_manifest(ROOT); b=build_source_manifest(ROOT)
    assert a==b
    assert manifest_hash(a)==manifest_hash(b)

def test_manifest_hashes_valid():
    m=build_source_manifest(ROOT)
    assert m["files"]
    assert all(HEX64.fullmatch(v) for v in m["files"].values())

def test_registry_unique_ids():
    r=load_json(ROOT/"config"/"module_registry.json")
    ids=[m["id"] for m in r["modules"]]
    assert len(ids)==len(set(ids))
    assert r["checkpoint"]=="CP52"
    assert any(m["id"]=="M01_RADAR" and m["status"]=="CP34_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M02_RESEARCH" and m["status"]=="CP35_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M03_SCORING" and m["status"]=="CP36_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M04_MASTER_DRAFT" and m["status"]=="CP37_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M05_NATIVE_ADAPT" and m["status"]=="CP38_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M06_VISUAL" and m["status"]=="CP49_IDENTITY_V2_RUNTIME_ACTIVE_EXACT_BINDING" for m in r["modules"])
    assert any(m["id"]=="M07_QA" and m["status"]=="CP49_IDENTITY_V2_EXACT_QA_GATE_ACTIVE" for m in r["modules"])
    assert any(m["id"]=="M08_QUEUE" and m["status"]=="CP43_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M09_PUBLISHER" and m["status"]=="CP44_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M10_ANALYTICS" and m["status"]=="CP45_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M11_LEARNING" and m["status"]=="CP46_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M12_APPROVAL" and m["status"]=="CP42_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M13_RIGHTS" and m["status"]=="CP39_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M14_EXPERIMENTS" and m["status"]=="CP47_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M16_OPERATIONS" and m["status"]=="CP32_PREFLIGHT_MANUAL_LOCKED" for m in r["modules"])
    assert any(m["id"]=="M17_REHEARSAL" and m["status"]=="CP33_CONTROL_PLANE_PASS_PILOT_VALIDATION_GATES_HOLD" for m in r["modules"])
    assert any(m["id"]=="M18_VISUAL_IDENTITY" and m["status"]=="CP49_V2_RUNTIME_ACTIVE_LOCAL_ONLY" for m in r["modules"])
    assert any(m["id"]=="M19_META_ADAPTERS" and m["status"]=="CP50_OFFLINE_REQUEST_COMPILER" for m in r["modules"])
    assert any(m["id"]=="M20_META_CONNECTIONS" and m["status"]=="CP51_SECRET_REFERENCE_PROFILE_VAULT_LOCAL_ONLY" for m in r["modules"])
    assert any(m["id"]=="M21_META_PREFLIGHT" and m["status"]=="CP52_SYNTHETIC_PROVISIONING_READBACK_LOCAL_ONLY" for m in r["modules"])

def test_reimplementation_priority_closes_executable_source_backlog():
    p=load_json(ROOT/"config"/"reimplementation_priority.json")
    assert p["checkpoint"]=="CP52"
    states={row["module_id"]:row["state"] for row in p["order"]}
    assert states["M06_VISUAL"]=="CP49_IDENTITY_V2_RUNTIME_ACTIVE_EXACT_BINDING"
    assert states["M07_QA"]=="CP49_IDENTITY_V2_EXACT_QA_GATE_ACTIVE"
    assert states["M11_LEARNING"]=="CP46_MINIMAL_EXECUTABLE_SLICE"
    assert states["M14_EXPERIMENTS"]=="CP47_MINIMAL_EXECUTABLE_SLICE"
    assert states["M18_VISUAL_IDENTITY"]=="CP49_V2_RUNTIME_ACTIVE_LOCAL_ONLY"
    assert states["M19_META_ADAPTERS"]=="CP50_OFFLINE_REQUEST_COMPILER"
    assert states["M20_META_CONNECTIONS"]=="CP51_SECRET_REFERENCE_PROFILE_VAULT_LOCAL_ONLY"
    assert states["M21_META_PREFLIGHT"]=="CP52_SYNTHETIC_PROVISIONING_READBACK_LOCAL_ONLY"
    assert p["next"]=="CP53_META_OPERATOR_PROVISIONING_PACKET_OFFLINE_CHECKLIST"

def test_no_paid_or_live_runtime_dependencies():
    txt="\n".join(p.read_text(encoding="utf-8") for p in (ROOT/"src").rglob("*.py"))
    forbidden=("requests","httpx","aiohttp","selenium","playwright","boto3","stripe")
    for package in forbidden:
        pat=rf"^\s*(?:from\s+{re.escape(package)}(?:\.|\s)|import\s+{re.escape(package)}(?:\.|\s|$))"
        assert not re.search(pat,txt,re.I|re.M)

def test_no_secret_material():
    text_suffixes={".py",".json",".md",".toml",".yml",".yaml",".txt"}
    txt="\n".join(
        p.read_text(encoding="utf-8")
        for p in ROOT.rglob("*")
        if p.is_file() and "dist" not in p.parts and "__pycache__" not in p.parts and p.suffix.lower() in text_suffixes
    )
    patterns = [r"access[_-]?token\s*[:=]",r"client[_-]?secret\s*[:=]",r"authorization:\s*bearer"]
    for pat in patterns:
        assert not re.search(pat,txt,re.I)

def test_build_is_reproducible(tmp_path):
    env=os.environ.copy(); env["PYTHONPATH"]=str(ROOT/"src")
    subprocess.run([sys.executable,str(ROOT/"scripts"/"build_release.py")],check=True,capture_output=True,text=True,env=env)
    zips=sorted((ROOT/"dist").glob("public-presence-os-cp30-*.zip"))
    assert zips
    first=zips[-1].read_bytes()
    subprocess.run([sys.executable,str(ROOT/"scripts"/"build_release.py")],check=True,capture_output=True,text=True,env=env)
    second=zips[-1].read_bytes()
    assert first==second

def test_cli_validate():
    env=os.environ.copy(); env["PYTHONPATH"]=str(ROOT/"src")
    p=subprocess.run([sys.executable,"-m","public_presence_os.cli","validate","--root",str(ROOT)],capture_output=True,text=True,env=env)
    assert p.returncode==0
    assert json.loads(p.stdout)["ok"] is True

def test_ci_has_no_deploy():
    t=(ROOT/".github"/"workflows"/"public-presence-os-ci.yml").read_text()
    assert "workflow_dispatch" in t
    assert "pytest" in t
    for bad in ["deploy","vercel","pages","aws","publish-package"]:
        assert bad not in t.lower()
