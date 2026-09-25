#!/usr/bin/env python3
"""Regression guard: homepage RPM promo reuses the exact service-page hero image."""
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
page=(WEB/"romana-pentru-munca"/"index.html").read_text(encoding="utf-8")
promo=(WEB/"romana-pentru-munca-promo.js").read_text(encoding="utf-8")
css=(WEB/"romana-pentru-munca.css").read_text(encoding="utf-8")
index=(WEB/"index.html").read_text(encoding="utf-8")

HERO="https://images.pexels.com/photos/7698712/pexels-photo-7698712.jpeg?w=1080"
ALT="Adulți într-o sesiune de formare și colaborare la locul de muncă"

assert HERO in page, "service page hero changed or is missing"
assert HERO in promo, "homepage promo does not reuse the exact service hero"
assert "pexels-photo-7698712.jpeg?w=400" not in promo, "thumbnail variant returned to homepage promo"
assert ALT in page and ALT in promo, "homepage promo alt text must match the service hero"
assert 'class="rpmPromoVisual"' in promo
assert 'class="rpmPromoImg"' in promo
assert 'class="rpmPromoCta"' in promo
assert 'loading="lazy"' in promo and 'decoding="async"' in promo

for marker in (
    ".rpmPromo{margin:28px 0 12px",
    "grid-template-columns:minmax(300px,.95fr) minmax(0,1.05fr)",
    ".rpmPromoVisual{display:block;min-height:280px",
    ".rpmPromoImg{display:block;width:100%;height:100%;min-height:280px",
    "@media(max-width:860px)",
    "@media(max-width:560px)",
):
    assert marker in css, marker

assert 'romana-pentru-munca.css' in index
assert 'romana-pentru-munca-promo.js' in index
print("PASS Română pentru Muncă homepage promo uses exact hero image at hero scale")
