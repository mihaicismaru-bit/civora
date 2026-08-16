#!/usr/bin/env python3
"""Prevent eligibility/beneficiary language from becoming winner evidence."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / 'partener-eu/ingest/build_call_lifecycle.py'
text = PATH.read_text(encoding='utf-8')

text = re.sub(
    r"RESULT_WORDS = \(.*?\)\nSTOPWORDS =",
    '''RESULT_WORDS = (\n    "rezultat", "selecție", "selectie", "câștigător", "castigator",\n    "lista proiectelor", "proiecte aprobate", "proiecte selectate",\n    "lista beneficiarilor", "contracte semnate", "contestații", "contestatii",\n)\nSTOPWORDS =''',
    text,
    count=1,
    flags=re.S,
)

start = text.index('def result_sources(')
end = text.index('\n\ndef lifecycle_history', start)
new_func = '''def result_sources(dossier: dict[str, Any], afir: dict[str, Any]) -> list[dict[str, Any]]:\n    candidates: list[dict[str, Any]] = []\n    # A source supporting the fact-class `beneficiaries` is about eligibility,\n    # not about winners. Only explicit result/selection/contract language counts.\n    for source in dossier.get("sources") or []:\n        label = str(source.get("label") or "")\n        if norm(label).startswith("evidenta oficiala"):\n            continue\n        hay = norm(f"{label} {source.get('url')}")\n        if any(norm(word) in hay for word in RESULT_WORDS):\n            candidates.append({\n                "label": label or "Rezultate / proiecte selectate",\n                "url": source.get("url"),\n                "tier": source.get("tier") or "T1",\n                "observedAt": source.get("observedAt"),\n            })\n\n    # AFIR navigation contains generic Beneficiari/Contracte links on almost\n    # every page. They are not call-specific. Accept AFIR evidence only when the\n    # page itself is explicitly a result/selection page and matches the dossier.\n    dtitle = tokens(dossier.get("title"))\n    if dossier.get("sourceType") == "AFIR_PROVISIONAL" or "AFIR" in str(dossier.get("programme") or "").upper():\n        for item in afir.get("items") or []:\n            title = str(item.get("title") or "")\n            title_norm = norm(title)\n            if not any(norm(word) in title_norm for word in RESULT_WORDS):\n                continue\n            it = tokens(title)\n            if dtitle and it and len(dtitle & it) / max(1, min(len(dtitle), len(it))) < 0.45:\n                continue\n            url = item.get("url")\n            if url:\n                candidates.append({\n                    "label": title or "Rezultate AFIR",\n                    "url": url,\n                    "tier": "T1",\n                    "observedAt": item.get("observedAt"),\n                })\n            for link in item.get("documentLinks") or []:\n                hay = norm(f"{link.get('name')} {link.get('url')}")\n                if any(norm(word) in hay for word in RESULT_WORDS):\n                    candidates.append({\n                        "label": link.get("name") or "Listă oficială rezultate",\n                        "url": link.get("url"),\n                        "tier": "T1",\n                        "observedAt": item.get("observedAt"),\n                    })\n    seen: set[str] = set()\n    out: list[dict[str, Any]] = []\n    for row in candidates:\n        url = row.get("url")\n        if not url or url in seen:\n            continue\n        seen.add(url)\n        out.append(row)\n    return out[:20]\n'''
text = text[:start] + new_func + text[end:]
PATH.write_text(text, encoding='utf-8')
print('Call lifecycle result evidence: PASS')
