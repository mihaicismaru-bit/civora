from __future__ import annotations

import hashlib
import io
import zipfile
from xml.sax.saxutils import escape
from typing import Any

from research_storage import canonical_json_bytes

ANALYSIS_SCHEMA = "eucons.ai4work_needs_analysis.v0.1"
FIXED_ZIP_TIME = (2026, 8, 31, 0, 0, 0)


class NeedsAnalysisDocxError(ValueError):
    pass


def _text(value: Any) -> str:
    return escape(str(value), {'"': '&quot;'})


def _paragraph(text: str, *, bold: bool = False) -> str:
    run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return (
        "<w:p><w:r>"
        f"{run_props}<w:t xml:space=\"preserve\">{_text(text)}</w:t>"
        "</w:r></w:p>"
    )


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any, *, bold: bool = False) -> str:
        run_props = "<w:rPr><w:b/></w:rPr>" if bold else ""
        return (
            "<w:tc><w:tcPr/><w:p><w:r>"
            f"{run_props}<w:t xml:space=\"preserve\">{_text(value)}</w:t>"
            "</w:r></w:p></w:tc>"
        )

    header_xml = "<w:tr>" + "".join(cell(value, bold=True) for value in headers) + "</w:tr>"
    body_xml = "".join(
        "<w:tr>" + "".join(cell(value) for value in row) + "</w:tr>"
        for row in rows
    )
    return "<w:tbl><w:tblPr/><w:tblGrid/>" + header_xml + body_xml + "</w:tbl>"


def _zip_write(archive: zipfile.ZipFile, name: str, data: str | bytes) -> None:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    payload = data.encode("utf-8") if isinstance(data, str) else data
    archive.writestr(info, payload)


def render_needs_analysis_docx(analysis: dict[str, Any]) -> bytes:
    """Render a deterministic DOCX from the already validated analysis model.

    The renderer never receives respondent-level records. It can only render the
    disclosure-controlled, hash-bound analysis object produced by the final needs
    package gate. The analysis SHA-256 is embedded visibly in the DOCX so the
    package gate can prove byte-to-model binding without relying on Word metadata.
    """
    if not isinstance(analysis, dict):
        raise NeedsAnalysisDocxError("analysis must be an object")
    if analysis.get("schema_version") != ANALYSIS_SCHEMA:
        raise NeedsAnalysisDocxError("unsupported needs-analysis schema")
    if analysis.get("research_id") != "AI4WORK-STEP-NF-RUN-001":
        raise NeedsAnalysisDocxError("research_id mismatch")

    analysis_sha = hashlib.sha256(canonical_json_bytes(analysis)).hexdigest()
    mode = str(analysis.get("evidence_mode", ""))
    title = "AI4WORK STEP – Analiză de nevoi"
    if mode == "TEST_TWIN_NON_EVIDENCE":
        title += " – TEST TWIN NON-EVIDENCE"

    body: list[str] = [
        _paragraph(title, bold=True),
        _paragraph(f"Analysis SHA-256: {analysis_sha}"),
        _paragraph(str(analysis.get("scope_statement", ""))),
        _paragraph("Metodologie", bold=True),
        _paragraph(str(analysis.get("methodology_statement", ""))),
        _paragraph("Eșantion analizat", bold=True),
        _paragraph(
            f"Adulți: {analysis.get('sample', {}).get('adult_n', 0)}; "
            f"angajatori: {analysis.get('sample', {}).get('employer_n', 0)}."
        ),
    ]

    ranking = analysis.get("ranking", {})
    rank_rows = []
    for row in ranking.get("pooled_equal_population_rank", []):
        need_id = str(row.get("need_id", ""))
        dimension = ranking.get("dimensions", {}).get(need_id, {})
        rank_rows.append(
            [
                row.get("rank", ""),
                need_id,
                dimension.get("label", ""),
                row.get("score_display_0_100", ""),
            ]
        )
    body.extend(
        [
            _paragraph("Ierarhia H1–H5 pentru lotul eligibil", bold=True),
            _table(["Rang", "ID", "Nevoie", "Scor 0–100"], rank_rows),
        ]
    )

    qa = analysis.get("adversarial_qa", {})
    body.extend(
        [
            _paragraph("QA adversarial", bold=True),
            _paragraph(
                "Stabilitate: "
                f"{qa.get('overall_stability_label', '')}; "
                f"competing_orders_required={qa.get('competing_orders_required', False)}; "
                f"single_definitive_rank_allowed={qa.get('single_definitive_rank_allowed', False)}."
            ),
        ]
    )

    limitations = analysis.get("limitations", [])
    if limitations:
        body.append(_paragraph("Limitări și limite de interpretare", bold=True))
        for item in limitations:
            body.append(_paragraph(f"• {item}"))

    sources = analysis.get("source_register", {}).get("entries", [])
    if sources:
        body.append(_paragraph("Registrul surselor", bold=True))
        source_rows: list[list[Any]] = []
        for item in sources:
            source_rows.append(
                [
                    item.get("source_id", ""),
                    item.get("publisher", ""),
                    item.get("title", ""),
                    item.get("publication_date", ""),
                    item.get("evidence_role", ""),
                    item.get("url", ""),
                ]
            )
        body.append(
            _table(
                ["ID", "Instituție", "Titlu", "Data", "Rol", "URL"],
                source_rows,
            )
        )

    body.append(
        _paragraph(
            "Acest document nu autorizează inferențe de reprezentativitate sau cauzalitate "
            "dincolo de limitele declarate în modelul canonic al analizei."
        )
    )

    document_xml = (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
        "<w:body>"
        + "".join(body)
        + "<w:sectPr><w:pgSz w:w=\"11906\" w:h=\"16838\"/>"
        "<w:pgMar w:top=\"1440\" w:right=\"1440\" w:bottom=\"1440\" w:left=\"1440\"/>"
        "</w:sectPr></w:body></w:document>"
    )

    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""
    document_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    core = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>AI4WORK STEP – Analiză de nevoi</dc:title>
  <dc:creator>EUCONS AI4WORK research pipeline</dc:creator>
  <cp:lastModifiedBy>EUCONS AI4WORK research pipeline</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">2026-08-31T00:00:00Z</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">2026-08-31T00:00:00Z</dcterms:modified>
</cp:coreProperties>"""
    app = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>EUCONS AI4WORK deterministic renderer</Application>
</Properties>"""

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        _zip_write(archive, "[Content_Types].xml", content_types)
        _zip_write(archive, "_rels/.rels", rels)
        _zip_write(archive, "word/document.xml", document_xml)
        _zip_write(archive, "word/_rels/document.xml.rels", document_rels)
        _zip_write(archive, "docProps/core.xml", core)
        _zip_write(archive, "docProps/app.xml", app)
    return buffer.getvalue()
