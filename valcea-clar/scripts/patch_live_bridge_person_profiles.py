#!/usr/bin/env python3
"""Idempotently project resolved People Intelligence into the Sites live bridge.

The bridge keeps the existing artist helper name for compatibility, but extends
its text-node linker to both artist_profiles and person_profiles. Future artist
patches therefore do not erase person links. A separate person profile block is
rendered below the article body, and people-only feed changes invalidate the
runtime fingerprint.
"""
from __future__ import annotations
import argparse,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TARGET=ROOT/"site/chatgpt-sites-live-bridge.js"
PERSON_MARKER="function personProfiles(story)"

def replace_function(text,name,replacement):
    pattern=re.compile(rf"  function {re.escape(name)}\([^\n]*\) \{{.*?\n  \}}\n",re.S)
    if not pattern.search(text): raise ValueError(f"{name} function anchor missing")
    return pattern.sub(replacement,text,count=1)

def patch(text:str)->str:
    enhanced=r'''  function artistLinkedText(value, story) {
    const artists = Array.isArray(story?.artist_profiles) ? story.artist_profiles : [];
    const people = Array.isArray(story?.person_profiles) ? story.person_profiles : [];
    let output = esc(value);
    const rows = [
      ...artists
        .filter(item => item?.name && /^\/artisti\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
        .map(item => ({...item, kind:'artist'})),
      ...people
        .filter(item => item?.name && item?.identity_resolved === true && /^\/oameni\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
        .map(item => ({...item, kind:'person'})),
    ].sort((a,b) => String(b.name).length - String(a.name).length);
    if (!rows.length) return output;
    for (const item of rows) {
      const token = esc(item.name);
      if (!token || !output.includes(token)) continue;
      const cls = item.kind === 'person' ? 'vc-person-inline' : 'vc-artist-inline';
      const attr = item.kind === 'person' ? 'data-person-profile' : 'data-artist-profile';
      const linked = `<a class="${cls}" href="${esc(item.path)}" ${attr}="${esc(item.id || '')}">${token}</a>`;
      output = output.split(token).join(linked);
    }
    return output;
  }
'''
    text=replace_function(text,"artistLinkedText",enhanced)

    if PERSON_MARKER not in text:
        anchor="  function artistProfiles(story) {"
        if anchor not in text: raise ValueError("artistProfiles anchor missing")
        helper=r'''  function personProfiles(story) {
    const rows = Array.isArray(story?.person_profiles) ? story.person_profiles : [];
    const links = rows
      .filter(item => item?.name && item?.identity_resolved === true && /^\/oameni\/[a-z0-9-]+\/$/.test(String(item?.path || '')))
      .map(item => `<a href="${esc(item.path)}">${esc(item.name)}</a>`)
      .join('');
    if (!links) return '';
    return `<section class="vc-rich vc-people" data-people-intelligence="verified"><h2>Oameni din acest material</h2><p>Profiluri publice VÂLCEA CLAR cu identitate rezolvată și istoric construit incremental din surse verificabile.</p><div class="vc-personlinks">${links}</div><p><a href="/oameni/">Vezi directorul de persoane →</a></p></section>`;
  }

'''
        text=text.replace(anchor,helper+anchor,1)

    css_anchor=".vc-artist-inline:hover{color:var(--vc-red)}"
    css_add=css_anchor+".vc-person-inline{font-weight:700;text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:3px}.vc-person-inline:hover{color:var(--vc-red)}.vc-personlinks{display:flex;gap:9px;flex-wrap:wrap}.vc-personlinks a{border:1px solid var(--vc-line);border-radius:999px;padding:7px 11px;text-decoration:none;font:750 13px/1.2 Inter,system-ui,sans-serif}.vc-personlinks a:hover{text-decoration:underline}"
    if ".vc-person-inline{" not in text:
        if css_anchor not in text: raise ValueError("artist inline CSS anchor missing")
        text=text.replace(css_anchor,css_add,1)

    old='${richSections(story)}${artistProfiles(story)}<section class="vc-article-sources">'
    new='${richSections(story)}${artistProfiles(story)}${personProfiles(story)}<section class="vc-article-sources">'
    if new not in text:
        if old not in text: raise ValueError("person profile insertion anchor missing")
        text=text.replace(old,new,1)

    old_fp="`${s.id}:${s.headline}:${(s.article_sections || []).length}:${(s.artist_profiles || []).map(a => `${a.id}:${a.path}`).join(',')}`"
    new_fp="`${s.id}:${s.headline}:${(s.article_sections || []).length}:${(s.artist_profiles || []).map(a => `${a.id}:${a.path}`).join(',')}:${(s.person_profiles || []).map(p => `${p.id}:${p.path}`).join(',')}`"
    if old_fp in text: text=text.replace(old_fp,new_fp,1)
    elif new_fp not in text: raise ValueError("feed fingerprint anchor missing")
    return text

def validate(text:str)->None:
    required=[PERSON_MARKER,"person_profiles","identity_resolved === true","/oameni/",".vc-person-inline{",".vc-personlinks{","${personProfiles(story)}<section class=\"vc-article-sources\">","data-person-profile","(s.person_profiles || [])"]
    missing=[x for x in required if x not in text]
    if missing: raise ValueError(f"People Intelligence live bridge contract missing: {missing}")

def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument("--check",action="store_true");a=ap.parse_args()
    original=TARGET.read_text(encoding="utf-8")
    updated=patch(original);validate(updated)
    if a.check:
        print("VÂLCEA CLAR live bridge People Intelligence contract: PASS");return 0
    if updated!=original:
        TARGET.write_text(updated,encoding="utf-8");print("VÂLCEA CLAR live bridge People Intelligence patch: UPDATED")
    else: print("VÂLCEA CLAR live bridge People Intelligence patch: ALREADY_CURRENT")
    return 0
if __name__=="__main__":raise SystemExit(main())
