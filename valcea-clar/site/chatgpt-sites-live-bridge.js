(() => {
  'use strict';

  const FEED = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json';
  const LEGAL = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/legal/legal_pages.json';
  const REFRESH_MS = 60 * 1000;
  const root = document.querySelector('[data-valcea-clar-live]') || document.getElementById('valcea-clar-live') || document.body;
  let lastFingerprint = '';

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalizePath = (value) => {
    let path = String(value || '/').split('?')[0].split('#')[0].replace(/\/{2,}/g, '/');
    if (!path.startsWith('/')) path = `/${path}`;
    if (path !== '/' && !path.endsWith('/')) path += '/';
    return path;
  };
  const currentPath = () => normalizePath(window.location.pathname);
  const safeStoryPath = (value) => {
    const path = normalizePath(value);
    return /^\/stiri\/[a-z0-9-]+\/$/.test(path) ? path : '/';
  };
  const storyHref = (story) => safeStoryPath(story?.path);
  const sourceLinks = (item) => (item?.sources || []).slice(0,3).filter(s => s?.url).map(s => `<a href="${esc(s.url)}" target="_blank" rel="nofollow noopener">${esc(s.name || 'Sursă')}</a>`).join(' · ');

  function route() {
    const path = currentPath();
    if (path === '/termeni/') return {kind:'legal', slug:'termeni'};
    if (path === '/confidentialitate/') return {kind:'legal', slug:'confidentialitate'};
    if (/^\/stiri\/[a-z0-9-]+\/$/.test(path)) return {kind:'story', path};
    return {kind:'home'};
  }

  function setCanonical(url) {
    let el = document.querySelector('link[rel="canonical"]');
    if (!el) {
      el = document.createElement('link');
      el.rel = 'canonical';
      document.head.appendChild(el);
    }
    el.href = url;
  }

  function setDescription(value) {
    let el = document.querySelector('meta[name="description"]');
    if (!el) {
      el = document.createElement('meta');
      el.name = 'description';
      document.head.appendChild(el);
    }
    el.content = String(value || '');
  }

  function styleOnce() {
    if (document.getElementById('vc-live-css')) return;
    const style = document.createElement('style');
    style.id = 'vc-live-css';
    style.textContent = `
      :root{--vc-navy:#071a3d;--vc-red:#d71920;--vc-ink:#101828;--vc-muted:#667085;--vc-line:#e4e7ec;--vc-soft:#f6f7f9}
      #vc-runtime{color:var(--vc-ink);font:16px/1.5 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;background:#fff;min-height:100vh}
      #vc-runtime *{box-sizing:border-box}#vc-runtime a{color:inherit}.vc-storylink{text-decoration:none}.vc-storylink:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:4px}
      .vc-top{background:var(--vc-navy);color:#fff}.vc-mast{max-width:1240px;margin:auto;padding:20px 22px 17px;display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.vc-brand{font:700 clamp(30px,4vw,48px)/1 Georgia,serif;letter-spacing:.035em}.vc-brand span{border-bottom:3px solid var(--vc-red);padding-bottom:7px}.vc-tag{font-family:Georgia,serif;opacity:.84;margin-top:10px}.vc-nav{max-width:1240px;margin:auto;padding:0 22px;border-top:1px solid rgba(255,255,255,.13);display:flex;gap:24px;overflow:auto;white-space:nowrap}.vc-nav a{padding:12px 0;text-decoration:none;font-size:13px;font-weight:800;text-transform:uppercase}
      .vc-main{max-width:1240px;margin:auto;padding:25px 22px 52px}.vc-livebar{display:flex;align-items:center;gap:13px;flex-wrap:wrap;border-bottom:1px solid var(--vc-line);padding-bottom:12px;margin-bottom:20px}.vc-pill{background:var(--vc-red);color:#fff;padding:7px 11px;border-radius:4px;font-size:12px;font-weight:900}.vc-time,.vc-status{font-size:13px;color:var(--vc-muted)}
      .vc-grid{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(300px,.75fr);gap:34px}.vc-kicker{color:var(--vc-red);font-size:12px;font-weight:900;letter-spacing:.07em;text-transform:uppercase}.vc-hero h1{font:800 clamp(36px,5vw,64px)/1.04 Georgia,serif;margin:8px 0 14px;letter-spacing:-.025em}.vc-dek{font-size:20px;line-height:1.45;color:#344054}.vc-hero p{font-size:18px}.vc-sources{font-size:12px;color:var(--vc-muted);margin-top:12px}.vc-sources a{color:#475467}
      .vc-section-title{font-size:14px;letter-spacing:.055em;text-transform:uppercase;border-bottom:2px solid var(--vc-ink);padding-bottom:7px;margin:28px 0 14px}.vc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}.vc-card{border-top:3px solid var(--vc-navy);padding-top:12px}.vc-card h3{font:700 22px/1.15 Georgia,serif;margin:7px 0}.vc-card p{color:#475467;margin:0}.vc-side{border-left:1px solid var(--vc-line);padding-left:28px}.vc-side>h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid var(--vc-red);padding-bottom:9px}.vc-side-story{padding:13px 0;border-bottom:1px solid var(--vc-line)}.vc-side-story strong{display:block;font:700 19px/1.18 Georgia,serif}.vc-side-story span{font-size:12px;color:var(--vc-red);font-weight:800}.vc-venues{background:var(--vc-navy);color:#fff;border-radius:10px;padding:18px;margin-top:28px}.vc-venue{display:block;text-decoration:none;padding:12px 0;border-top:1px solid rgba(255,255,255,.14)}.vc-venue span{display:block;color:#d0d5dd;font-size:13px;margin-top:3px}.vc-note{margin-top:34px;background:var(--vc-soft);border-left:4px solid var(--vc-red);padding:15px 18px;color:#475467;font-size:13px}
      .vc-article,.vc-legal{max-width:850px;margin:0 auto;padding:34px 0 24px}.vc-article h1,.vc-legal h1{font:800 clamp(38px,6vw,64px)/1.05 Georgia,serif;letter-spacing:-.025em;margin:8px 0 15px}.vc-article .vc-dek,.vc-legal .vc-dek{font-size:21px}.vc-body{font:18px/1.72 Georgia,serif;margin-top:27px}.vc-body p{margin:0 0 20px}.vc-legal-section{padding:4px 0 18px;border-bottom:1px solid var(--vc-line)}.vc-legal-section:last-of-type{border-bottom:0}.vc-legal-section h2{font:700 25px/1.2 Georgia,serif;margin:28px 0 10px}.vc-legal-section p{font-size:17px;line-height:1.7;color:#344054;margin:10px 0}.vc-back{display:inline-block;margin-top:30px;font-weight:800;color:var(--vc-navy)!important;text-decoration:none}.vc-back:hover{text-decoration:underline}.vc-contact{margin-top:34px;background:var(--vc-soft);border-left:4px solid var(--vc-red);padding:16px 18px}.vc-footer{background:var(--vc-navy);color:#d0d5dd;padding:22px;text-align:center;font-size:13px}.vc-footer-links{display:flex;justify-content:center;gap:10px;margin-top:7px}.vc-footer-links a{color:#fff}
      @media(max-width:900px){.vc-grid{grid-template-columns:1fr}.vc-side{border-left:0;padding-left:0;border-top:1px solid var(--vc-line);padding-top:24px}.vc-cards{grid-template-columns:1fr}.vc-tag{display:none}.vc-hero h1{font-size:42px}}
    `;
    document.head.appendChild(style);
  }

  function shell(content) {
    return `<div id="vc-runtime"><header class="vc-top"><div class="vc-mast"><div><a href="/" class="vc-storylink"><div class="vc-brand"><span>VÂLCEA CLAR</span></div></a><div class="vc-tag">Știrile Vâlcii, fără zgomot.</div></div><div>valceaclar.ro</div></div><nav class="vc-nav"><a href="/">Acasă</a><a href="/#stiri">Știri locale</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>${content}<footer class="vc-footer"><div>VÂLCEA CLAR · informație locală verificată · redactie@valceaclar.ro</div><div class="vc-footer-links"><a href="/termeni/">Termeni</a><span>·</span><a href="/confidentialitate/">Confidențialitate</a></div></footer></div>`;
  }

  function renderHome(feed) {
    const stories = Array.isArray(feed.stories) ? feed.stories : [];
    if (!stories.length) throw new Error('No publishable stories');
    const lead = stories[0], secondary = stories.slice(1,4), rest = stories.slice(4);
    const cards = secondary.map(i => `<article class="vc-card"><div class="vc-kicker">${esc(i.section)}</div><h3><a class="vc-storylink" href="${esc(storyHref(i))}">${esc(i.headline)}</a></h3><p>${esc(i.dek)}</p><div class="vc-sources">${sourceLinks(i)}</div></article>`).join('');
    const side = [...rest,...secondary].slice(0,5).map(i => `<div class="vc-side-story"><span>${esc(i.section)}</span><strong><a class="vc-storylink" href="${esc(storyHref(i))}">${esc(i.headline)}</a></strong></div>`).join('');
    const venues = (feed.unde_iesim || []).slice(0,4).map(p => `<a class="vc-venue" href="/unde-iesim/"><strong>${esc(p.name)}</strong><span>${esc(p.summary || 'Fișă verificată editorial.')}</span></a>`).join('');
    const paragraphs = (lead.paragraphs || []).slice(0,2).map(p => `<p>${esc(p)}</p>`).join('');
    const updated = feed.generated_at || feed?.compatibility_snapshot?.updated_local || '';
    root.innerHTML = shell(`<main class="vc-main"><div class="vc-livebar"><span class="vc-pill">ACTUALIZAT LIVE</span><span class="vc-time">${esc(updated)}</span></div><div class="vc-grid"><section><article class="vc-hero"><div class="vc-kicker">${esc(lead.section)}</div><h1><a class="vc-storylink" href="${esc(storyHref(lead))}">${esc(lead.headline)}</a></h1><p class="vc-dek">${esc(lead.dek)}</p>${paragraphs}<div class="vc-sources">${sourceLinks(lead)}</div></article><h2 class="vc-section-title" id="stiri">Cele mai noi știri verificate</h2><div class="vc-cards">${cards}</div></section><aside class="vc-side"><h2>Top știri</h2>${side}<section class="vc-venues"><h2>Unde ieșim</h2>${venues}</section></aside></div><div class="vc-note">VÂLCEA CLAR publică fiecare material imediat ce trece verificarea editorială. Edițiile de dimineață și seară sunt doar recapuri și nu întârzie știrile.</div><div class="vc-status">Redacție live · story-first · fără API LLM plătit · ${stories.length} materiale publicabile</div></main>`);
    document.title = 'VÂLCEA CLAR — Știri live din Vâlcea';
    setCanonical('https://valceaclar.ro/');
    setDescription('Știri locale verificate din Vâlcea, publicate live de VÂLCEA CLAR.');
  }

  function renderStory(feed, path) {
    const story = (feed.stories || []).find(item => normalizePath(item.path) === path);
    if (!story) {
      root.innerHTML = shell(`<main class="vc-main"><article class="vc-article"><div class="vc-kicker">ȘTIRI</div><h1>Material indisponibil</h1><p class="vc-dek">Acest material nu mai este în fluxul publicabil curent.</p><a class="vc-back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>`);
      document.title = 'Material indisponibil — VÂLCEA CLAR';
      return;
    }
    const body = (story.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('');
    const canonical = story.canonical_url || `https://valceaclar.ro${storyHref(story)}`;
    root.innerHTML = shell(`<main class="vc-main"><article class="vc-article"><div class="vc-kicker">${esc(story.section)}</div><h1>${esc(story.headline)}</h1><p class="vc-dek">${esc(story.dek)}</p><div class="vc-status">Actualizat ${esc(feed.generated_at || '')}</div><div class="vc-body">${body}</div><div class="vc-sources">Surse: ${sourceLinks(story)}</div><a class="vc-back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>`);
    document.title = `${story.headline} — VÂLCEA CLAR`;
    setCanonical(canonical);
    setDescription(story.dek || story.headline || 'Material VÂLCEA CLAR');
  }

  function validateLegal(doc, slug) {
    if (!doc || doc.canonical_domain !== 'valceaclar.ro') throw new Error('Legal canonical domain mismatch');
    const page = doc.pages?.[slug];
    if (!page || page.path !== `/${slug}/`) throw new Error('Legal route mismatch');
    if (!Array.isArray(page.sections) || page.sections.length < 5) throw new Error('Legal page incomplete');
    return page;
  }

  function renderLegal(doc, slug) {
    const page = validateLegal(doc, slug);
    const sections = page.sections.map(section => `<section class="vc-legal-section"><h2>${esc(section.title)}</h2>${(section.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('')}</section>`).join('');
    root.innerHTML = shell(`<main class="vc-main"><article class="vc-legal"><div class="vc-kicker">DOCUMENT PUBLIC</div><h1>${esc(page.title)}</h1><div class="vc-status">În vigoare din ${esc(doc.effective_date)} · VÂLCEA CLAR / valceaclar.ro</div><p class="vc-dek">${esc(page.intro)}</p>${sections}<div class="vc-contact"><strong>Contact</strong><br><a href="mailto:${esc(doc.contact_email)}">${esc(doc.contact_email)}</a></div></article></main>`);
    document.title = `${page.title} — VÂLCEA CLAR`;
    setCanonical(`https://valceaclar.ro${page.path}`);
    setDescription(page.description || page.intro || page.title);
  }

  function feedFingerprint(feed) {
    return `${feed.generated_at || ''}:${(feed.stories || []).map(s => `${s.id}:${s.headline}:${(s.paragraphs || []).length}`).join('|')}`;
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}?t=${Date.now()}`, {cache:'no-store', mode:'cors'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  async function refreshNews(target) {
    try {
      const feed = await fetchJson(FEED);
      if (feed.publication_model !== 'continuous_story_first' || !Array.isArray(feed.stories)) throw new Error('Feed is not story-first');
      const fingerprint = feedFingerprint(feed);
      if (!lastFingerprint || fingerprint !== lastFingerprint) {
        if (target.kind === 'story') renderStory(feed, target.path); else renderHome(feed);
        lastFingerprint = fingerprint;
      }
    } catch (err) {
      console.error('VÂLCEA CLAR live feed refresh failed', err);
      const status = root.querySelector?.('.vc-status');
      if (status && !status.textContent.includes('actualizarea live')) status.textContent += ' · actualizarea live este temporar indisponibilă; se păstrează ultima versiune bună.';
    }
  }

  async function refreshLegal(slug) {
    try {
      const doc = await fetchJson(LEGAL);
      renderLegal(doc, slug);
    } catch (err) {
      console.error('VÂLCEA CLAR legal page refresh failed', err);
      root.innerHTML = shell(`<main class="vc-main"><article class="vc-legal"><div class="vc-kicker">DOCUMENT PUBLIC</div><h1>Pagina este temporar indisponibilă</h1><p class="vc-dek">Documentul nu a putut fi încărcat. Încearcă din nou sau contactează redacția la redactie@valceaclar.ro.</p><a class="vc-back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>`);
    }
  }

  styleOnce();
  const target = route();
  if (target.kind === 'legal') {
    refreshLegal(target.slug);
  } else {
    refreshNews(target);
    setInterval(() => refreshNews(target), REFRESH_MS);
  }
})();
