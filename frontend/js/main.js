/* Shared helpers: nav, footer, account state, selected place, UV categories, charts. */
const $ = (s, r = document) => r.querySelector(s);
const escHtml = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');

/* WHO UV categories. The index is rounded to a whole number first, as on the backend (ml/risk.py). */
const UVC = [
  [2, 'Low', '#3e9b3a', 'Safe for most people. Sunglasses on bright days.'],
  [5, 'Moderate', '#e5be00', 'Wear sunscreen and sunglasses; seek shade around midday.'],
  [7, 'High', '#ec7d17', 'Use SPF 30+, a hat and sunglasses; limit sun 10am–4pm.'],
  [10, 'Very High', '#d63b20', 'Avoid midday sun; cover up and use SPF 50+, reapply often.'],
  [99, 'Extreme', '#9a4e99', 'Stay indoors at midday; unprotected skin can burn in minutes.']
];
const UV_COLOR = Object.fromEntries(UVC.map(c => [c[1], c[2]]));
const uvCat = v => { const r = Math.floor(Number(v) + 0.5), c = UVC.find(x => r <= x[0]); return { label: c[1], color: c[2], tip: c[3] }; };
const riskBadge = label => `<span class="badge" style="--c:${UV_COLOR[label] || '#87939a'}">${escHtml(label || 'Unavailable')}</span>`;
const fmtNum = (v, d = 1) => v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d);
const fmt = iso => new Date(iso).toLocaleString();

/* UV index scale, 0 to 11+, in the WHO category colours, with a marker at `value` (omit it for a plain key).
 * Category edges sit at 2.5, 5.5, 7.5 and 10.5 because the index is rounded before it is categorised. */
const UV_SCALE_MAX = 13;
function uvScale(value) {
  const edges = [0, 2.5, 5.5, 7.5, 10.5, UV_SCALE_MAX];
  const bar = UVC.map((c, i) => `<span style="--c:${c[2]};--w:${edges[i + 1] - edges[i]}" title="${c[1]}"></span>`).join('');
  const ticks = [0, 3, 6, 8, 11].map(t => `<span style="left:${(t / UV_SCALE_MAX) * 100}%">${t === 11 ? '11+' : t}</span>`).join('');
  const has = value !== null && value !== undefined && !Number.isNaN(Number(value));
  const pos = has ? Math.min(Math.max(Number(value), 0), UV_SCALE_MAX) / UV_SCALE_MAX * 100 : 0;
  const label = has ? `UV index ${fmtNum(value, 1)} on the WHO scale: ${uvCat(value).label}` : 'WHO UV index scale from 0 to 11 and above';
  return `<div class="uv-scale" role="img" aria-label="${escHtml(label)}">${has ? `<i class="uv-scale-mark" style="left:${pos}%"></i>` : ''}<div class="uv-scale-bar">${bar}</div><div class="uv-scale-ticks" aria-hidden="true">${ticks}</div></div>`;
}

/* The five WHO categories with their index range and guidance (home page). */
function uvGuide() {
  const lo = [0, 3, 6, 8, 11];
  return `<ol class="uv-guide">${UVC.map((c, i) => `<li style="--c:${c[2]}"><span class="uv-guide-range">${i === 4 ? '11+' : `${lo[i]}–${c[0]}`}</span><strong>${c[1]}</strong><p>${escHtml(c[3])}</p></li>`).join('')}</ol>`;
}

/* ------------------------------------------------------------ selected place
 * The last point chosen on any page, shared between pages: {lat, lon, name?}. */
function getPlace() {
  try {
    const c = JSON.parse(localStorage.getItem('og_coords') || 'null');
    if (c && Number.isFinite(Number(c.lat)) && Number.isFinite(Number(c.lon))) return { lat: Number(c.lat), lon: Number(c.lon), name: c.name || null };
  } catch (_) {}
  return null;
}
function setPlace(lat, lon, name) {
  lat = Number(lat); lon = Number(lon);
  const old = getPlace();
  const keep = old && Math.abs(old.lat - lat) < 0.0005 && Math.abs(old.lon - lon) < 0.0005 ? old.name : null;
  const place = { lat, lon, name: name || keep || null };
  try { localStorage.setItem('og_coords', JSON.stringify(place)); } catch (_) {}
  return place;
}
const coordText = (lat, lon) => `${Math.abs(lat).toFixed(4)}° ${lat >= 0 ? 'N' : 'S'}, ${Math.abs(lon).toFixed(4)}° ${lon >= 0 ? 'E' : 'W'}`;
const placeLabel = p => (p && p.name) || (p ? coordText(p.lat, p.lon) : 'No location selected');

