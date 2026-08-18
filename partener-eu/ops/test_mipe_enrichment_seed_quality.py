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

crawler = (ROOT / "partener-eu/ingest/mipe_windows_crawl_v3.py").read_text(encoding="utf-8")
for token in (
    'previous_corpus.get("frontier")',
    '"frontier": frontier',
    '"frontierPersisted": len(frontier)',
    '"resumedFrontier": resumed',
    'if u in previous_urls and not force:',
):
    assert token in crawler, f"missing durable MIPE frontier contract: {token}"

print("MIPE enrichment seed + durable frontier quality: PASS")
