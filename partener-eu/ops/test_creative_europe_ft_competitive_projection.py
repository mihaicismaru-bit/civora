#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))


def load(name: str):
    path = INGEST / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


exact = load("creative_europe_ft_competitive_exact")
reconcile = load("creative_europe_ft_competitive_reconcile")
admission = load("creative_europe_ft_competitive_admission")
projection = load("creative_europe_ft_competitive_projection")

PARENT = "CREA-CULT-2026-PERFORM-EU"
CID = "49521170"
URL = exact.competitive_url(CID)
OPEN = "31094502"
CLOSED = "31094503"

SEARCH = {
    "results": [{
        "metadata": {
            "identifier": [PARENT],
            "callIdentifier": [PARENT],
            "status": [OPEN],
            "type": ["8"],
            "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
            "deadlineDate": ["2026-10-22T23:59:00.000+0000"],
            "budget": ["1400000"],
            "esST_URL": [URL],
            "title": ["Perform EU"],
        },
        "content": "Perform EU",
        "url": URL,
    }]
}
FACET = {"facets": [{"name": "status", "values": [
    {"rawValue": OPEN, "value": "Open for submission"},
    {"rawValue": CLOSED, "value": "Closed"},
]}]}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    payload = SEARCH if "search" in endpoint and "facet" not in endpoint else FACET
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}


def fake_readback(url, *, max_bytes=None, opener=None):
    assert url == URL
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 64,
        "body_sha256": "b" * 64,
        "verified": True,
    }


source_candidate = {
    "identity_key": f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}",
    "parent_reference": PARENT,
    "semantic_fingerprint": "c" * 64,
}
current = exact.collect_exact(
    PARENT,
    CID,
    run_id="competitive-projection-current",
    fetched_at="2026-09-01T12:00:00+00:00",
    source_candidate=source_candidate,
    post_func=fake_post,
    readback_func=fake_readback,
)
receipt = reconcile.reconcile(current, reconciled_at="2026-09-01T12:01:00Z")
admitted = admission.admit_status(current, receipt, admitted_at="2026-09-01T12:02:00Z")
preview = projection.build_projection(current, admitted)

assert preview["opportunity_class"] == "COMPETITIVE_CASCADING_CALL"
assert preview["display_title"] == "Perform EU"
assert preview["status"] == "OPEN_CALL"
assert preview["status_fact_authorized"] is True
assert preview["confirmed_material_fields"] == ["status"]
assert set(preview["withheld_material_fields"]) == {"deadline", "budget", "eligibility", "participation"}
assert preview["confidence"] == "HIGH_STATUS_ONLY"
assert preview["surface_policy"]["preview_only"] is True
assert preview["surface_policy"]["reader_visibility"] == "INTERNAL_PREVIEW_ONLY"
assert preview["surface_policy"]["robots"] == "noindex,nofollow,noarchive,nosnippet"
assert preview["surface_policy"]["indexable"] is False
assert preview["surface_policy"]["canonical_route_enabled"] is False
assert preview["surface_policy"]["homepage_inclusion"] is False
assert preview["surface_policy"]["search_index_inclusion"] is False
assert preview["surface_policy"]["ask_partener_inclusion"] is False
assert preview["surface_policy"]["sitemap_inclusion"] is False
assert preview["surface_policy"]["structured_data_inclusion"] is False
assert preview["open_call_authorized"] is True
assert preview["deadline_authorized"] is False
assert preview["budget_authorized"] is False
assert preview["eligibility_authorized"] is False
assert preview["participation_authorized"] is False
assert preview["publish_authorized"] is False
assert preview["distribution_authorized"] is False
assert preview["call_alert_authorized"] is False
assert preview["publication_effect"] == "NONE"
assert preview["canonical_corpus_mutation"] is False
serialized = json.dumps(preview, ensure_ascii=False, sort_keys=True)
assert "2026-10-22" not in serialized
assert "1400000" not in serialized
assert "deadline_candidate" not in serialized
assert "budget_candidate" not in serialized

# Admission must stay cryptographically bound to the exact evidence.
tampered_admission = copy.deepcopy(admitted)
tampered_admission["exact_evidence_sha256"] = "d" * 64
try:
    projection.build_projection(current, tampered_admission)
except ValueError:
    pass
else:
    raise AssertionError("competitive product projection accepted unbound admission")

# A broadened admission cannot be smuggled into the preview.
broadened_admission = copy.deepcopy(admitted)
broadened_admission["deadline_authorized"] = True
try:
    projection.build_projection(current, broadened_admission)
except ValueError:
    pass
else:
    raise AssertionError("competitive product projection accepted deadline authorization")

# The projection validator must prevent accidental public-route/search/index escape.
public_escape = copy.deepcopy(preview)
public_escape["surface_policy"]["canonical_route_enabled"] = True
try:
    projection.validate_projection(public_escape)
except ValueError:
    pass
else:
    raise AssertionError("competitive product projection allowed canonical route activation")

search_escape = copy.deepcopy(preview)
search_escape["surface_policy"]["search_index_inclusion"] = True
try:
    projection.validate_projection(search_escape)
except ValueError:
    pass
else:
    raise AssertionError("competitive product projection allowed search inclusion")

print("PASS Creative Europe competitive product projection stays status-only, read-only and NOINDEX")