/* ------------------------------------------------------------ layout */
const PAGES = [['index.html', 'Home'], ['locations.html', 'Location'], ['predictions.html', 'Predictions'], ['analytics.html', 'Analytics'], ['dashboard.html', 'Dashboard'], ['about.html', 'About']];
/* The three views in time order, shown as a strip in each of their page headers. */
const TENSES = [['analytics.html', 'Past', 'History since Aug 2022'], ['locations.html', 'Now', 'Live conditions'], ['predictions.html', 'Next 24 hours', 'Model forecast']];
/* Brand mark: the Earth's limb with the ozone layer as a band above it. */
const LOGO = '<svg class="logo-mark" viewBox="0 0 28 28" aria-hidden="true"><rect width="28" height="28" rx="6" fill="#161d45"/><path d="M3 24a11 11 0 0 1 22 0" fill="none" stroke="#8fa2ff" stroke-width="3"/><path d="M8 24a6 6 0 0 1 12 0" fill="#fff"/><circle cx="20.5" cy="7.5" r="2.2" fill="#e5be00"/></svg>';

/* ------------------------------------------------------------ quick pick
 * Fills a <select> with the 38 named places the models were trained and tested on (grouped by
 * region), plus the user's saved locations, and calls onPick(lat, lon, name) when one is chosen.
 * Returns { sync(lat, lon) }: shows the matching place in the list, or "Custom point". */
function quickPick(sel, onPick) {
  let presets = [], saved = [], at = null;
  const opt = (p, v) => `<option value="${escHtml(v)}" data-lat="${p.lat}" data-lon="${p.lon}" data-name="${escHtml(p.name)}">${escHtml(p.name)}</option>`;
  function sync(lat, lon) {
    at = lat == null ? null : [Number(lat), Number(lon)];
    const hit = at && [...sel.options].find(o => o.dataset.lat && Math.abs(o.dataset.lat - at[0]) < 0.0005 && Math.abs(o.dataset.lon - at[1]) < 0.0005);
    sel.value = hit ? hit.value : '';
  }
  function fill() {
    const byRegion = {};
    presets.forEach(p => (byRegion[p.region] = byRegion[p.region] || []).push(p));
    sel.innerHTML = '<option value="">Custom point</option>'
      + (saved.length ? `<optgroup label="Your saved locations">${saved.map(p => opt(p, 's:' + p.id)).join('')}</optgroup>` : '')
      + Object.entries(byRegion).map(([region, list]) => `<optgroup label="${escHtml(region)}">${list.map(p => opt(p, 'p:' + p.id)).join('')}</optgroup>`).join('');
    if (at) sync(at[0], at[1]);
  }
  sel.addEventListener('change', () => {
    const o = sel.selectedOptions[0];
    if (o && o.dataset.lat) { at = [Number(o.dataset.lat), Number(o.dataset.lon)]; onPick(at[0], at[1], o.dataset.name); }
  });
  API.getPresets().then(list => {
    presets = list.map(p => ({ id: p.id, name: p.name, region: p.region, lat: p.latitude, lon: p.longitude }));
    fill();
  }).catch(() => {});
  if (window.OGAccount) OGAccount.onUser(async () => { try { saved = await OGAccount.locations.list(); } catch (_) { saved = []; } fill(); });
  return { sync };
}

