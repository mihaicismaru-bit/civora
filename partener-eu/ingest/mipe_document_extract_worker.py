#!/usr/bin/env python3
"""Resource-isolated PDF/DOCX text extraction worker for the MIPE crawler."""
from __future__ import annotations

import io
import json
import re
import sys
import zipfile


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(io.BytesIO(data))
    chunks: list[str] = []
    total = 0
    for page in reader.pages[:250]:
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        chunks.append(text)
        total += len(text)
        if total > 150000:
            break
    return clean("\n".join(chunks))[:120000]


def parse_docx(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="ignore")
    xml = re.sub(r"</w:p>", "\n", xml)
    return clean(re.sub(r"<[^>]+>", " ", xml))[:120000]


def main() -> int:
    kind = sys.argv[1] if len(sys.argv) > 1 else ""
    data = sys.stdin.buffer.read()
    try:
        if kind == "pdf":
            text = extract_pdf(data)
        elif kind == "docx":
            text = parse_docx(data)
        else:
            return 2
    except Exception:
        text = ""
    sys.stdout.write(json.dumps({"text": text}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
