(() => {
  'use strict';

  const FEED = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json';
  const NAVIGATION = 'https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/navigation.json';
  const REFRESH_MS = 60 * 1000;
  const path = (() => {
    let value = String(window.location.pathname || '/').split('?')[0].split('#')[0].replace(/\/{2,}/g, '/');
    if (!value.startsWith('/')) value = `/${value}`;
    if (value !== '/' && !value.endsWith('/')) value += '/';
    return value;
  })();

  if (path !== '/stiri/' && path !== '/despre/') return;

  const root = document.querySelector('[data-valcea-clar-live]') || document.getElementById('valcea-clar-live') || document.body;
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));

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

  async function fetchJson(url) {
    const response = await fetch(`${url}?t=${Date.now()}`, {cache: 'no-store', mode: 'cors'});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  const archiveLabel = (story) => story?.active_now
    ? '<span class="vc-live">ACTIV ACUM</span>'
    : '<span class="vc-archive">ARHIVĂ</span>';

  function shell(nav, content) {
    const items = (nav?.items || []).map(item => `<a href="${esc(item.href)}">${esc(item.label)}</a>`).join('');
    const footerLinks = (nav?.footer?.links || []).map(item => `<a href="${esc(item.href)}">${esc(item.label)}</a>`).join('<span>·</span>');
    return `<div id="vc-runtime" data-nav-contract="${esc(nav?.contract_id || 'valcea-clar-primary-v2')}"><header class="vc-top"><div class="vc-mast"><div><div class="vc-brand"><a href="/"><span>${esc(nav?.brand || 'VÂLCEA CLAR')}</span></a></div><div class="vc-tag">${esc(nav?.tagline || 'Știrile Vâlcii, fără zgomot.')}</div></div><div class="vc-domain">${esc(nav?.domain_label || 'valceaclar.ro')}</div></div><nav class="vc-nav" aria-label="Navigație principală">${items}</nav></header>${content}<footer class="vc-footer"><div>${esc(nav?.footer?.line || 'VÂLCEA CLAR · informație locală verificată')}</div><div class="vc-footer-links">${footerLinks}</div></footer></div>`;
  }

  function renderNews(nav, feed) {
    const stories = Array.isArray(feed?.stories) ? feed.stories : [];
    const rows = stories.map(story => `<article class="vc-side-story"><div class="vc-kicker">${esc(String(story.section || 'ȘTIRI').replaceAll('_', ' '))}</div><div class="vc-storymeta">${archiveLabel(story)}<span>${esc(String(story.first_published_at || '').slice(0, 10))}</span></div><strong><a class="vc-storylink" href="${esc(story.path)}">${esc(story.headline)}</a></strong><p>${esc(story.dek || '')}</p></article>`).join('');
    root.innerHTML = shell(nav, `<main class="vc-main"><div class="vc-kicker">ȘTIRI</div><h1 style="font:800 clamp(39px,6vw,65px)/1.04 Georgia,serif;letter-spacing:-.03em;margin:8px 0 15px">Știrile Vâlcii, puse în ordine.</h1><p class="vc-dek">Aici apar numai materiale jurnalistice publicabile. Dosarele de documentare și monitoarele interne nu sunt folosite pentru a umple categorii.</p><div class="vc-livebar"><span class="vc-pill">ACTUALIZAT LIVE</span><span class="vc-time">${esc(feed.generated_at || '')}</span><span class="vc-status">${stories.filter(story => story.active_now).length} materiale curente · ${stories.length} materiale sigure</span></div><section>${rows || '<p class="vc-status">Nu există materiale publicabile.</p>'}</section></main>`);
    document.title = 'Știri — VÂLCEA CLAR';
    setCanonical('https://valceaclar.ro/stiri/');
    setDescription('Toate știrile VÂLCEA CLAR, cu materialele curente separate clar de arhivă.');
  }

  function renderAbout(nav) {
    root.innerHTML = shell(nav, `<main class="vc-main"><article class="vc-article"><div class="vc-kicker">DESPRE VÂLCEA CLAR</div><h1>Clar înainte de rapid.</h1><p class="vc-dek">VÂLCEA CLAR publică informație locală verificată, separă faptele de monitorizare și păstrează vizibilă diferența dintre actualitate și arhivă.</p><section class="vc-rich"><h2>Verificăm înainte de publicare</h2><p>Un semnal, un monitor sau un dosar incomplet nu devine automat articol. Faptele materiale rămân blocate până când dovezile cerute sunt suficiente.</p></section><section class="vc-rich"><h2>Arhiva nu este prezentată drept actualitate</h2><p>Materialele publicate rămân accesibile, dar sunt marcate distinct atunci când nu mai descriu o situație activă.</p></section><section class="vc-rich"><h2>Sursele rămân verificabile</h2><p>Materialele publice păstrează legătura cu sursele și cu traseul editorial care a autorizat publicarea.</p></section></article></main>`);
    document.title = 'Despre — VÂLCEA CLAR';
    setCanonical('https://valceaclar.ro/despre/');
    setDescription('Cum lucrează VÂLCEA CLAR: verificare înainte de publicare, actualitate separată de arhivă și surse verificabile.');
  }

  async function refresh() {
    try {
      const nav = await fetchJson(NAVIGATION);
      if (path === '/despre/') {
        renderAbout(nav);
        return;
      }
      const feed = await fetchJson(FEED);
      if (feed?.publication_model !== 'continuous_story_first' || !Array.isArray(feed?.stories)) throw new Error('Feed is not story-first');
      renderNews(nav, feed);
    } catch (error) {
      console.error('VÂLCEA CLAR route bridge refresh failed', error);
    }
  }

  refresh();
  if (path === '/stiri/') setInterval(refresh, REFRESH_MS);
})();
