"""Vercel Python entrypoint for LOCAL NEWS OS vNext."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE = ROOT / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from starlette.applications import Starlette
from starlette.middleware.wsgi import WSGIMiddleware

from production_app import create_production_app_from_env

app = Starlette()
app.mount("/", WSGIMiddleware(create_production_app_from_env()))
