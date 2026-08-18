#!/usr/bin/env python3
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[2]
module_path = ROOT / "partener-eu/ingest/build_mipe_enrichment_seeds.py"
spec = importlib.util.spec_from_file_location("mipe_seeds", module_path)
mod = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(mod)

assert mod.useful("https://mfe.gov.ro/ghiduri-") is False
assert mod.useful("https://mfe.gov.ro/ghiduri-ms/") is False
assert mod.useful("https://mfe.gov.ro/ghiduri-ms/investitii-in-infrastructura-cabinetelor-medicilor-de-familie/") is True
print("MIPE enrichment seed quality: PASS")
