#!/usr/bin/env python3
"""Idempotently enrich AFIR ingestion for automated dossier generation."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "afir_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

helper_marker = "\ndef main():\n"
helper = r'''
def classify_page(url, title, text):
    """Classify an AFIR object without promoting material facts."""
    value = clean(f"{url} {title} {text[:2500]}").lower()
    if re.search(r"\bdr\s*[-–]?\s*\d{1,3}\b", value) or "schema de energie" in value or "investalim" in value:
        return "INTERVENTION_OR_CALL"
    if any(token in value for token in ("sesiune de depunere", "sesiuni depuneri", "sesiuni primire", "anunțurilor de primire", "anunturilor de primire")):
        return "SESSION"
    if any(token in value for token in ("ghidul și anexele", "ghidul si anexele", "detalii și anexe", "detalii si anexe", "ghid solicitant")):
        return "GUIDE"
    if any(token in value for token in ("apel de proiecte", "intervenția", "interventia", "transfer de cunoștințe", "transfer de cunostinte")):
        return "CALL_CANDIDATE"
    if url.lower().endswith(DOC_EXT):
        return "DOCUMENT"
    return "GENERIC_SOURCE_PAGE"


def linked_evidence(links, base):
    """Return official document/page references discovered on the source page."""
    documents = []
    relevant_pages = []
    doc_seen = set()
    page_seen = set()
    for href, label in links:
        absolute = norm(href, base)
        if not absolute:
            continue
        path = urllib.parse.urlparse(absolute).path.lower()
        entry = {"name": clean(label) or Path(path).name or "Document oficial", "url": absolute}
        if path.endswith(DOC_EXT):
            if absolute not in doc_seen:
                doc_seen.add(absolute)
                documents.append(entry)
            continue
        signal = clean(f"{label} {absolute}").lower()
        if any(token in signal for token in ("sesiun", "ghid", "apel", "finant", "finanț", "dezbatere", "consult", "anunt", "anunț", "calendar", "dr-", "dr ")):
            if absolute not in page_seen:
                page_seen.add(absolute)
                relevant_pages.append(entry)
    return documents[:80], relevant_pages[:80]

'''
if "def classify_page(" in text:
    print("AFIR decision helpers already present")
elif helper_marker in text:
    text = text.replace(helper_marker, "\n" + helper + "def main():\n", 1)
    changed = True
else:
    raise SystemExit("AFIR main marker not found")

old = '''        oldrow = old.get(url) or {}
        changed = bool(oldrow.get("sha256") and oldrow.get("sha256") != sha)
        material_signal = changed and any(k in (text[:150000] + " " + title).lower() for k in MATERIAL_TERMS)
        items.append({
            "url": url,
            "title": title[:500],
            "contentType": ct,
            "bytes": len(data),
            "sha256": sha,
            "textExtracted": bool(text),
            "textChars": len(text),
            "changedFromPrevious": changed,
            "materialChangeCandidate": material_signal,
            "materialFactAction": "RESOLUTION_TASK_ONLY" if material_signal else "NONE",
        })
'''
new = '''        oldrow = old.get(url) or {}
        changed = bool(oldrow.get("sha256") and oldrow.get("sha256") != sha)
        material_signal = changed and any(k in (text[:150000] + " " + title).lower() for k in MATERIAL_TERMS)
        page_class = classify_page(url, title, text)
        document_links, relevant_links = linked_evidence(links, url) if links else ([], [])
        keep_text = page_class in {"INTERVENTION_OR_CALL", "SESSION", "GUIDE", "CALL_CANDIDATE", "DOCUMENT"}
        items.append({
            "url": url,
            "title": title[:500],
            "contentType": ct,
            "bytes": len(data),
            "sha256": sha,
            "observedAt": now(),
            "pageClass": page_class,
            "textExtracted": bool(text),
            "textChars": len(text),
            "textPreview": text[:80000] if keep_text else text[:4000],
            "documentLinks": document_links,
            "relevantLinks": relevant_links,
            "changedFromPrevious": changed,
            "materialChangeCandidate": material_signal,
            "materialFactAction": "RESOLUTION_TASK_ONLY" if material_signal else "NONE",
        })
'''
if new in text:
    print("AFIR decision fields already present")
elif old in text:
    text = text.replace(old, new, 1)
    changed = True
else:
    raise SystemExit("AFIR item append block not found")

if changed:
    PATH.write_text(text, encoding="utf-8")
    print("AFIR decision extraction patch applied")
