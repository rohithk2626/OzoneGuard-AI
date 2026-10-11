/* Shared helpers: nav, footer, account state, selected place, UV categories, charts. */
const $ = (s, r = document) => r.querySelector(s);
const escHtml = v => String(v ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');

/* WHO UV categories. The index is rounded to a whole number first, as on the backend (ml/risk.py). */
const UVC = [
  [2, 'Low', '#2ea043', 'Safe for most people. Sunglasses on bright days.'],
  [5, 'Moderate', '#d4a72c', 'Wear sunscreen and sunglasses; seek shade around midday.'],
  [7, 'High', '#e8801a', 'Use SPF 30+, a hat and sunglasses; limit sun 10am–4pm.'],
  [10, 'Very High', '#dc3545', 'Avoid midday sun; cover up and use SPF 50+, reapply often.'],
  [99, 'Extreme', '#8b5cf6', 'Stay indoors at midday; unprotected skin can burn in minutes.']
];
const UV_COLOR = Object.fromEntries(UVC.map(c => [c[1], c[2]]));
const uvCat = v => { const r = Math.floor(Number(v) + 0.5), c = UVC.find(x => r <= x[0]); return { label: c[1], color: c[2], tip: c[3] }; };
const riskBadge = label => `<span class="badge" style="--c:${UV_COLOR[label] || '#87939a'}">${escHtml(label || 'Unavailable')}</span>`;
const fmtNum = (v, d = 1) => v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d);
const fmt = iso => new Date(iso).toLocaleString();

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

function layout() {
  const cur = location.pathname.split('/').pop() || 'index.html';
  const a = p => `<a href="${p[0]}" class="${cur === p[0] ? 'on' : ''}"${cur === p[0] ? ' aria-current="page"' : ''}>${p[1]}</a>`;
  $('#nav').outerHTML = `<header class="nav"><div class="wrap"><a class="logo" href="index.html"><span class="logo-mark"><i data-lucide="shield-check"></i></span>OzoneGuard AI</a><button class="burger" type="button" aria-label="Open navigation menu" aria-expanded="false"><i data-lucide="menu"></i></button><nav class="links" aria-label="Main navigation">${a(PAGES[0])}<span class="grp">${a(PAGES[1])}${a(PAGES[2])}${a(PAGES[3])}</span>${a(PAGES[4])}${a(PAGES[5])}<span class="acct" id="acct"><a class="btn" href="login.html">Sign in <i data-lucide="arrow-up-right"></i></a></span></nav></div></header>`;
  const menu = $('.burger'), links = $('.links');
  menu.addEventListener('click', () => { const open = links.classList.toggle('open'); menu.setAttribute('aria-expanded', String(open)); menu.setAttribute('aria-label', open ? 'Close navigation menu' : 'Open navigation menu'); });
  links.addEventListener('click', e => { if (e.target.closest('a')) { links.classList.remove('open'); menu.setAttribute('aria-expanded', 'false'); menu.setAttribute('aria-label', 'Open navigation menu'); } });
  $('#foot').outerHTML = `<footer><div class="wrap"><div class="footer-top"><div class="footer-brand"><a class="logo" href="index.html"><span class="logo-mark"><i data-lucide="shield-check"></i></span>OzoneGuard AI</a><p>Ozone, UV and weather for any point in India: what happened, what is happening now, and what is likely over the next 24 hours.</p></div><nav class="footer-links" aria-label="Footer navigation">${PAGES.map(a).join('')}</nav></div><div class="footer-bottom"><span>© ${new Date().getFullYear()} OzoneGuard AI</span><span>${DATA_NOTE}</span></div></div></footer>`;
  window.lucide && lucide.createIcons();
  if (window.OGAccount) OGAccount.onUser(renderAccount);
}

/* Nav account area: "Sign in" when signed out, name + "Sign out" when signed in. */
function renderAccount(user) {
  const box = $('#acct');
  if (!box) return;
  if (!user) {
    box.innerHTML = '<a class="btn" href="login.html">Sign in <i data-lucide="arrow-up-right"></i></a>';
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
  const grid = { color: '#e6eeea' }, tick = { color: '#657982' };
  charts[id] = new Chart(document.getElementById(id), {
    type, data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { display: datasets.length > 1, labels: { color: '#1c3440', boxWidth: 14, boxHeight: 3 } } },
      scales: {
        y: { title: { display: true, text: y, color: '#657982' }, beginAtZero: true, grid, ticks: tick },
        x: { title: { display: !!opts.x, text: opts.x || '', color: '#657982' }, grid: { display: false }, ticks: { ...tick, maxTicksLimit: 12, maxRotation: 0 } }
      },
      ...opts.o
    }
  });
  return charts[id];
}
const ds = (label, data, color, extra) => ({ label, data, borderColor: color, backgroundColor: color + '33', borderWidth: 2, tension: .35, pointRadius: 2, pointHoverRadius: 5, ...extra });

document.addEventListener('DOMContentLoaded', layout);
