#!/usr/bin/env python3
"""Compatibility entry point for the semantic-quality MIPE browser collector.

The dossier-evidence fields are implemented directly in
``mipe_browser_ingest_v2``. This shim intentionally performs no source-file
mutation so collector code, hashes and replay inputs remain stable at runtime.
"""
from mipe_browser_ingest_v2 import main


if __name__ == "__main__":
    raise SystemExit(main())
