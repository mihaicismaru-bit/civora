#!/usr/bin/env python3
"""Regression for volatile presentation noise in official-source semantic hashes."""
from __future__ import annotations

import hashlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))

from source_registry_probe import semantic_bytes  # noqa: E402


def digest(html: str) -> str:
    semantic = semantic_bytes(html.encode("utf-8"), "text/html; charset=utf-8")
    return hashlib.sha256(semantic).hexdigest()


def main() -> int:
    base = """
    <html><body>
      <article>
        <h1>Centrul Național de Dezvoltare a Învățământului Profesional și Tehnic</h1>
        <p>CNDIPT este organ de specialitate al administrației publice centrale.</p>
        <div class="views-en">92065 views</div>
        <div class="views-ro">92065 de afişări</div>
      </article>
    </body></html>
    """
    counter_only = base.replace("92065 views", "92174 views").replace("92065 de afişări", "92174 de afișări")
    substantive = base.replace(
        "CNDIPT este organ de specialitate al administrației publice centrale.",
        "CNDIPT publică o regulă materială nouă privind eligibilitatea solicitanților.",
    )
    unrelated_number = base.replace(
        "CNDIPT este organ de specialitate al administrației publice centrale.",
        "CNDIPT coordonează 12 programe oficiale de formare.",
    )

    assert digest(base) == digest(counter_only), "bilingual view-count telemetry must not change semantic hash"
    assert digest(base) != digest(substantive), "substantive text changes must remain detectable"
    assert digest(base) != digest(unrelated_number), "ordinary numeric facts must remain detectable"

    normalized = semantic_bytes(counter_only.encode("utf-8"), "text/html").decode("utf-8")
    assert "92174" not in normalized
    assert "afișări" not in normalized.lower()
    assert "views" not in normalized.lower()
    assert "CNDIPT" in normalized

    binary = b"92065 views / 92065 de afisari\x00material"
    assert semantic_bytes(binary, "application/pdf") == binary, "non-HTML sources must remain byte-exact"

    print("PASS source-registry semantic noise regression: bilingual counters ignored; substantive facts preserved")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
