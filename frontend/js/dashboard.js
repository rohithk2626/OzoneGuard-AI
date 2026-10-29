/* Dashboard: live conditions (NOW), 24-hour UV forecast (FUTURE), 14-day peak UV (PAST)
 * for the selected place, plus saved locations. Everything comes from the backend or
 * from the user's own saved list; nothing is generated in the browser. */
(() => {
  const C = { one: '#b8620b' };   // sun amber: the UV series colour used across the site
  const todayIST = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  const shift = (s, days) => { const d = new Date(s + 'T00:00:00Z'); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
  const short = s => new Date(s + 'T00:00:00Z').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const istTime = iso => new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', hour12: true, timeZone: 'Asia/Kolkata' });
  const passDate = iso => (iso ? new Date(iso).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : 'an unknown date');
  const boxMsg = (id, text, err) => { $('#' + id).innerHTML = `<div class="state ${err ? 'err' : ''}">${escHtml(text)}</div>`; };
  let place = null, saved = [];

  /* ---------------------------------------------------------------- NOW */
  async function loadNow() {
    const box = $('#sum');
    box.innerHTML = '<div class="card state">Loading live conditions…</div>';
    try {
      const d = await API.getLocationOverview(place.lat, place.lon), w = d.weather || {}, o = d.ozone || {}, p = d.location.place || {};
      const name = p.city || p.district || p.state;
      if (name && !place.name) { place = setPlace(place.lat, place.lon, name); heading(); }
      const live = w.status !== 'unavailable', uv = live ? w.uv_index : null;
      const cat = uv === null || uv === undefined ? null : uvCat(uv);
      box.innerHTML = `
        <div class="card kpi peak" style="--c:${cat ? cat.color : '#87939a'}"><div class="l">UV index now</div><div class="v">${fmtNum(uv, 1)}</div><div class="s">${cat ? riskBadge(cat.label) + ' ' + escHtml(cat.tip) : 'UV is unavailable right now.'}</div>${cat ? uvScale(uv) : ''}</div>
        <div class="card kpi"><div class="l">Weather now</div><div class="v">${fmtNum(w.temperature, 1)}<small>°C</small></div><div class="s">${live ? `feels like ${fmtNum(w.feels_like, 1)} °C · humidity ${fmtNum(w.humidity, 0)}% · cloud ${fmtNum(w.cloud_cover, 0)}% · wind ${fmtNum(w.wind_speed, 1)} km/h` : 'The weather provider did not respond.'}</div></div>
        <div class="card kpi"><div class="l">Ozone layer (total column)</div><div class="v">${fmtNum(o.value, 0)}<small>DU</small></div><div class="s">${o.status === 'live' ? 'NASA OMI satellite pass of ' + escHtml(passDate(o.observation_time)) : o.status === 'stale' ? 'From ' + escHtml(passDate(o.observation_time)) + '. ' + escHtml(o.message || '') : o.status === 'requires_earthdata_auth' ? 'Needs a NASA Earthdata token on the backend (docs/blockers.md).' : escHtml(o.message || 'Unavailable right now.')}</div></div>`;
    } catch (e) { box.innerHTML = `<div class="note" role="alert"><strong>Live conditions unavailable.</strong><br>${escHtml(e.message)}</div>`; }
    window.lucide && lucide.createIcons();
  }

  /* ---------------------------------------------------------------- FUTURE */
  async function loadForecast() {
    $('#f-box').innerHTML = '<canvas id="f"></canvas>';
    try {
      const r = await API.getPredictions24h(place.lat, place.lon), P = r.predictions, peak = P.findIndex(p => p.time_utc === r.peak_uv.time_utc);
      chart('f', 'line', P.map(p => istTime(p.time_ist)), [
        ds('Upper range', P.map(p => p.uv.upper), C.one, { borderWidth: 0, pointRadius: 0, fill: false }),
        ds('90% range', P.map(p => p.uv.lower), C.one, { borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: C.one + '2e' }),
        ds('Forecast UV index', P.map(p => p.uv.value), C.one, { fill: false, pointRadius: P.map((_, i) => (i === peak ? 6 : 0)) })], 'UV index',
        { x: 'Time (IST)', o: { plugins: { legend: { labels: { filter: it => it.text !== 'Upper range', boxWidth: 14, boxHeight: 3 } },
          subtitle: { display: true, align: 'start', color: '#5c6283', padding: { bottom: 8 }, text: `Peak ${fmtNum(r.peak_uv.value, 1)} (${r.peak_uv.risk}) at ${istTime(r.peak_uv.time_ist)}` } } } });
    } catch (e) { boxMsg('f-box', 'Forecast unavailable: ' + e.message, 1); }
  }

  /* ---------------------------------------------------------------- PAST */
  async function loadHistory() {
    $('#h-box').innerHTML = '<canvas id="h"></canvas>';
    $('#uv-key').innerHTML = UVC.map(c => `<span><i style="background:${c[2]}"></i>${c[1]}</span>`).join('');
    try {
      const end = todayIST(), r = await API.getHistory(place.lat, place.lon, shift(end, -14), end);
      const rows = r.daily.filter(d => !d.partial && d.uv_max !== null).slice(-14);
      if (!rows.length) return boxMsg('h-box', 'No complete days in the last two weeks.');
      chart('h', 'bar', rows.map(d => short(d.date)), [{ label: 'Peak UV index', data: rows.map(d => d.uv_max), backgroundColor: rows.map(d => UV_COLOR[d.uv_risk] || '#87939a'), borderRadius: 4, maxBarThickness: 22 }], 'UV index',
        { o: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` Peak UV ${fmtNum(c.parsed.y, 1)} · ${rows[c.dataIndex].uv_risk || ''}` } } } } });
    } catch (e) { boxMsg('h-box', 'History unavailable: ' + e.message, 1); }
  }

  /* ---------------------------------------------------------------- saved locations */
  function renderSaved() {
    const box = $('#saved'), user = OGAccount.user;
    $('#saved-where').innerHTML = user
      ? `Signed in as <b>${escHtml(user.displayName || user.email)}</b>. These are stored in your account.`
      : `Stored in this browser only. <a href="login.html">Sign in</a> to keep them on every device${OGAccount.configured ? '' : ' (accounts are not set up yet)'}.`;
    if (!saved.length) return (box.innerHTML = '<div class="state">No saved locations yet. Use "Save this location" above, or on the Location page.</div>');
    box.innerHTML = `<ul class="saved-list">${saved.map(s => `
      <li data-id="${escHtml(s.id)}" class="${place && Math.abs(s.lat - place.lat) < 0.0005 && Math.abs(s.lon - place.lon) < 0.0005 ? 'current' : ''}">
        <button class="saved-open" type="button" data-act="open"><strong>${escHtml(s.name)}</strong><span>${escHtml(coordText(s.lat, s.lon))}</span></button>
        <span class="saved-actions"><button type="button" data-act="where">Location</button><button type="button" data-act="forecast">Forecast</button><button type="button" data-act="history">History</button><button type="button" class="danger" data-act="remove">Remove</button></span>
      </li>`).join('')}</ul>`;
  }

  async function refreshSaved() {
    try { saved = await OGAccount.locations.list(); renderSaved(); }
    catch (e) { $('#saved').innerHTML = `<div class="state err">${escHtml(OGAccount.message(e))}</div>`; }
  }

  async function onSavedClick(e) {
    const btn = e.target.closest('button[data-act]'), li = e.target.closest('li[data-id]');
    if (!btn || !li) return;
    const row = saved.find(s => s.id === li.dataset.id);
    if (!row) return;
    const act = btn.dataset.act;
    if (act === 'remove') {
      if (btn.dataset.armed !== '1') { btn.dataset.armed = '1'; btn.textContent = 'Confirm remove'; setTimeout(() => { if (btn.isConnected) { btn.dataset.armed = ''; btn.textContent = 'Remove'; } }, 4000); return; }
      btn.disabled = true;
      try { await OGAccount.locations.remove(row.id); } catch (x) { $('#save-msg').textContent = OGAccount.message(x); $('#save-msg').className = 'save-msg err'; }
      return refreshSaved();
    }
    setPlace(row.lat, row.lon, row.name);
    if (act === 'open') return show(getPlace());
    if (act === 'where') { try { sessionStorage.setItem('og_open_place', '1'); } catch (_) {} location.href = 'locations.html'; }
    if (act === 'forecast') location.href = 'predictions.html';
    if (act === 'history') location.href = 'analytics.html';
  }

  async function saveCurrent() {
    const note = $('#save-msg');
    if (!place) return;
    note.className = 'save-msg'; note.textContent = 'Saving…';
    try {
      const r = await OGAccount.locations.add({ name: place.name, lat: place.lat, lon: place.lon });
      note.textContent = r.already ? `Already saved as "${r.name}".` : `Saved to ${OGAccount.locations.mode() === 'cloud' ? 'your account' : 'this device'}.`;
      note.classList.add('ok');
      refreshSaved();
    } catch (e) { note.textContent = OGAccount.message(e); note.classList.add('err'); }
  }

  /* ---------------------------------------------------------------- page */
  function heading() {
    $('#loc').textContent = placeLabel(place);
    $('#loc-sub').textContent = place ? coordText(place.lat, place.lon) : '';
  }

  function show(p) {
    place = p; heading(); renderSaved();
    $('#save-msg').textContent = '';
    loadNow(); loadForecast(); loadHistory();
  }

  function empty() {
    $('#loc').textContent = 'no place yet';
    $('#save-place').style.display = 'none';
    $('#sum').innerHTML = '<div class="card"><p>Choose a place on the <a href="locations.html">Location page</a> (or open one of your saved locations below) to see its live conditions here.</p></div>';
    boxMsg('f-box', 'Pick a place to see its 24-hour forecast.'); boxMsg('h-box', 'Pick a place to see its recent history.');
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('#saved').addEventListener('click', onSavedClick);
    $('#save-place').addEventListener('click', saveCurrent);
    const start = getPlace();
    if (start) show(start); else empty();
    OGAccount.onUser(async () => {
      await refreshSaved();
      if (!place && saved.length) { $('#save-place').style.display = ''; setPlace(saved[0].lat, saved[0].lon, saved[0].name); show(getPlace()); }
    });
  });
})();
