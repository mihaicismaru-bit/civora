#!/usr/bin/env python3
"""Deterministic P10 guard for the public frontpage freeze incident.

This test is intentionally narrow: it prevents reintroduction of the two script
patterns that caused the 2026-08-12 main-thread render loop while keeping the
runtime dependency-free.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
index = (WEB / "index.html").read_text(encoding="utf-8")
public_copy = (WEB / "public-product-copy-v1.js").read_text(encoding="utf-8")

errors = []

# PR #23 module remains in the repository for auditability but must not be
# loaded publicly until it has browser-level performance acceptance evidence.
if 'src="public-ux-optimization-v1.js' in index:
    errors.append("public-ux-optimization-v1.js is loaded by public index")
if 'href="public-ux-optimization-v1.css' in index:
    errors.append("public-ux-optimization-v1.css is loaded by public index")

# The copy-polish layer previously observed characterData globally while also
# mutating text nodes, creating a self-triggering microtask loop. Keep it finite.
if "new MutationObserver" in public_copy:
    errors.append("public-product-copy-v1.js contains a global MutationObserver")
if "characterData:true" in public_copy.replace(" ", ""):
    errors.append("public-product-copy-v1.js observes characterData")

# Copy layer must still execute at least once and expose its diagnostic version.
if "polish();" not in public_copy:
    errors.append("public copy polish pass missing")
if "PARTENER_PUBLIC_COPY" not in public_copy:
    errors.append("public copy diagnostic export missing")

if errors:
    raise SystemExit("FAIL frontend regression guard: " + "; ".join(errors))
print("PASS frontend regression guard")
