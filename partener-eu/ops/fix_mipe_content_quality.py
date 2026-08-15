#!/usr/bin/env python3
"""Apply idempotent decision-usefulness and editorial-quality fixes to MIPE ingest."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
text = PATH.read_text(encoding="utf-8")
changed = False

replacements = [
    (
        '''def parse_reader(raw: bytes, target: str) -> dict[str, Any] | None:\n''',
        '''READER_BOILERPLATE = (\n    "skip to main content", "adaugă ca sursă preferată", "adauga ca sursa preferata",\n    "bine ați venit pe site", "bine ati venit pe site", "acest site folosește",\n    "acest site foloseste", "politica de confidențialitate", "politica de confidentialitate",\n    "urmărește-ne", "urmareste-ne", "toate drepturile rezervate", "copyright",\n    "facebook", "linkedin", "youtube", "instagram", "sitemap", "meniu principal",\n)\nPUBLISHABLE_EVENT_KINDS = {\n    "CALL_OPENED", "DEADLINE_EXTENDED", "GUIDE_PUBLISHED", "GUIDE_MODIFIED",\n    "CONSULTATION_OPENED", "RESULTS_PUBLISHED",\n}\nSTATIC_TITLE_HINTS = (\n    "poveste de succes", "povești de succes", "povesti de succes",\n    "politica de coeziune", "alte finanțări și instrumente financiare",\n    "alte finantari si instrumente financiare",\n)\nOFFICIAL_UPDATE_ACTIONS = (\n    "anunț", "anunt", "finanț", "finant", "buget", "investi", "apel",\n    "contract", "plată", "plata", "cerere", "negocier", "reform",\n    "aprobat", "publicat", "lansat", "actualizat", "modificat",\n)\n\n\ndef markdown_plain(value: str) -> str:\n    value = re.sub(r"!\\[[^\\]]*\\]\\([^)]+\\)", " ", value)\n    value = re.sub(r"\\[([^\\]]+)\\]\\([^)]+\\)", r"\\1", value)\n    value = re.sub(r"https?://\\S+", " ", value)\n    value = re.sub(r"[`*_#>|]+", " ", value)\n    return clean_text(value)\n\n\ndef is_boilerplate(value: str) -> bool:\n    plain = markdown_plain(value)\n    low = plain.lower()\n    if len(plain) < 55:\n        return True\n    if any(marker in low for marker in READER_BOILERPLATE):\n        return True\n    alpha = sum(ch.isalpha() for ch in plain)\n    return alpha < max(30, len(plain) // 3)\n\n\ndef best_reader_summary(body_md: str, title: str) -> str:\n    title_terms = {w for w in re.findall(r"[a-zăâîșț0-9]+", title.lower()) if len(w) >= 5}\n    ranked: list[tuple[int, int, str]] = []\n    for index, paragraph in enumerate(re.split(r"\\n\\s*\\n", body_md)):\n        candidate = markdown_plain(paragraph)\n        if is_boilerplate(candidate) or candidate.lower() == title.lower():\n            continue\n        low = candidate.lower()\n        relevance = sum(3 for keyword in FUNDING_KEYWORDS if keyword in low)\n        overlap = sum(1 for term in title_terms if term in low)\n        # Prefer early, title-related explanatory paragraphs, not navigation or footer text.\n        score = relevance + overlap + max(0, 8 - index // 4)\n        ranked.append((score, -index, candidate[:900]))\n    if not ranked:\n        return ""\n    ranked.sort(reverse=True)\n    return ranked[0][2]\n\n\ndef parse_reader(raw: bytes, target: str) -> dict[str, Any] | None:\n''',
        "reader editorial helpers",
    ),
    (
        '''    description = ""\n    for paragraph in re.split(r"\\n\\s*\\n", body_md):\n        candidate = clean_text(paragraph)\n        if len(candidate) >= 70 and not candidate.lower().startswith(("title:", "url source:")):\n            description = candidate[:900]\n            break\n''',
        '''    description = best_reader_summary(body_md, title)\n''',
        "reader summary selection",
    ),
    (
        '''def classify_tag(text: str) -> str:\n    value = text.lower()\n    if "poids" in value or "pids" in value or "incluziune și demnitate socială" in value or "incluziune si demnitate sociala" in value:\n        return "PoIDS"\n    if re.search(r"\\bpeo\\b", value) or "educație și ocupare" in value or "educatie si ocupare" in value:\n        return "PEO"\n    if "pdds" in value or "dezvoltare durabilă" in value or "dezvoltare durabila" in value:\n        return "PDDS"\n    if "pnrr" in value or "redresare și reziliență" in value or "redresare si rezilienta" in value:\n        return "PNRR"\n    if "tranziție justă" in value or "tranzitie justa" in value or re.search(r"\\bptj\\b", value):\n        return "PTJ"\n    if "oportunități de finanțare" in value or "oportunitati de finantare" in value:\n        return "OPORTUNITĂȚI UE"\n    return "MIPE"\n''',
        '''def classify_tag(title: str, url: str = "", context: str = "") -> str:\n    # URL and title outrank the page body because MIPE templates contain links\n    # to every programme and can otherwise contaminate programme classification.\n    primary = f"{title} {url}".lower()\n    secondary = context[:800].lower()\n    if "/ghiduri_peos/" in primary or re.search(r"\\bpeo\\b", primary) or "educație și ocupare" in primary or "educatie si ocupare" in primary:\n        return "PEO"\n    if "/ghiduri_pids/" in primary or "poids" in primary or re.search(r"\\bpids\\b", primary) or "incluziune și demnitate socială" in primary or "incluziune si demnitate sociala" in primary:\n        return "PoIDS"\n    if "/pdds/" in primary or "programul dezvoltare durabilă" in primary or "programul dezvoltare durabila" in primary:\n        return "PDDS"\n    if "tranziție justă" in primary or "tranzitie justa" in primary or re.search(r"\\bptj\\b", primary):\n        return "PTJ"\n    if "programul sănătate" in primary or "programul sanatate" in primary:\n        return "SĂNĂTATE"\n    if "pnrr" in primary or "redresare și reziliență" in primary or "redresare si rezilienta" in primary or "planul-national-de-redresare" in primary:\n        return "PNRR"\n    if re.search(r"\\bpr[ -](?:nord|sud|vest|centru|bucure)", primary) or "program regional" in primary:\n        return "REGIONAL"\n    combined = f"{primary} {secondary}"\n    if re.search(r"\\bpeo\\b", combined):\n        return "PEO"\n    if "poids" in combined or re.search(r"\\bpids\\b", combined):\n        return "PoIDS"\n    if "pdds" in combined:\n        return "PDDS"\n    return "MIPE"\n''',
        "programme classification",
    ),
    (
        '''    if ("prelung" in text and "termen" in text) or ("extind" in text and "termen" in text):\n        return "DEADLINE_EXTENDED"\n''',
        '''    if ("prelung" in text or "extind" in text) and any(token in text for token in ("termen", "perioada", "depunere", "deadline")):\n        return "DEADLINE_EXTENDED"\n''',
        "deadline extension classification",
    ),
    (
        '''    if "ghid" in text and any(token in text for token in ("publicat", "aprobat", "final", "lansat")):\n        return "GUIDE_PUBLISHED"\n''',
        '''    if "ghid" in text and any(token in text for token in ("actualiz", "modific", "revizuit")):\n        return "GUIDE_MODIFIED"\n    if "ghidul solicitantului" in title.lower() or ("ghid" in text and any(token in text for token in ("publicat", "aprobat", "final", "lansat"))):\n        return "GUIDE_PUBLISHED"\n''',
        "guide page classification",
    ),
    (
        '''def item_id(url: str, title: str) -> str:\n''',
        '''def decision_useful(title: str, kind: str, date: dt.date | None, path: str) -> bool:\n    low = title.lower()\n    if any(hint in low for hint in STATIC_TITLE_HINTS):\n        return False\n    if kind in PUBLISHABLE_EVENT_KINDS:\n        return True\n    if kind != "OFFICIAL_UPDATE" or not date:\n        return False\n    if date < now_utc().date() - dt.timedelta(days=180):\n        return False\n    if path.rstrip("/") in {"", "/minister/perioade-de-programare", "/programe-de-finantare/planul-national-de-redresare-si-rezilienta", "/programe-de-finantare/alte-finantari-si-instrumente-financiare"}:\n        return False\n    return any(token in low for token in OFFICIAL_UPDATE_ACTIONS)\n\n\ndef previous_item_useful(item: dict[str, Any]) -> bool:\n    if item.get("source") == "MIPE / MySMIS":\n        return True\n    if item.get("decisionUseful") is True:\n        return True\n    return item.get("kind") in PUBLISHABLE_EVENT_KINDS\n\n\ndef item_id(url: str, title: str) -> str:\n''',
        "decision usefulness gate",
    ),
    (
        '''        documents.append({"name": label or Path(path).name or "Document oficial", "url": url})\n''',
        '''        clean_label = re.sub(r"[`*_#]+", "", clean_text(label)).strip()\n        documents.append({"name": clean_label or Path(path).name or "Document oficial", "url": url})\n''',
        "document label cleanup",
    ),
    (
        '''    summary = description\n    if len(summary) < 50:\n        summary = body[:900]\n    summary = clean_text(summary)[:900]\n    combined = f"{title} {description} {body[:4000]}"\n''',
        '''    if not decision_useful(title, kind, date, path):\n        return None, health\n\n    documents = document_links(parsed.get("links", []), canonical)\n    summary = clean_text(description)\n    if is_boilerplate(summary):\n        summary = ""\n    if not summary:\n        summary = f"Actualizare oficială MIPE: {title}."\n        if documents:\n            summary += f" Pagina include {len(documents)} documente oficiale pentru verificare."\n    summary = summary[:900]\n''',
        "decision-useful summary and document extraction",
    ),
    (
        '''        "tag": classify_tag(combined),\n''',
        '''        "tag": classify_tag(title, canonical, description),\n''',
        "programme tag call",
    ),
    (
        '''        "retrievalTransport": transport,\n        "documents": document_links(parsed.get("links", []), canonical),\n''',
        '''        "retrievalTransport": transport,\n        "decisionUseful": True,\n        "documents": documents,\n''',
        "decision usefulness item marker",
    ),
    (
        '''        normalized.setdefault("documents", [])\n        previous_by_url[old_url] = normalized\n''',
        '''        normalized.setdefault("documents", [])\n        if previous_item_useful(normalized):\n            previous_by_url[old_url] = normalized\n''',
        "previous feed pruning",
    ),
]

for old, new, label in replacements:
    if new in text:
        print(f"MIPE content quality {label}: already applied")
    elif old in text:
        text = text.replace(old, new, 1)
        changed = True
        print(f"MIPE content quality {label}: applied")
    else:
        raise SystemExit(f"Expected MIPE content-quality pattern not found for {label}; refusing blind edit")

if changed:
    PATH.write_text(text, encoding="utf-8")
