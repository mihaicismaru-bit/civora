#!/usr/bin/env python3
"""Offline AFIR delegated selection-report source, ZIP and publication-boundary regressions."""
import importlib.util
import io
import json
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "ingest" / "afir_selection_results_acquire.py"
spec = importlib.util.spec_from_file_location("afir_selection_results_acquire", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

SELECTED = "https://stportalafirprod.blob.core.windows.net/media/media/45pgvsbh/raport-final-de-selectie-solar-peste-1mw-selectate.xlsx"
UNFUNDED = "https://stportalafirprod.blob.core.windows.net/media/media/ftab3hsy/raport-final-de-selectie-solar-peste-1mw-nefinantate.xlsx"
REFS = {"Selectate": SELECTED, "Nefinanțate": UNFUNDED}

def html(rows):
    output = []
    for category, href in rows.items():
        cells = ["Final", category, "ENERGIE", "3", "2026",
                 "15.06.2026 - 14.08.2026 (Solar Peste 1MW)", "03.11.2026"]
        output.append("<tr>" + "".join("<td>" + x + "</td>" for x in cells)
                      + f'<td><a href="{href}">Descarcă</a></td></tr>')
    return ("<table>" + "".join(output) + "</table>").encode()

def xlsx():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("xl/workbook.xml", "<workbook/>")
        z.writestr("xl/worksheets/sheet1.xml", "<sheetData/>")
    return out.getvalue()

assert module.parse_index(html(REFS)) == REFS
assert module.validate_workbook(xlsx()) is True

for bad in [
    {"Selectate": SELECTED},
    {"Selectate": SELECTED, "Nefinanțate": SELECTED},
    {"Selectate": "http://stportalafirprod.blob.core.windows.net/media/media/a/file.xlsx", "Nefinanțate": UNFUNDED},
    {"Selectate": "https://other.example/media/media/a/file.xlsx", "Nefinanțate": UNFUNDED},
    {"Selectate": SELECTED + "?token=untrusted", "Nefinanțate": UNFUNDED},
]:
    try:
        module.parse_index(html(bad))
    except ValueError:
        pass
    else:
        raise AssertionError("Invalid official-index delegation was admitted")

for data in [b"<html>login</html>", b"PK\\x03\\x04damaged"]:
    try:
        module.validate_workbook(data)
    except (ValueError, zipfile.BadZipFile):
        pass
    else:
        raise AssertionError("Invalid delegated XLSX was admitted")

with tempfile.TemporaryDirectory() as root:
    def success(url, *args):
        return (html(REFS), "text/html") if url == module.INDEX_URL else (
            xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    with patch.object(module, "download_exact", side_effect=success):
        assert module.run(root, "offline-run-123", "2026-11-05T08:30:00Z") == 0
    receipt = json.loads((Path(root) / "manifest.json").read_text())
    assert receipt["status"] == "RAW_CAPTURED_PENDING_RECONCILIATION"
    assert {r["category"] for r in receipt["documents"]} == set(module.CATEGORIES)
    assert all(r.get("sha256") and r["status"] == "RAW_FETCHED_NOT_RECONCILED"
               for r in receipt["documents"])
    assert receipt["run_id"] == "offline-run-123"
    assert receipt["official_index"]["sha256"]
    assert (Path(root) / "afir-selection-index.raw.html").exists()
    for key in ("open_call_authorized", "publish_authorized", "material_fact_use"):
        assert receipt[key] is False
    assert receipt["publication_effect"] == "NONE"
    # Availability failure must not authorize facts, even with LKG artifacts present.
    with patch.object(module, "download_exact", side_effect=ValueError("offline outage")):
        assert module.run(root, "offline-run-failed", "2026-11-05T08:31:00Z") == 2
    failed = json.loads((Path(root) / "manifest.json").read_text())
    assert failed["status"] == "FETCH_FAILED" and failed["publish_authorized"] is False
    assert failed["observation_state"] != "OPEN_CALL"
print("AFIR solar final selection raw delegated acquisition regressions PASS")
