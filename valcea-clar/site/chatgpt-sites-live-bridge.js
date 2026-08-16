(() => {
  'use strict';

  const FEED = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json';
  const NAVIGATION = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/navigation.json';
  const LEGAL = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/legal/legal_pages.json';
  const REFRESH_MS = 60 * 1000;
  const root = document.querySelector('[data-valcea-clar-live]') || document.getElementById('valcea-clar-live') || document.body;
  let lastFingerprint = '';

  const FALLBACK_NAV = {
    contract_id: 'valcea-clar-primary-v1',
    brand: 'VÂLCEA CLAR',
    tagline: 'Știrile Vâlcii, fără zgomot.',
    domain_label: 'valceaclar.ro',
    items: [
      {label:'Acasă',href:'/'},
      {label:'Ultimele',href:'/#stiri'},
      {label:'Administrație',href:'/#administratie'},
      {label:'Sănătate',href:'/#sanatate'},
      {label:'Infrastructură',href:'/#infrastructura'},
      {label:'Cultură & Evenimente',href:'/#cultura-evenimente'},
      {label:'Sport',href:'/#sport'},
      {label:'Unde ieșim',href:'/unde-iesim/'}
    ],
    footer: {
      line: 'VÂLCEA CLAR · informație locală verificată · redactie@valceaclar.ro',
      links: [
        {label:'Termeni',href:'/termeni/'},
        {label:'Confidențialitate',href:'/confidentialitate/'}
      ]
    }
  };

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const normalizePath = (value) => {
    let path = String(value || '/').split('?')[0].split('#')[0].replace(/\/{2,}/g, '/');
    if (!path.startsWith('/')) path = `/${path}`;
    if (path !== '/' && !path.endsWith('/')) path += '/';
    return path;
  };
  const currentPath = () => normalizePath(window.location.pathname);
  const storyHref = (story) => /^\/stiri\/[a-z0-9-]+\/$/.test(normalizePath(story?.path)) ? normalizePath(story.path) : '/';

  function route() {
    const path = currentPath();
    if (path === '/') return {kind:'home'};
    if (path === '/termeni/') return {kind:'legal', slug:'termeni'};
    if (path === '/confidentialitate/') return {kind:'legal', slug:'confidentialitate'};
    if (path === '/unde-iesim/') return {kind:'venues'};
    if (/^\/stiri\/[a-z0-9-]+\/$/.test(path)) return {kind:'story', path};
    return {kind:'passthrough'};
  }

  function setCanonical(url) {
    let el = document.querySelector('link[rel="canonical"]');
    if (!el) { el = document.createElement('link'); el.rel = 'canonical'; document.head.appendChild(el); }
    el.href = url;
  }
  function setDescription(value) {
    let el = document.querySelector('meta[name="description"]');
    if (!el) { el = document.createElement('meta'); el.name = 'description'; document.head.appendChild(el); }
    el.content = String(value || '');
  }

  function styleOnce() {
    if (document.getElementById('vc-live-css')) return;
    const style = document.createElement('style');
    style.id = 'vc-live-css';
    style.textContent = `
      :root{--vc-navy:#071a3d;--vc-red:#d71920;--vc-ink:#101828;--vc-muted:#667085;--vc-line:#e4e7ec;--vc-soft:#f6f7f9}
      #vc-runtime{color:var(--vc-ink);font:16px/1.58 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif;background:#fff;min-height:100vh}#vc-runtime *{box-sizing:border-box}#vc-runtime a{color:inherit}
      .vc-top{background:var(--vc-navy);color:#fff}.vc-mast{max-width:1240px;margin:auto;padding:20px 22px 17px;display:flex;justify-content:space-between;gap:24px;align-items:flex-start}.vc-brand{font:700 clamp(30px,4vw,48px)/1 Georgia,serif;letter-spacing:.035em}.vc-brand a{text-decoration:none}.vc-brand span{border-bottom:3px solid var(--vc-red);padding-bottom:7px}.vc-tag{font-family:Georgia,serif;opacity:.84;margin-top:10px}.vc-domain{font-size:13px;opacity:.76;padding-top:5px}
      .vc-nav{max-width:1240px;margin:auto;padding:0 22px;border-top:1px solid rgba(255,255,255,.14);display:flex;gap:23px;overflow-x:auto;white-space:nowrap}.vc-nav a{padding:12px 0;text-decoration:none;font-size:12px;font-weight:850;letter-spacing:.025em;text-transform:uppercase}.vc-nav a:hover{text-decoration:underline;text-underline-offset:4px}
      .vc-main{max-width:1240px;margin:auto;padding:25px 22px 58px}.vc-livebar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--vc-line);padding-bottom:12px;margin-bottom:22px}.vc-pill{background:var(--vc-red);color:#fff;padding:7px 11px;border-radius:4px;font-size:11px;font-weight:900;letter-spacing:.045em}.vc-time,.vc-status{font-size:13px;color:var(--vc-muted)}
      .vc-grid{display:grid;grid-template-columns:minmax(0,1.86fr) minmax(285px,.72fr);gap:36px}.vc-kicker{color:var(--vc-red);font-size:12px;font-weight:900;letter-spacing:.075em;text-transform:uppercase}.vc-storylink{text-decoration:none}.vc-storylink:hover{text-decoration:underline;text-underline-offset:5px}.vc-hero h1{font:800 clamp(38px,5.4vw,66px)/1.03 Georgia,serif;letter-spacing:-.03em;margin:8px 0 14px}.vc-dek{font-size:20px;line-height:1.45;color:#344054}.vc-hero p{font:18px/1.68 Georgia,serif}.vc-storymeta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin:9px 0;color:var(--vc-muted);font-size:12px}.vc-archive{font-weight:850;background:#f2f4f7;color:#475467;padding:4px 7px;border-radius:999px}.vc-live{font-weight:900;background:#ecfdf3;color:#067647;padding:4px 7px;border-radius:999px}.vc-sources{font-size:12px;color:var(--vc-muted);margin-top:14px}.vc-sources a{color:#475467}
      .vc-section-title{font-size:13px;letter-spacing:.07em;text-transform:uppercase;border-bottom:2px solid var(--vc-ink);padding-bottom:8px;margin:30px 0 15px}.vc-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.vc-card{border-top:3px solid var(--vc-navy);padding-top:12px}.vc-card h3{font:700 22px/1.15 Georgia,serif;margin:7px 0}.vc-card p{color:#475467;margin:0}.vc-side{border-left:1px solid var(--vc-line);padding-left:28px}.vc-side>h2{font-size:14px;text-transform:uppercase;letter-spacing:.07em;border-bottom:2px solid var(--vc-red);padding-bottom:9px;margin:0}.vc-side-story{padding:13px 0;border-bottom:1px solid var(--vc-line)}.vc-side-story strong{display:block;font:700 18px/1.2 Georgia,serif}
      .vc-venues{background:var(--vc-navy);color:#fff;border-radius:10px;padding:18px;margin-top:28px}.vc-venues-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.vc-venues h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;margin:0}.vc-venues .vc-cta{font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:5px 8px}.vc-venue{display:block;text-decoration:none;padding:12px 0;border-top:1px solid rgba(255,255,255,.14)}.vc-venue span{display:block;color:#d0d5dd;font-size:13px;margin-top:3px}.vc-note{margin-top:34px;background:var(--vc-soft);border-left:4px solid var(--vc-red);padding:15px 18px;color:#475467;font-size:13px}
      .vc-article,.vc-legal{max-width:860px;margin:0 auto}.vc-article h1,.vc-legal h1,.vc-venues-page h1{font:800 clamp(39px,6vw,65px)/1.04 Georgia,serif;letter-spacing:-.03em;margin:8px 0 15px}.vc-body{font:18px/1.72 Georgia,serif;margin-top:26px}.vc-body p{margin:0 0 20px}.vc-factbox{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--vc-line);border:1px solid var(--vc-line);border-radius:10px;overflow:hidden;margin:26px 0}.vc-fact{background:#fff;padding:13px 15px}.vc-fact b{display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em;color:var(--vc-muted);margin-bottom:3px}.vc-fact span{font-weight:750}.vc-rich{border-top:1px solid var(--vc-line);padding-top:24px;margin-top:28px}.vc-rich h2{font:800 26px/1.16 Georgia,serif;margin:0 0 13px}.vc-rich p{font:17px/1.7 Georgia,serif;color:#344054}.vc-rich li{margin:8px 0;line-height:1.55}.vc-article-sources{margin-top:38px;border-top:2px solid var(--vc-ink);padding-top:15px}.vc-article-sources h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em}.vc-back{display:inline-block;margin-top:30px;font-weight:800;color:var(--vc-navy)!important}.vc-legal-section{padding:3px 0 20px;border-bottom:1px solid var(--vc-line)}.vc-legal-section h2{font:700 25px/1.2 Georgia,serif}.vc-contact{margin-top:30px;background:var(--vc-soft);border-left:4px solid var(--vc-red);padding:16px 18px}
      .vc-venue-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:24px}.vc-venue-card{border:1px solid var(--vc-line);border-radius:12px;padding:17px;text-decoration:none}.vc-venue-card h2{font:700 22px/1.2 Georgia,serif;margin:4px 0 8px}.vc-venue-card p{color:#475467}.vc-city{font-size:11px;color:var(--vc-red);font-weight:900;text-transform:uppercase;letter-spacing:.06em}
      .vc-footer{background:var(--vc-navy);color:#d0d5dd;padding:22px;text-align:center;font-size:13px}.vc-footer-links{display:flex;justify-content:center;gap:9px;margin-top:7px}.vc-footer-links a{color:#fff}
      @media(max-width:900px){.vc-grid{grid-template-columns:1fr}.vc-side{border-left:0;padding-left:0;border-top:1px solid var(--vc-line);padding-top:24px}.vc-cards,.vc-venue-grid{grid-template-columns:1fr}.vc-tag{display:none}.vc-hero h1{font-size:43px}}@media(max-width:560px){.vc-main{padding:20px 16px 48px}.vc-mast,.vc-nav{padding-left:16px;padding-right:16px}.vc-factbox{grid-template-columns:1fr}.vc-article h1{font-size:39px}}
    `;
    document.head.appendChild(style);
  }

  const navLinks = (nav) => (nav.items || []).map(i => `<a href="${esc(i.href)}">${esc(i.label)}</a>`).join('');
  const footerLinks = (nav) => (nav.footer?.links || []).map(i => `<a href="${esc(i.href)}">${esc(i.label)}</a>`).join('<span>·</span>');
  function shell(nav, content) {
    return `<div id="vc-runtime" data-nav-contract="${esc(nav.contract_id || 'valcea-clar-primary-v1')}"><header class="vc-top"><div class="vc-mast"><div><div class="vc-brand"><a href="/"><span>${esc(nav.brand || 'VÂLCEA CLAR')}</span></a></div><div class="vc-tag">${esc(nav.tagline || '')}</div></div><div class="vc-domain">${esc(nav.domain_label || 'valceaclar.ro')}</div></div><nav class="vc-nav" aria-label="Navigație principală">${navLinks(nav)}</nav></header>${content}<footer class="vc-footer"><div>${esc(nav.footer?.line || '')}</div><div class="vc-footer-links">${footerLinks(nav)}</div></footer></div>`;
  }

  const sources = (story, list=false) => {
    const rows = (story?.sources || []).filter(s => s?.url).map(s => `<a href="${esc(s.url)}" target="_blank" rel="nofollow noopener">${esc(s.name || 'Sursă')}</a>`);
    return list ? rows.map(x => `<li>${x}</li>`).join('') : rows.slice(0,4).join(' · ');
  };
  const archiveLabel = (story) => story?.active_now
    ? '<span class="vc-live">ACTIV ACUM</span>'
    : `<span class="vc-archive">ARHIVĂ${story?.first_published_at ? ` · ${esc(String(story.first_published_at).slice(0,10))}` : ''}</span>`;
  const factbox = (story) => (story?.factbox || []).length ? `<section class="vc-factbox">${story.factbox.map(x => `<div class="vc-fact"><b>${esc(x.label)}</b><span>${esc(x.value)}</span></div>`).join('')}</section>` : '';
  const richSections = (story) => (story?.article_sections || []).map(section => {
    const ps = (section.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('');
    const bullets = (section.bullets || []).length ? `<ul>${section.bullets.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '';
    return `<section class="vc-rich"><h2>${esc(section.title)}</h2>${ps}${bullets}</section>`;
  }).join('');

  function renderHome(nav, feed) {
    const stories = Array.isArray(feed.stories) ? feed.stories : [];
    if (!stories.length) throw new Error('No publishable stories');
    const active = stories.filter(s => s.active_now), lead = active[0] || stories[0];
    const others = stories.filter(s => s.id !== lead.id), secondary = others.slice(0,3), top = [...others, lead].slice(0,5);
    const cards = secondary.map(i => `<article class="vc-card"><div class="vc-kicker">${esc(String(i.section || 'ȘTIRI').replaceAll('_',' '))}</div><div class="vc-storymeta">${archiveLabel(i)}</div><h3><a class="vc-storylink" href="${esc(storyHref(i))}">${esc(i.headline)}</a></h3><p>${esc(i.dek)}</p></article>`).join('');
    const side = top.map(i => `<div class="vc-side-story"><div class="vc-kicker">${esc(String(i.section || 'ȘTIRI').replaceAll('_',' '))}</div><strong><a class="vc-storylink" href="${esc(storyHref(i))}">${esc(i.headline)}</a></strong></div>`).join('');
    const venues = (feed.unde_iesim || []).slice(0,4).map(p => `<a class="vc-venue" href="/unde-iesim/local/${esc(p.slug || p.id)}/"><strong>${esc(p.name)}</strong><span>${esc(p.summary || 'Fișă verificată editorial.')}</span></a>`).join('');
    const paragraphs = (lead.paragraphs || []).slice(0,2).map(p => `<p>${esc(p)}</p>`).join('');
    const liveNote = active.length ? 'Materialele active sunt ordonate primele.' : 'Nu există în acest moment un material activ; afișăm clar cele mai recente materiale din arhivă.';
    root.innerHTML = shell(nav, `<main class="vc-main"><span id="stiri"></span><span id="administratie"></span><span id="sanatate"></span><span id="infrastructura"></span><span id="cultura-evenimente"></span><span id="sport"></span><div class="vc-livebar"><span class="vc-pill">ACTUALIZAT LIVE</span><span class="vc-time">${esc(feed.generated_at || '')}</span><span class="vc-status">${esc(liveNote)}</span></div><div class="vc-grid"><section><article class="vc-hero"><div class="vc-kicker">${esc(String(lead.section || 'ȘTIRI').replaceAll('_',' '))}</div><div class="vc-storymeta">${archiveLabel(lead)}</div><h1><a class="vc-storylink" href="${esc(storyHref(lead))}">${esc(lead.headline)}</a></h1><p class="vc-dek">${esc(lead.dek)}</p>${paragraphs}<div class="vc-sources">${sources(lead)}</div></article><h2 class="vc-section-title">Ultimele materiale publicate</h2><div class="vc-cards">${cards}</div></section><aside class="vc-side"><h2>De citit</h2>${side}<section class="vc-venues"><div class="vc-venues-head"><h2>Unde ieșim</h2><a class="vc-cta" href="/unde-iesim/">Vezi ghidul</a></div>${venues}</section></aside></div><div class="vc-note">Știrile active și arhiva sunt marcate distinct. Monitoarele interne și anchetele incomplete nu apar ca articole.</div></main>`);
    document.title = 'VÂLCEA CLAR — Știri din Vâlcea';
    setCanonical('https://valceaclar.ro/');
    setDescription('Știri locale verificate din Vâlcea, publicate continuu și arhivate clar.');
  }

  function renderStory(nav, feed, path) {
    const story = (feed.stories || []).find(item => normalizePath(item.path) === path);
    if (!story) {
      root.innerHTML = shell(nav, `<main class="vc-main"><article class="vc-article"><div class="vc-kicker">ȘTIRI</div><h1>Material indisponibil</h1><p class="vc-dek">Acest material nu se află în fluxul public autorizat.</p><a class="vc-back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>`);
      return;
    }
    const body = (story.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('');
    root.innerHTML = shell(nav, `<main class="vc-main"><article class="vc-article"><div class="vc-kicker">${esc(String(story.section || 'ȘTIRI').replaceAll('_',' '))}</div><div class="vc-storymeta">${archiveLabel(story)}</div><h1>${esc(story.headline)}</h1><p class="vc-dek">${esc(story.dek)}</p><div class="vc-status">Publicat ${esc(story.first_published_at || '')} · informație locală verificată</div>${factbox(story)}<div class="vc-body">${body}</div>${richSections(story)}<section class="vc-article-sources"><h2>Surse</h2><ul>${sources(story,true)}</ul></section><a class="vc-back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>`);
    document.title = `${story.headline} — VÂLCEA CLAR`;
    setCanonical(story.canonical_url || `https://valceaclar.ro${storyHref(story)}`);
    setDescription(story.dek || story.headline || 'Material VÂLCEA CLAR');
  }

  function renderVenues(nav, feed) {
    const cards = (feed.unde_iesim || []).map(p => `<a class="vc-venue-card" href="/unde-iesim/local/${esc(p.slug || p.id)}/"><div class="vc-city">${esc(p.city || 'Vâlcea')}</div><h2>${esc(p.name)}</h2><p>${esc(p.summary || 'Fișă verificată editorial.')}</p></a>`).join('');
    root.innerHTML = shell(nav, `<main class="vc-main vc-venues-page"><div class="vc-kicker">GHID LOCAL</div><h1>Unde ieșim</h1><p class="vc-dek">Restaurante, cafenele și locuri de ieșit verificate editorial. Candidații incompleți rămân ascunși până la verificare.</p><div class="vc-venue-grid">${cards}</div></main>`);
    document.title = 'Unde ieșim — VÂLCEA CLAR';
    setCanonical('https://valceaclar.ro/unde-iesim/');
    setDescription('Ghid local VÂLCEA CLAR pentru restaurante, cafenele și locuri de ieșit.');
  }

  function renderLegal(nav, doc, slug) {
    const page = doc?.pages?.[slug];
    if (!page || page.path !== `/${slug}/`) throw new Error('Legal route mismatch');
    const sections = (page.sections || []).map(section => `<section class="vc-legal-section"><h2>${esc(section.title)}</h2>${(section.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('')}</section>`).join('');
    root.innerHTML = shell(nav, `<main class="vc-main"><article class="vc-legal"><div class="vc-kicker">DOCUMENT PUBLIC</div><h1>${esc(page.title)}</h1><div class="vc-status">În vigoare din ${esc(doc.effective_date)} · VÂLCEA CLAR / valceaclar.ro</div><p class="vc-dek">${esc(page.intro)}</p>${sections}<div class="vc-contact"><strong>Contact</strong><br><a href="mailto:${esc(doc.contact_email)}">${esc(doc.contact_email)}</a></div></article></main>`);
    document.title = `${page.title} — VÂLCEA CLAR`;
    setCanonical(`https://valceaclar.ro${page.path}`);
    setDescription(page.description || page.intro || page.title);
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}?t=${Date.now()}`, {cache:'no-store', mode:'cors'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }
  async function getNav() {
    try {
      const nav = await fetchJson(NAVIGATION);
      return nav?.contract_id ? nav : FALLBACK_NAV;
    } catch (_) {
      return FALLBACK_NAV;
    }
  }

  function feedFingerprint(feed) {
    return `${feed.generated_at || ''}:${feed.navigation_contract || ''}:${(feed.stories || []).map(s => `${s.id}:${s.headline}:${(s.article_sections || []).length}`).join('|')}`;
  }

  async function refreshNews(target) {
    try {
      const [feed, nav] = await Promise.all([fetchJson(FEED), getNav()]);
      if (feed.publication_model !== 'continuous_story_first' || !Array.isArray(feed.stories)) throw new Error('Feed is not story-first');
      const fp = feedFingerprint(feed);
      if (lastFingerprint && fp === lastFingerprint) return;
      if (target.kind === 'story') renderStory(nav, feed, target.path);
      else if (target.kind === 'venues') renderVenues(nav, feed);
      else renderHome(nav, feed);
      lastFingerprint = fp;
    } catch (err) {
      console.error('VÂLCEA CLAR live refresh failed', err);
      const status = root.querySelector?.('.vc-status');
      if (status) status.textContent = 'Actualizarea live este temporar indisponibilă; rămâne afișată ultima versiune bună.';
    }
  }

  async function refreshLegal(slug) {
    try {
      const [doc, nav] = await Promise.all([fetchJson(LEGAL), getNav()]);
      renderLegal(nav, doc, slug);
    } catch (err) {
      console.error('VÂLCEA CLAR legal refresh failed', err);
    }
  }

  styleOnce();
  const target = route();
  if (target.kind === 'passthrough') return;
  if (target.kind === 'legal') refreshLegal(target.slug);
  else {
    refreshNews(target);
    setInterval(() => refreshNews(target), REFRESH_MS);
  }
})();
