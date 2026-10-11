#!/usr/bin/env python3
"""Regression guard for the 2026-10 public UX fixes.

- in-app views have URLs (History API) and calls with a static page open it;
- the Ask page loads the compact ask-index.js, with the full data as fallback;
- the homepage puts open calls before the Română pentru Muncă promo;
- actionable static dossiers carry the Euroconsult help CTA, closed/unverified ones do not.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "partener-eu" / "web"
OPS = ROOT / "partener-eu" / "ops"


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, OPS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


# 1. routing
app = (WEB / "app.js").read_text(encoding="utf-8")
for token in ("function stateFromUrl()", "history[replace?'replaceState':'pushState']", "addEventListener('popstate'", "PARTENER_DOSSIER_ROUTES", "function searchCalls(", "e.preventDefault();go({route:x.dataset.r"):
    assert token in app, f"app.js missing {token}"
assert "JSON.stringify(c).toLowerCase().includes(S.q.toLowerCase())" not in app, "explorer regressed to exact-phrase search"
index = (WEB / "index.html").read_text(encoding="utf-8")
assert 'src="dossier-routes.js' in index, "dossier routes not loaded on the homepage"
assert index.index("dossier-routes.js") < index.index("public-heavy-loader-v1.js")

# 2. Ask data path
loader = (WEB / "public-heavy-loader-v1.js").read_text(encoding="utf-8")
assert "loadScript('ask-index.js" in loader, "Ask does not load the compact index"
assert loader.index("ask-index.js") < loader.index("loadDecisionData(),loadCanonicalCalls()"), "full data must only be the fallback"
ask = (WEB / "ask-partener-v2.js").read_text(encoding="utf-8")
for token in ("window.PARTENER_ASK_INDEX", "window.PARTENER_DECISION_PRODUCTS", "window.PARTENER_MIPE_CANONICAL_CALLS", "ROUTES()[id]", "get('q')", "P.dossiers.filter(publishable)", "function conceptGroups(", "if(topicGroups&&!topicMatched)"):
    assert token in ask, f"ask-partener-v2.js missing {token}"

# word matching: whole word for short tokens, word prefix otherwise, never mid-word
import re as _re
has_src = _re.search(r"const has=\(text,t\)=>[^;]+;", ask).group(0)
check = subprocess.run(["node", "-e", has_src + """
const ok=[has('firmei mici','firm'),!has('sunt confirmate','firma'),has('apa potabila','apa'),!has('apare des','apa'),has('fotovoltaice','fotovoltaic')];
process.exit(ok.every(Boolean)?0:1)"""], capture_output=True)
assert check.returncode == 0, "Ask word matching regressed"

# 3. homepage order + immediate render (no delayed layout jump)
concierge = (WEB / "home-concierge-vnext.js").read_text(encoding="utf-8")
assert concierge.index('class="conciergeSection conciergeOpen"') < concierge.index('class="conciergeService"'), "promo is above open calls"
assert "setTimeout(render,760)" not in concierge and "setTimeout(render,560)" not in concierge, "concierge render is delayed again"

# 4. help CTA policy
builder = load("build_public_static_pages")
assert builder.help_cta({"status": "OPEN"}, "/dosare/x/").count("eucons.ro/evaluare-proiect/") == 1
assert "utm_campaign=x" in builder.help_cta({"status": "EXPECTED"}, "/dosare/x/")
for status in ("CLOSED", "REVIEW", "DISCOVERED", ""):
    assert builder.help_cta({"status": status}, "/dosare/x/") == "", status

# 5. ask index builder produces the fields ask-partener-v2.js reads
with tempfile.TemporaryDirectory() as tmp:
    web = Path(tmp) / "partener-eu" / "web"
    ops = Path(tmp) / "partener-eu" / "ops"
    web.mkdir(parents=True); ops.mkdir(parents=True)
    (ops / "build_ask_index.js").write_text((OPS / "build_ask_index.js").read_text(encoding="utf-8"), encoding="utf-8")
    dossier = {"id": "d1", "title": "Apel Test", "status": "OPEN", "publicationState": "PUBLISHABLE", "sources": [{"url": "https://x.ro", "tier": "T1", "label": "S"}],
               "quickFacts": [{"label": "Termen", "value": "1 ianuarie 2030", "confidence": "CONFIRMED"}, {"label": "Altceva", "value": "zgomot"}],
               "sections": [{"title": "Activități", "items": ["Utilaje și echipamente", "utilaje"]}, {"title": "Ce nu este încă confirmat", "items": ["Bugetul"]}]}
    (web / "decision-products.js").write_text("window.PARTENER_DECISION_PRODUCTS=" + json.dumps({"dossiers": [dossier, {"id": "d2", "title": "Provizoriu", "publicationState": "PROVISIONAL_FAIL_CLOSED"}]}) + ";", encoding="utf-8")
    (web / "mipe-canonical-calls.js").write_text("window.PARTENER_MIPE_CANONICAL_CALLS=" + json.dumps({"calls": [{"id": "c1", "activities": ["Digitalizare"]}]}) + ";", encoding="utf-8")
    subprocess.run(["node", str(ops / "build_ask_index.js")], check=True, capture_output=True)
    raw = (web / "ask-index.js").read_text(encoding="utf-8")
    payload = json.loads(raw[len("window.PARTENER_ASK_INDEX="):].rstrip().rstrip(";"))
    assert [x["id"] for x in payload["dossiers"]] == ["d1"], "non-publishable dossiers must not reach Ask"
    d = payload["dossiers"][0]
    assert d["sectionTitles"] == ["activitati", "ce nu este inca confirmat"]
    assert "utilaje:1" in d["sectionVocab"].split(","), d["sectionVocab"]
    assert [s["title"] for s in d["sections"]] == ["Ce nu este încă confirmat"], "only 'not confirmed' sections are kept verbatim"
    assert [q["label"] for q in d["quickFacts"]] == ["Termen"]
    assert d["sources"][0]["url"] == "https://x.ro"
    assert payload["calls"][0]["activitiesText"] == "digitalizare"

print("PASS public UX routing, Ask index, homepage order and help CTA")
