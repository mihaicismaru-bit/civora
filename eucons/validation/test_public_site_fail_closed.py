#!/usr/bin/env python3
from __future__ import annotations

import ast
import importlib.util
import tempfile
from pathlib import Path

EUCONS_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DATA_PATHS = {
    "web/information_architecture.json",
    "services/service_registry.json",
    "canon/commercial_canon.json",
    "evidence/evidence_registry.json",
    "people/people_registry.json",
    "cases/case_study_registry.json",
    "web/jtbd_ux_contract.json",
    "evidence/service_proof_architecture.json",
}
PUBLIC_DATA_KEYS = {"ia", "services", "canon", "evidence", "people", "cases", "ux", "proof"}
PRIVATE_DATA_ROOTS = {"prospects", "leads", "crm", "research", "ops"}


def load_builder():
    path = EUCONS_ROOT / "web" / "build_public_site.py"
    spec = importlib.util.spec_from_file_location("eucons_build_public_site", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def assert_public_source_boundary(builder):
    seen = []
    original_load_json = builder.load_json

    def recording_load_json(path):
        resolved = Path(path).resolve()
        relative = resolved.relative_to(EUCONS_ROOT.resolve()).as_posix()
        seen.append(relative)
        return original_load_json(path)

    builder.load_json = recording_load_json
    try:
        data = builder.load_contracts()
    finally:
        builder.load_json = original_load_json

    assert set(seen) == PUBLIC_DATA_PATHS, f"Public build source allowlist drifted: {seen}"
    assert len(seen) == len(PUBLIC_DATA_PATHS), f"Public build loads a dataset more than once: {seen}"
    assert set(data) == PUBLIC_DATA_KEYS, f"Public build contract keys drifted: {sorted(data)}"
    return data


def assert_no_private_namespace_reads():
    source_path = EUCONS_ROOT / "web" / "build_public_site.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [node.module] if node.module else []
        else:
            modules = []

        for module in modules:
            if any(module == f"eucons.{root}" or module.startswith(f"eucons.{root}.") for root in PRIVATE_DATA_ROOTS):
                raise AssertionError(f"Public builder imports private namespace {module}")

        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.replace("\\", "/").strip("/")
            if value in PRIVATE_DATA_ROOTS or any(value.startswith(f"{root}/") for root in PRIVATE_DATA_ROOTS):
                raise AssertionError(f"Public builder references private EUCONS path {node.value!r}")


def assert_private_payload_not_rendered(builder, public_data):
    sentinel = "EUCONS_PRIVATE_SENTINEL_DO_NOT_PUBLISH"
    private_payload = {
        "sentinel": sentinel,
        "prospect_id": sentinel,
        "selected_service_id": sentinel,
        "selected_opportunity": {"id": sentinel, "title": sentinel},
        "display_name": sentinel,
        "title": sentinel,
        "label": sentinel,
        "items": [{"id": sentinel, "display_name": sentinel, "title": sentinel, "label": sentinel}],
        "records": [{"id": sentinel, "display_name": sentinel, "title": sentinel, "label": sentinel}],
        "prospects": [{"prospect_id": sentinel, "display_name": sentinel, "selected_service_id": sentinel}],
    }
    injected = dict(public_data)
    for key in ("prospects", "client_finder", "leads", "crm", "research", "ops"):
        injected[key] = private_payload

    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "site"
        builder.build_site(target, data=injected)
        rendered = "\n".join(path.read_text(encoding="utf-8") for path in target.rglob("*.html"))
        assert sentinel not in rendered, "Private Client Finder/prospect payload leaked into the public static build"


def main():
    builder = load_builder()
    evidence = {
        "claims": [
            {"claim_class": "SERVICE_OFFERING", "publication_state": "HOLD", "object_ref": "hold_service"},
            {"claim_class": "SERVICE_OFFERING", "publication_state": "PUBLISHABLE", "object_ref": "public_service"},
            {"claim_class": "PROJECT_RESULT", "publication_state": "PUBLISHABLE", "object_ref": "not_a_service"},
        ]
    }
    assert builder.publishable_service_ids(evidence) == {"public_service"}

    people = {
        "people": [
            {"display_name": "Hold Person", "publication_state": "HOLD"},
            {"display_name": "Public Person", "publication_state": "PUBLISHABLE"},
        ]
    }
    assert [p["display_name"] for p in builder.publishable_records(people, "people")] == ["Public Person"]

    cases = {
        "cases": [
            {"title": "Private Case", "publication_state": "HOLD"},
            {"title": "Verified Case", "publication_state": "PUBLISHABLE"},
        ]
    }
    assert [c["title"] for c in builder.publishable_records(cases, "cases")] == ["Verified Case"]

    assert builder.route_file(Path("/tmp/site"), "/") == Path("/tmp/site/index.html")
    assert builder.route_file(Path("/tmp/site"), "/servicii/") == Path("/tmp/site/servicii/index.html")
    assert builder.relative_asset_prefix("/") == ""
    assert builder.relative_asset_prefix("/servicii/") == "../"
    assert builder.relative_asset_prefix("/servicii/example/") == "../../"

    public_data = assert_public_source_boundary(builder)
    assert_no_private_namespace_reads()
    assert_private_payload_not_rendered(builder, public_data)

    print("PASS: E08 public-site fail-closed regressions + private-data boundary")


if __name__ == "__main__":
    main()