function layout() {
  const cur = location.pathname.split('/').pop() || 'index.html';
  const a = p => `<a href="${p[0]}" class="${cur === p[0] ? 'on' : ''}"${cur === p[0] ? ' aria-current="page"' : ''}>${p[1]}</a>`;
  $('#nav').outerHTML = `<header class="nav"><div class="wrap"><a class="logo" href="index.html">${LOGO}<span>OzoneGuard <span class="ai">AI</span></span></a><button class="burger" type="button" aria-label="Open navigation menu" aria-expanded="false"><i data-lucide="menu"></i></button><nav class="links" aria-label="Main navigation">${a(PAGES[0])}<span class="grp">${a(PAGES[1])}${a(PAGES[2])}${a(PAGES[3])}</span>${a(PAGES[4])}${a(PAGES[5])}<span class="acct" id="acct"><a class="btn" href="login.html">Sign in</a></span></nav></div></header>`;
  const head = $('.page-h .wrap');
  if (head && TENSES.some(t => t[0] === cur)) {
    head.insertAdjacentHTML('beforeend', `<ol class="tense" aria-label="Time views">${TENSES.map(t => `<li><a href="${t[0]}"${cur === t[0] ? ' aria-current="page"' : ''}><b>${t[1]}</b>${t[2]}</a></li>`).join('')}</ol>`);
  }
  document.querySelectorAll('[data-uv-guide]').forEach(el => { el.innerHTML = uvGuide(); });
  document.querySelectorAll('[data-uv-scale]').forEach(el => { el.innerHTML = uvScale(); });
  const menu = $('.burger'), links = $('.links');
  menu.addEventListener('click', () => { const open = links.classList.toggle('open'); menu.setAttribute('aria-expanded', String(open)); menu.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu'); });
  links.addEventListener('click', e => { if (e.target.closest('a')) { links.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); menu.setAttribute('aria-label', 'Open navigation menu'); } });
  $('#foot').outerHTML = `<footer><div class="wrap"><div class="footer-top"><div class="footer-brand"><a class="logo" href="index.html">${LOGO}<span>OzoneGuard <span class="ai">AI</span></span></a><p>Ozone, UV and weather for any point in India: what happened, what is happening now, and what is likely over the next 24 hours.</p></div><nav class="footer-links" aria-label="Footer navigation">${PAGES.map(a).join('')}</nav></div><div class="footer-bottom"><span>© ${new Date().getFullYear()} OzoneGuard AI</span><span>${DATA_NOTE}</span></div></div></footer>`;
  window.lucide && lucide.createIcons();
  if (window.OGAccount) OGAccount.onUser(renderAccount);
}

/* Nav account area: "Sign in" when signed out, name + "Sign out" when signed in. */
function renderAccount(user) {
  const box = $('#acct');
  if (!box) return;
  if (!user) {
    box.innerHTML = '<a class="btn" href="login.html">Sign in</a>';
  } else {
    const name = user.displayName || (user.email || '').split('@')[0] || 'Account';
    box.innerHTML = `<a class="acct-name" href="dashboard.html" title="${escHtml(user.email || '')}"><i data-lucide="user-round"></i>${escHtml(name)}</a><button class="btn ghost" type="button" id="signout">Sign out</button>`;
    $('#signout').addEventListener('click', async () => { try { await OGAccount.signOut(); } catch (e) { console.error(e); } });
  }
  window.lucide && lucide.createIcons();
}

const state = (el, msg, err) => el.innerHTML = `<div class="state ${err ? 'err' : ''}">${escHtml(msg)}</div>`;

/* ------------------------------------------------------------ charts (Chart.js) */
const charts = {};
function chart(id, type, labels, datasets, y, opts = {}) {
  charts[id] && charts[id].destroy();
  Chart.defaults.font.family = "'Instrument Sans', system-ui, sans-serif";
  Chart.defaults.font.size = 12;
  const grid = { color: '#e7eaf2' }, tick = { color: '#5c6283' };
  charts[id] = new Chart(document.getElementById(id), {
    type, data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: datasets.length > 1, align: 'start', labels: { color: '#30365a', boxWidth: 14, boxHeight: 3, padding: 14 } }, tooltip: { backgroundColor: '#161d45', titleColor: '#fff', bodyColor: '#e3e7f6', padding: 10, cornerRadius: 6, boxPadding: 4 } },
      scales: {
        y: { title: { display: true, text: y, color: '#5c6283' }, beginAtZero: true, grid, border: { display: false }, ticks: tick },
        x: { title: { display: !!opts.x, text: opts.x || '', color: '#5c6283' }, grid: { display: false }, border: { color: '#c3cadf' }, ticks: { ...tick, maxTicksLimit: 12, maxRotation: 0 } }
      },
      ...opts.o
    }
  });
  return charts[id];
}
const ds = (label, data, color, extra) => ({ label, data, borderColor: color, backgroundColor: color + '33', borderWidth: 2, tension: .3, pointRadius: 2, pointHoverRadius: 5, pointBackgroundColor: color, ...extra });

document.addEventListener('DOMContentLoaded', layout);
