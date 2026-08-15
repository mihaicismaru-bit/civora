(() => {
  'use strict';
  const FEED = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json';
  const REFRESH_MS = 5 * 60 * 1000;
  const root = document.querySelector('[data-valcea-clar-live]') || document.getElementById('valcea-clar-live') || document.body;
  let lastEdition = '';

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sourceLinks = (item) => (item.sources || []).slice(0,3).map(s => `<a href="${esc(s.url)}" target="_blank" rel="nofollow noopener">${esc(s.name || 'Sursă')}</a>`).join(' · ');

  function styleOnce() {
    if (document.getElementById('vc-live-css')) return;
    const style = document.createElement('style');
    style.id = 'vc-live-css';
    style.textContent = `
      :root{--vc-navy:#071a3d;--vc-red:#d71920;--vc-ink:#101828;--vc-muted:#667085;--vc-line:#e4e7ec;--vc-soft:#f6f7f9}
      #vc-runtime{color:var(--vc-ink);font:16px/1.5 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;background:#fff}
      #vc-runtime *{box-sizing:border-box} #vc-runtime a{color:inherit}
      .vc-top{background:var(--vc-navy);color:#fff}.vc-mast{max-width:1240px;margin:auto;padding:20px 22px 17px;display:flex;justify-content:space-between;gap:20px;align-items:flex-start}
      .vc-brand{font:700 clamp(30px,4vw,48px)/1 Georgia,serif;letter-spacing:.035em}.vc-brand span{border-bottom:3px solid var(--vc-red);padding-bottom:7px}.vc-tag{font-family:Georgia,serif;opacity:.84;margin-top:10px}
      .vc-nav{max-width:1240px;margin:auto;padding:0 22px;border-top:1px solid rgba(255,255,255,.13);display:flex;gap:24px;overflow:auto;white-space:nowrap}.vc-nav a{padding:12px 0;text-decoration:none;font-size:13px;font-weight:800;text-transform:uppercase}
      .vc-main{max-width:1240px;margin:auto;padding:25px 22px 52px}.vc-editionbar{display:flex;align-items:center;gap:13px;flex-wrap:wrap;border-bottom:1px solid var(--vc-line);padding-bottom:12px;margin-bottom:20px}.vc-pill{background:var(--vc-red);color:#fff;padding:7px 11px;border-radius:4px;font-size:12px;font-weight:900}.vc-time{font-size:14px;color:var(--vc-muted)}
      .vc-grid{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(300px,.75fr);gap:34px}.vc-kicker{color:var(--vc-red);font-size:12px;font-weight:900;letter-spacing:.07em;text-transform:uppercase}.vc-hero h1{font:800 clamp(36px,5vw,64px)/1.04 Georgia,serif;margin:8px 0 14px;letter-spacing:-.025em}.vc-dek{font-size:20px;line-height:1.45;color:#344054}.vc-hero p{font-size:18px}.vc-sources{font-size:12px;color:var(--vc-muted);margin-top:12px}.vc-sources a{color:#475467}
      .vc-section-title{font-size:14px;letter-spacing:.055em;text-transform:uppercase;border-bottom:2px solid var(--vc-ink);padding-bottom:7px;margin:28px 0 14px}.vc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.vc-card{border-top:3px solid var(--vc-navy);padding-top:12px}.vc-card h3{font:700 22px/1.15 Georgia,serif;margin:7px 0}.vc-card p{color:#475467;margin:0}
      .vc-side{border-left:1px solid var(--vc-line);padding-left:28px}.vc-side>h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid var(--vc-red);padding-bottom:9px}.vc-side-story{padding:13px 0;border-bottom:1px solid var(--vc-line)}.vc-side-story strong{display:block;font:700 19px/1.18 Georgia,serif}.vc-side-story span{font-size:12px;color:var(--vc-red);font-weight:800}
      .vc-venues{background:var(--vc-navy);color:#fff;border-radius:10px;padding:18px;margin-top:28px}.vc-venue{display:block;text-decoration:none;padding:12px 0;border-top:1px solid rgba(255,255,255,.14)}.vc-venue span{display:block;color:#d0d5dd;font-size:13px;margin-top:3px}.vc-note{margin-top:34px;background:var(--vc-soft);border-left:4px solid var(--vc-red);padding:15px 18px;color:#475467;font-size:13px}.vc-status{font-size:12px;color:var(--vc-muted);margin-top:8px}
      @media(max-width:900px){.vc-grid{grid-template-columns:1fr}.vc-side{border-left:0;padding-left:0;border-top:1px solid var(--vc-line);padding-top:24px}.vc-cards{grid-template-columns:1fr}.vc-tag{display:none}.vc-hero h1{font-size:42px}}
    `;
    document.head.appendChild(style);
  }

  function render(feed) {
    const edition = feed.edition || {};
    const items = edition.items || [];
    const editorial = items.filter(i => !['UNDE_IEȘIM','NOTA_REDACTIEI'].includes(i.section));
    if (!editorial.length) throw new Error('No publishable editorial lead');
    const lead = editorial[0], secondary = editorial.slice(1,4), rest = editorial.slice(4);
    const slot = edition.slot === 'evening' ? 'EDIȚIA DE SEARĂ' : 'EDIȚIA DE DIMINEAȚĂ';
    const cards = secondary.map(i => `<article class="vc-card"><div class="vc-kicker">${esc(i.section)}</div><h3>${esc(i.headline)}</h3><p>${esc(i.dek)}</p><div class="vc-sources">${sourceLinks(i)}</div></article>`).join('');
    const side = [...rest,...secondary].slice(0,4).map(i => `<div class="vc-side-story"><span>${esc(i.section)}</span><strong>${esc(i.headline)}</strong></div>`).join('');
    const venues = (feed.unde_iesim || []).slice(0,4).map(p => `<a class="vc-venue" href="/unde-iesim/"><strong>${esc(p.name)}</strong><span>${esc(p.summary || 'Fișă verificată editorial.')}</span></a>`).join('');
    const paragraphs = (lead.paragraphs || []).slice(0,2).map(p => `<p>${esc(p)}</p>`).join('');
    root.innerHTML = `<div id="vc-runtime">
      <header class="vc-top"><div class="vc-mast"><div><div class="vc-brand"><span>VÂLCEA CLAR</span></div><div class="vc-tag">Știrile Vâlcii, fără zgomot.</div></div><div>valceaclar.ro</div></div><nav class="vc-nav"><a href="/">Acasă</a><a href="#stiri">Știri locale</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>
      <main class="vc-main"><div class="vc-editionbar"><span class="vc-pill">${slot}</span><span class="vc-time">${esc(edition.edition_date)} · actualizată automat ${esc(edition.updated_local)}</span></div>
      <div class="vc-grid"><section><article class="vc-hero"><div class="vc-kicker">${esc(lead.section)}</div><h1>${esc(lead.headline)}</h1><p class="vc-dek">${esc(lead.dek)}</p>${paragraphs}<div class="vc-sources">${sourceLinks(lead)}</div></article><h2 class="vc-section-title" id="stiri">Alte știri importante</h2><div class="vc-cards">${cards}</div></section>
      <aside class="vc-side"><h2>Top știri</h2>${side}<section class="vc-venues"><h2>Unde ieșim</h2>${venues}</section></aside></div>
      <div class="vc-note">Ediția este generată automat numai din informații care au trecut pragul de verificare. Pentru sursele primare descoperite automat, sistemul publică autonom doar titlul, data și sursa; detaliile materiale rămân în verificare.</div><div class="vc-status">Flux autonom · fără API LLM plătită · ediție ${esc(edition.edition_id)}</div></main></div>`;
    lastEdition = edition.edition_id || '';
    document.title = `VÂLCEA CLAR — ${slot.replace('EDIȚIA DE ','')}`;
  }

  async function refresh() {
    try {
      const response = await fetch(`${FEED}?t=${Date.now()}`, {cache:'no-store', mode:'cors'});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const feed = await response.json();
      const id = feed?.edition?.edition_id || '';
      if (!lastEdition || id !== lastEdition) render(feed);
    } catch (err) {
      console.error('VÂLCEA CLAR live feed refresh failed', err);
      const status = root.querySelector?.('.vc-status');
      if (status) status.textContent += ' · actualizarea live este temporar indisponibilă; se păstrează ultima ediție încărcată.';
    }
  }

  styleOnce();
  refresh();
  setInterval(refresh, REFRESH_MS);
})();
