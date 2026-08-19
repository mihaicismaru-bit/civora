#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, OSError):
        return
    raise SystemExit(f"{label}: preview failed open")


def main() -> None:
    builder = load_module("e25_builder_failclosed", EUCONS / "web" / "build_public_site.py")
    preview = load_module("e25_preview_failclosed", EUCONS / "preview" / "preview_engine.py")
    contract = json.loads((EUCONS / "preview" / "preview_contract.json").read_text(encoding="utf-8"))

    bad_contract = copy.deepcopy(contract)
    bad_contract["production_deployment_enabled"] = True
    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        must_fail("production deployment activation", lambda: preview.build_preview_receipt(build_dir, bad_contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, contract)
        home = build_dir / "index.html"
        original = home.read_text(encoding="utf-8")
        home.write_text(original.replace('<link rel="canonical" href="https://eucons.ro/">', ''), encoding="utf-8")
        must_fail("missing canonical", lambda: preview.validate_static_build(build_dir, routes, contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, contract)
        home = build_dir / "index.html"
        original = home.read_text(encoding="utf-8")
        home.write_text(original.replace('content="noindex,nofollow"', 'content="index,follow"'), encoding="utf-8")
        must_fail("indexable preview", lambda: preview.validate_static_build(build_dir, routes, contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, contract)
        home = build_dir / "index.html"
        home.write_text(home.read_text(encoding="utf-8").replace('</main>', '<form action="/collect"></form></main>'), encoding="utf-8")
        must_fail("live form collection", lambda: preview.validate_static_build(build_dir, routes, contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, contract)
        css = build_dir / "assets" / "eucons.css"
        css.write_text(css.read_text(encoding="utf-8").replace("@media", "@disabled-media"), encoding="utf-8")
        must_fail("responsive CSS removed", lambda: preview.validate_static_build(build_dir, routes, contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        routes = preview.materialize_preview_support_files(build_dir, contract)
        (build_dir / "robots.txt").unlink()
        must_fail("robots missing", lambda: preview.validate_static_build(build_dir, routes, contract))

    with tempfile.TemporaryDirectory() as td:
        build_dir = Path(td) / "site"
        builder.build_site(build_dir)
        service_page = next(path for path in sorted(build_dir.rglob("index.html")) if path != build_dir / "index.html")
        service_page.unlink()
        must_fail("incomplete route build", lambda: preview.materialize_preview_support_files(build_dir, contract))

    must_fail("repository receipt write", lambda: preview.assert_output_path_safe(EUCONS / "preview" / "unsafe-receipt.json"))
    preview.assert_output_path_safe(Path("/tmp/eucons-e25-preview-receipt.json"))

    commercial = preview.synthetic_commercial_journey()
    if commercial["offer"]["automatic_send_allowed"] is not False:
        raise SystemExit("synthetic journey bypassed offer auto-send hold")
    if commercial["offer"]["pricing"]["amount_minor"] is not None:
        raise SystemExit("synthetic journey invented numeric pricing")

    print("EUCONS E25 Preview Production fail-closed: PASS")


if __name__ == "__main__":
    main()
