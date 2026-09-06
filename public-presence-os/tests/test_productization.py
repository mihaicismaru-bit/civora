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
    assert r["checkpoint"]=="CP36"
    assert any(m["id"]=="M01_RADAR" and m["status"]=="CP34_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M02_RESEARCH" and m["status"]=="CP35_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M03_SCORING" and m["status"]=="CP36_MINIMAL_EXECUTABLE_SLICE" for m in r["modules"])
    assert any(m["id"]=="M16_OPERATIONS" and m["status"]=="CP32_PREFLIGHT_MANUAL_LOCKED" for m in r["modules"])
    assert any(m["id"]=="M17_REHEARSAL" and m["status"]=="CP33_CONTROL_PLANE_PASS_PILOT_EXECUTABLE_GAPS_HOLD" for m in r["modules"])

def test_no_paid_or_live_runtime_dependencies():
    txt="\n".join(p.read_text(encoding="utf-8") for p in (ROOT/"src").rglob("*.py"))
    for pat in [r"\brequests\b",r"\bhttpx\b",r"\baiohttp\b",r"selenium",r"playwright",r"boto3",r"stripe"]:
        assert not re.search(pat,txt,re.I)

def test_no_secret_material():
    text_suffixes={".py",".json",".md",".toml",".yml",".yaml",".txt"}
    txt="\n".join(
        p.read_text(encoding="utf-8")
        for p in ROOT.rglob("*")
        if p.is_file() and "dist" not in p.parts and "__pycache__" not in p.parts and p.suffix.lower() in text_suffixes
    )
    patterns = [r"access[_-]?token\\s*[:=]",r"client[_-]?secret\\s*[:=]",r"authorization:\\s*bearer"]
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
