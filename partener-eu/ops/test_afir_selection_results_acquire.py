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

# The official HTML catalogue may contain hidden (stale or forged) rows.
# Neither hidden rows nor embedded script/template text may establish the
# 3/2026 report pair or override its exact delegated XLSX identity.
valid_index = html(REFS)
conflicting_hidden_row = (
    '<tr><td>Final</td><td>Selectate</td><td>ENERGIE</td>'
    '<td>3</td><td>2026</td>'
    '<td>15.06.2026 - 15.08.2026 (Solar Peste 1MW)</td>'
    '<td>03.11.2026</td>'
    f'<td><a href="{SELECTED}">Fake report</a></td></tr>'
).encode()
for wrapper_start, wrapper_end in (
    ('<div hidden>', '</div>'),
    ('<div inert>', '</div>'),
    ('<div aria-hidden="true">', '</div>'),
    ('<div style="display: none !important">', '</div>'),
    ('<div style="visibility: hidden">', '</div>'),
    ('<div style="opacity:0">', '</div>'),
    ('<div style="content-visibility:hidden">', '</div>'),
    ('<div style="display:none" style="display:block">', '</div>'),
    ('<template>', '</template>'),
    ('<noscript>', '</noscript>'),
    ('<details>', '</details>'),
    ('<div popover>', '</div>'),
):
    hidden = (wrapper_start.encode() + conflicting_hidden_row +
              wrapper_end.encode())
    assert module.parse_index(valid_index.replace(b"</table>", hidden + b"</table>")) == REFS
    try:
        module.parse_index(b"<table>" + hidden + b"</table>")
    except ValueError:
        pass
    else:
        raise AssertionError(f"Hidden AFIR report row was accepted: {wrapper_start}")

# Hidden text within an otherwise visible date cell must not compensate for
# a conflicting official period or create an artificial quality match.
for wrapper_start, wrapper_end in (
    ('<span hidden>', '</span>'),
    ('<script>', '</script>'),
    ('<template>', '</template>'),
    ('<span style="display:none">', '</span>'),
):
    injected = (
        b"15.06.2026 - 15.08.2026 "
        + wrapper_start.encode()
        + b"15.06.2026 - 14.08.2026 "
        + wrapper_end.encode()
    )
    payload = valid_index.replace(b"15.06.2026 - 14.08.2026 ", injected, 1)
    try:
        module.parse_index(payload)
    except ValueError:
        pass
    else:
        raise AssertionError(f"Hidden AFIR period repaired a conflicting date: {wrapper_start}")

# Two href attributes in a source anchor cannot collapse into one accepted link.
dupe_anchor = (f'<a href="{SELECTED}" href="{UNFUNDED}">Descarcă</a>').encode()
dupe_payload = valid_index.replace(
    (f'<a href="{SELECTED}">Descarcă</a>').encode(), dupe_anchor, 1
)
try:
    module.parse_index(dupe_payload)
except ValueError:
    pass
else:
    raise AssertionError("Duplicate delegated XLSX href was accepted")

# An ordinary visible wrapper and nested emphasis preserve legitimate rows.
assert module.parse_index(valid_index.replace(
    b"<table>", b"<table><tbody>", 1
).replace(b"</table>", b"</tbody></table>", 1)) == REFS

assert module.validate_workbook(xlsx()) is True

# Exact MIME recorded in original live PR preflight 42442574151.
for kind, accepted in (
    ("html", ("text/html; charset=utf-8", "APPLICATION/XHTML+XML")),
    ("xlsx", ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
              "APPLICATION/VND.OPENXMLFORMATS-OFFICEDOCUMENT.SPREADSHEETML.SHEET; charset=binary")),
):
    for header in accepted:
        assert module.accepted_media_type(kind, header), (kind, header)
for kind, rejected in (
    ("html", ("text/plain; filename=index.html", "application/json; note=text/html",
              "text/html-fake", "application/pdf", "application/octet-stream")),
    ("xlsx", ("text/html; filename=report.xlsx", "application/json; note=report.xlsx",
              "application/pdf", "application/octet-stream", "application/zip",
              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet-fake")),
):
    for header in rejected:
        assert not module.accepted_media_type(kind, header), (kind, header)

class FakeResponse:
    status = 200
    def __init__(self, url, raw, ctype, encoding="identity", length=None):
        self.url, self.raw = url, raw
        self.headers = {"Content-Type": ctype, "Content-Encoding": encoding,
                        "Content-Length": str(len(raw)) if length is None else length}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def geturl(self):
        return self.url
    def read(self, max_size):
        return self.raw[:max_size]

class FakeOpener:
    def __init__(self, response):
        self.response = response
    def open(self, request, timeout):
        assert request.full_url == self.response.url and timeout == 25
        return self.response

for target, kind, raw, good, bad in (
    (module.INDEX_URL, "html", html(REFS), "text/html; charset=utf-8",
     ("text/plain; filename=notice.html", "application/json; hint=text/html", "text/html-fake")),
    (SELECTED, "xlsx", xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
     ("application/pdf", "application/octet-stream", "text/html; filename=selected.xlsx")),
):
    allowed_delegation = tuple(REFS.values()) if kind == "xlsx" else ()
    def transport(mime, encoding="identity", length=None):
        mock = FakeResponse(target, raw, mime, encoding, length)
        with patch.object(module.urllib.request, "build_opener", return_value=FakeOpener(mock)):
            return module.download_exact(target, 5_000_000, kind, delegated_urls=allowed_delegation)
    assert transport(good)[0] == raw
    for mime in bad:
        try:
            transport(mime)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Forged {kind} media type admitted: {mime}")
    for encoding in ("gzip", "br", "identity, gzip"):
        try:
            transport(good, encoding=encoding)
        except ValueError:
            pass
        else:
            raise AssertionError("Compressed or ambiguous raw transport admitted")
    try:
        transport(good, length=str(len(raw) + 1))
    except ValueError:
        pass
    else:
        raise AssertionError("Truncated AFIR body admitted")

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

# A contradictory *same-session* date must not be silently skipped merely
# because the valid pair is also present: 3/2026 would become ambiguous.
conflicting_period_row = (
    '<tr><td>Final</td><td>Selectate</td><td>ENERGIE</td>'
    '<td>3</td><td>2026</td>'
    '<td>15.06.2026 - 15.08.2026 (Solar Peste 1MW)</td>'
    '<td>03.11.2026</td>'
    f'<td><a href="{SELECTED}">Descarcă</a></td></tr>'
).encode()
for payload in (
    html(REFS).replace(b"</table>", conflicting_period_row + b"</table>"),
    html(REFS).replace(b"14.08.2026", b"15.08.2026", 1),
):
    try:
        module.parse_index(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("Contradictory AFIR 3/2026 solar period was admitted")

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
