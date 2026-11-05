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

# The official catalogue is multi-session: a later solar period must not
# invalidate the two exact 3/2026 reports already proven by the table.
future_row = (
    '<tr><td>Final</td><td>Selectate</td><td>ENERGIE</td>'
    '<td>4</td><td>2027</td>'
    '<td>15.06.2027 - 14.08.2027 (Solar Peste 1MW)</td>'
    '<td>03.11.2027</td>'
    f'<td><a href="{SELECTED}">Descarcă</a></td></tr>'
).encode()
assert module.parse_index(html(REFS).replace(b"</table>", future_row + b"</table>")) == REFS

# Conversely, a changed publication date for the exact 3/2026 session
# is a material identity mismatch and must remain fail-closed.
bad_date = html(REFS).replace(b"03.11.2026", b"04.11.2026", 1)
try:
    module.parse_index(bad_date)
except ValueError:
    pass
else:
    raise AssertionError("Changed exact-session report date was admitted")

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

# A plausible Azure Blob URL cannot self-authorize a download, even when
# it uses the delegated hostname and a matching workbook path.
for target, kind, delegated in [
    (SELECTED, "xlsx", ()),
    ("https://stportalafirprod.blob.core.windows.net/media/media/other/not-from-index.xlsx", "xlsx", tuple(REFS.values())),
    (SELECTED, "html", tuple(REFS.values())),
    (SELECTED, "json", tuple(REFS.values())),
]:
    try:
        module.download_exact(target, 25_000_000, kind, delegated_urls=delegated)
    except ValueError:
        pass
    else:
        raise AssertionError("Unverified delegated source was admitted")

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp) / "first-acquisition"
    def success(url, *args, **kwargs):
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
    assert receipt["official_index"]["fetched_at"]
    assert all(row["fetched_at"] and row["run_id"] == "offline-run-123"
               and row["source_family"] == "AFIR"
               and row["authority_class"] == "OFFICIAL_AFIR_REPORT_INDEX_DELEGATED_DOCUMENT"
               and row["observation_state"] != "OPEN_CALL"
               for row in receipt["documents"])
    assert (Path(root) / "afir-selection-index.raw.html").exists()
    for key in ("open_call_authorized", "publish_authorized", "material_fact_use"):
        assert receipt[key] is False
    assert receipt["publication_effect"] == "NONE"
    # Evidence from one run is immutable, including after a failed replay.
    manifest_before = (root / "manifest.json").read_bytes()
    xlsx_before = (root / "solar-3-2026-selectate.raw.xlsx").read_bytes()
    try:
        module.run(root, "unsafe-replay", "2026-11-05T08:31:00Z")
    except FileExistsError:
        pass
    else:
        raise AssertionError("Existing acquisition evidence directory was overwritten")
    assert (root / "manifest.json").read_bytes() == manifest_before
    assert (root / "solar-3-2026-selectate.raw.xlsx").read_bytes() == xlsx_before

    # If only the first XLSX succeeds and the second times out, no partial
    # original workbook may enter the evidence bundle or appear captured.
    partial_root = Path(tmp) / "second-document-timeout"
    def fail_second(url, *args, **kwargs):
        if url == UNFUNDED:
            raise TimeoutError("second original XLSX unavailable")
        return success(url, *args, **kwargs)
    with patch.object(module, "download_exact", side_effect=fail_second):
        assert module.run(partial_root, "offline-partial-run", "2026-11-05T08:32:00Z") == 2
    partial = json.loads((partial_root / "manifest.json").read_text())
    assert partial["status"] == "FETCH_FAILED" and partial["documents"] == []
    assert "TimeoutError" in partial["error"]
    assert not list(partial_root.glob("*.xlsx"))
    assert (partial_root / "afir-selection-index.raw.html").exists()
    assert partial["open_call_authorized"] is False
    assert partial["publish_authorized"] is False

    # A new failed acquisition has its own manifest and cannot mix in
    # original workbooks from an earlier successful acquisition.
    failed_root = Path(tmp) / "failed-acquisition"
    with patch.object(module, "download_exact", side_effect=ValueError("offline outage")):
        assert module.run(failed_root, "offline-run-failed", "2026-11-05T08:31:00Z") == 2
    failed = json.loads((failed_root / "manifest.json").read_text())
    assert not list(failed_root.glob("*.xlsx"))
    assert failed["status"] == "FETCH_FAILED" and failed["publish_authorized"] is False
    assert failed["observation_state"] != "OPEN_CALL"
print("AFIR solar final selection raw delegated acquisition regressions PASS")
