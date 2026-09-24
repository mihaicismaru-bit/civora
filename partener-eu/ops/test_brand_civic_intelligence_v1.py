#!/usr/bin/env python3
"""Brand-system regression for PARTENER.EU Civic Intelligence."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
WEB=ROOT/"web"
index=(WEB/"index.html").read_text(encoding="utf-8")
css=(WEB/"brand-civic-intelligence-v1.css").read_text(encoding="utf-8")
mark=(WEB/"brand-mark-v1.svg").read_text(encoding="utf-8")
horizontal=(WEB/"brand-horizontal-v1.svg").read_text(encoding="utf-8")
builder=(ROOT/"ops"/"build_public_static_pages.py").read_text(encoding="utf-8")

required_tokens={
    "--brand-950":"#0f172a",
    "--brand-accent-700":"#047857",
    "--text-primary":"#0f172a",
    "--text-secondary":"#475569",
    "--surface-page":"#f8fafc",
    "--border-default":"#cbd5e1",
    "--success":"#047857",
    "--warning":"#92400e",
    "--danger":"#b91c1c",
    "--info":"#1d4ed8",
    "--focus":"#2563eb",
}
for token,value in required_tokens.items():
    assert f"{token}:{value}" in css, (token,value)

for marker in (
    "Source Sans 3","Source Serif 4","font-variant-numeric:tabular-nums",
    "prefers-reduced-motion","outline:3px solid var(--focus)",
    "--status-open-fg","--status-prepare-fg","--status-consult-fg","--status-closed-fg",
):
    assert marker in css, marker

for marker in (
    'brand-civic-intelligence-v1.css',
    'brand-mark-v1.svg',
    'fonts.googleapis.com',
    'fonts.gstatic.com',
    'aria-label="PARTENER.EU — Acasă"',
):
    assert marker in index, marker
    assert marker in builder, marker

assert 'circle' not in mark.lower()
assert '€' not in mark and 'EUR' not in mark
assert '#0F172A' in mark and '#047857' in mark
assert 'PARTENER' in horizontal and '.EU' in horizontal

def rgb(hexv):
    h=hexv.lstrip("#")
    return tuple(int(h[i:i+2],16)/255 for i in (0,2,4))
def lin(c):
    return c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4
def lum(hexv):
    r,g,b=rgb(hexv)
    return .2126*lin(r)+.7152*lin(g)+.0722*lin(b)
def contrast(a,b):
    x,y=sorted((lum(a),lum(b)),reverse=True)
    return (x+.05)/(y+.05)

checks=[
    ("primary/white","#0f172a","#ffffff",7.0),
    ("secondary/white","#475569","#ffffff",4.5),
    ("accent/white","#047857","#ffffff",4.5),
    ("link/white","#1d4ed8","#ffffff",4.5),
    ("warning/white","#92400e","#ffffff",4.5),
    ("danger/white","#b91c1c","#ffffff",4.5),
    ("open text/bg","#065f46","#d1fae5",4.5),
    ("prepare text/bg","#4338ca","#eef2ff",4.5),
    ("consult text/bg","#92400e","#fffbeb",4.5),
    ("closed text/bg","#475569","#e2e8f0",4.5),
]
for name,fg,bg,minimum in checks:
    ratio=contrast(fg,bg)
    assert ratio>=minimum,(name,ratio,minimum)

assert index.index("styles.css") < index.index("brand-civic-intelligence-v1.css")
assert builder.index("public-static-v1.css") < builder.index("brand-civic-intelligence-v1.css")

print("PASS Civic Intelligence brand system, typography, logo and contrast contract")
