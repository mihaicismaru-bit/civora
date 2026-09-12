#!/usr/bin/env python3
import io
import json
import zipfile

import interreg_ro_rs_calls_planning as mod

FETCHED_AT = "2026-09-08T00:00:00+00:00"


def fixture_xlsx() -> bytes:
    shared = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<sst xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main' count='5' uniqueCount='5'>
  <si><t>Specific Objective</t></si>
  <si><t>Call 3</t></si>
  <si><t>Indicative launch</t></si>
  <si><t>September 2026</t></si>
  <si><t>PLANNED ONLY</t></si>
</sst>"""
    sheet = """<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'>
  <sheetData>
    <row r='1'><c r='A1' t='s'><v>0</v></c><c r='B1' t='s'><v>1</v></c></row>
    <row r='2'><c r='A2' t='s'><v>2</v></c><c r='B2' t='s'><v>3</v></c><c r='C2' t='s'><v>4</v></c></row>
  </sheetData>
</worksheet>"""
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("xl/sharedStrings.xml", shared)
        zf.writestr("xl/worksheets/sheet1.xml", sheet)
    return out.getvalue()


def healthy_fetcher(url: str):
    if url == mod.INDEX_URL:
        body = b"""
        <html><body>
          <a href='/wp-content/uploads/2026/02/2026-02-23_Calls_planning.xlsx'>23.02.2026 Calls planning timetable</a>
          <a href='https://romania-serbia.net/wp-content/uploads/2026/06/2026-06-09_Calls_planning.xlsx'>09.06.2026 Calls planning timetable</a>
        </body></html>
        """
        return body, {"requested_url": url, "final_url": url, "http_status": 200, "content_type": "text/html"}
    if url.endswith("2026-06-09_Calls_planning.xlsx"):
        body = fixture_xlsx()
        return body, {"requested_url": url, "final_url": url, "http_status": 200, "content_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    raise AssertionError(f"unexpected URL: {url}")


def assert_non_authorizing(evidence):
    assert evidence["observation_state"] == "PLANNED"
    assert evidence["market_intelligence_only"] is True
    assert evidence["planning_evidence_non_authorizing"] is True
    assert evidence["publication_effect"] == "NONE"
    assert evidence["material_admission_ready_for_downstream_review"] is False
    for flag in mod.MATERIAL_FLAGS:
        assert evidence[flag] is False, (flag, evidence[flag])


def main():
    evidence, raws = mod.collect(run_id="fixture-ro-rs-planning", fetched_at=FETCHED_AT, fetcher=healthy_fetcher)
    mod.validate(evidence)
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["lkg_required"] is False
    assert evidence["latest_calendar"]["calendar_date"] == "2026-06-09"
    assert evidence["latest_calendar"]["calendar_url"].endswith("2026-06-09_Calls_planning.xlsx")
    assert evidence["latest_calendar"]["sheet_count"] == 1
    assert evidence["latest_calendar"]["nonempty_cell_count"] == 5
    preview = json.dumps(evidence["latest_calendar"]["rows_preview"], ensure_ascii=False)
    assert "Indicative launch" in preview and "PLANNED ONLY" in preview
    assert evidence["semantic_fingerprint"]
    assert set(raws) == {"index", "workbook"}
    assert_non_authorizing(evidence)

    # A newer off-authority resource must fail closed rather than silently fall
    # back to an older official workbook.
    def off_authority(url: str):
        if url == mod.INDEX_URL:
            return b"""
              <a href='/wp-content/uploads/2026/06/official.xlsx'>09.06.2026 Calls planning timetable</a>
              <a href='https://example.com/fake.xlsx'>10.06.2026 Calls planning timetable</a>
            """, {"requested_url": url, "final_url": url, "http_status": 200, "content_type": "text/html"}
        raise AssertionError("workbook fetch must not happen after authority drift")

    degraded, _ = mod.collect(run_id="fixture-off-authority", fetched_at=FETCHED_AT, fetcher=off_authority)
    mod.validate(degraded)
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["latest_calendar"] is None
    assert degraded["lkg_required"] is True
    assert_non_authorizing(degraded)

    # Transport failure cannot preserve a stale current planning calendar.
    def broken(url: str):
        raise OSError("fixture transport failure")

    degraded2, _ = mod.collect(run_id="fixture-broken", fetched_at=FETCHED_AT, fetcher=broken)
    mod.validate(degraded2)
    assert degraded2["source_health_state"] == "DEGRADED"
    assert degraded2["latest_calendar"] is None
    assert degraded2["semantic_fingerprint"] is None
    assert degraded2["lkg_required"] is True
    assert_non_authorizing(degraded2)

    print("PASS RO-RS planned-calls calendar: latest official XLSX bound; PLANNED never authorizes OPEN/material facts")


if __name__ == "__main__":
    main()
