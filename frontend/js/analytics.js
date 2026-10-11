/* PAST: real history from GET /api/v1/analytics/history (CAMS ozone/UV + archived weather).
 * No values are generated in the browser. If the backend cannot return real history,
 * the page shows the reason instead of numbers. */
(() => {
  const C = { one: '#0e9384', two: '#c2570c' };              // validated pair (teal, orange): colour-blind safe on white
  const DEFAULT = { lat: 17.385, lon: 78.4867, name: 'Hyderabad' };
  const BOUNDS = L.latLngBounds([6.0, 68.0], [37.6, 97.6]);
  const EARLIEST = '2022-08-04', MAX_DAYS = 366;
  let map, marker, presets = [], saved = [], last = null, place = null;

  /* ---- dates: plain YYYY-MM-DD strings, Indian calendar days */
  const todayIST = () => new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' });
  const toDate = s => new Date(s + 'T00:00:00Z');
  const shift = (s, days) => { const d = toDate(s); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); };
  const span = (a, b) => Math.round((toDate(b) - toDate(a)) / 864e5) + 1;
  const nice = s => toDate(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
  const short = s => toDate(s).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', timeZone: 'UTC' });

  const mean = a => { const v = a.filter(x => x !== null && x !== undefined); return v.length ? v.reduce((p, c) => p + c, 0) / v.length : null; };
  const sum = a => { const v = a.filter(x => x !== null && x !== undefined); return v.length ? v.reduce((p, c) => p + c, 0) : null; };
  const maxOf = a => { const v = a.filter(x => x !== null && x !== undefined); return v.length ? Math.max(...v) : null; };
  const minOf = a => { const v = a.filter(x => x !== null && x !== undefined); return v.length ? Math.min(...v) : null; };

  function showError(title, message) {
    $('#out').innerHTML = `<div class="note" role="alert"><strong>${escHtml(title)}</strong><br>${escHtml(message)}</div>`;
  }

  /* ---- grouping daily rows into weeks or months (means of means, max of max, rain summed) */
  function group(rows, how) {
    if (how === 'Daily') return rows.map(r => ({ ...r, label: short(r.date) }));
    const buckets = new Map();
    rows.forEach((r, i) => {
      const key = how === 'Monthly' ? r.date.slice(0, 7) : Math.floor(i / 7);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(r);
    });
    return [...buckets.values()].map(b => {
      const f = k => b.map(r => r[k]);
      const first = b[0].date, lastDay = b[b.length - 1].date;
      const uv = maxOf(f('uv_max'));
      return {
        date: first,
        label: how === 'Monthly' ? toDate(first).toLocaleDateString('en-IN', { month: 'short', year: '2-digit', timeZone: 'UTC' }) : `${short(first)}–${short(lastDay)}`,
        ozone_mean: mean(f('ozone_mean')), ozone_max: maxOf(f('ozone_max')), uv_max: uv, uv_risk: uv === null ? null : uvCat(uv).label,
        temp_mean: mean(f('temp_mean')), temp_min: minOf(f('temp_min')), temp_max: maxOf(f('temp_max')),
        humidity_mean: mean(f('humidity_mean')), cloud_mean: mean(f('cloud_mean')), precip_sum: sum(f('precip_sum'))
      };
    });
  }

  const one = v => (v === null || v === undefined ? null : +Number(v).toFixed(1));

  function render(d) {
    last = d;
    const s = d.summary, how = $('#per').value;
    const complete = d.daily.filter(r => !r.partial);
    const rows = group(complete.length ? complete : d.daily, how);
    const skipped = d.daily.length - (complete.length ? complete.length : d.daily.length);
    const labels = rows.map(r => r.label);
    const riskDays = Object.entries(s.uv_risk_days).filter(([, n]) => n > 0);
    const rel = d.relationships;
    const relRow = (name, r, meaning) => `<tr><td>${name}</td><td class="num">${r.r === null ? '—' : (r.r > 0 ? '+' : '') + r.r.toFixed(2)}</td><td>${r.r === null ? 'Not enough data in this period.' : meaning(r.r)}</td></tr>`;
    const strength = r => { const a = Math.abs(r); return a < 0.2 ? 'almost no link' : a < 0.5 ? 'a moderate link' : 'a strong link'; };
    const dir = (r, up, down) => `${strength(r)}${Math.abs(r) < 0.2 ? '' : r > 0 ? ': ' + up : ': ' + down}`;

    $('#out').innerHTML = `
    <div class="pred-head"><div><span class="eyebrow">${escHtml(nice(d.period.start))} to ${escHtml(nice(d.period.end))}</span>
      <h2>${escHtml(placeLabel(place))}</h2>
      <p class="mut">${escHtml(coordText(d.location.latitude, d.location.longitude))} · ${s.days} day${s.days === 1 ? '' : 's'} · days are Indian days (IST)</p></div></div>

    <div class="pred-kpis">
      <div class="card kpi"><div class="l">Ground-level ozone, average</div><div class="v">${fmtNum(s.ozone_mean, 0)}<small>µg/m³</small></div><div class="s">hourly range ${fmtNum(s.ozone_min, 0)}–${fmtNum(s.ozone_max, 0)} µg/m³</div></div>
      <div class="card kpi peak" style="--c:${s.highest_uv ? uvCat(s.highest_uv.value).color : '#999'}"><div class="l">Highest UV index</div><div class="v">${s.highest_uv ? fmtNum(s.highest_uv.value, 1) : '—'}</div><div class="s">${s.highest_uv ? `${riskBadge(uvCat(s.highest_uv.value).label)} on ${escHtml(nice(s.highest_uv.date))}` : 'No UV values'}</div></div>
      <div class="card kpi"><div class="l">Daily peak UV, average</div><div class="v">${fmtNum(s.uv_daily_max_mean, 1)}</div><div class="s">${riskDays.map(([k, n]) => `${n} day${n === 1 ? '' : 's'} ${escHtml(k)}`).join(' · ') || '—'}</div></div>
      <div class="card kpi"><div class="l">Weather</div><div class="v">${fmtNum(s.temp_mean, 1)}<small>°C average</small></div><div class="s">humidity ${fmtNum(s.humidity_mean, 0)}% · cloud ${fmtNum(s.cloud_mean, 0)}% · rain ${fmtNum(s.precip_total, 0)} mm</div></div>
    </div>
    ${skipped ? `<p class="mut" style="margin-top:12px;font-size:.84rem">${skipped} day${skipped === 1 ? '' : 's'} with incomplete data (usually today, which is still in progress) ${skipped === 1 ? 'is' : 'are'} left out of the charts and averages.</p>` : ''}

    <div class="grid two" style="margin-top:18px">
      <div class="card"><h3>Ground-level ozone</h3><p>${how} average and highest hourly value, in µg/m³.</p><div class="chartbox"><canvas id="a-oz"></canvas></div></div>
      <div class="card"><h3>Peak UV index</h3><p>Highest UV index ${how === 'Daily' ? 'each day' : 'in each ' + (how === 'Weekly' ? 'week' : 'month')}; bar colour is the WHO risk level.</p><div class="uv-key">${UVC.map(c => `<span><i style="background:${c[2]}"></i>${c[1]}</span>`).join('')}</div><div class="chartbox short"><canvas id="a-uv"></canvas></div></div>
      <div class="card"><h3>Temperature</h3><p>${how} average, with the lowest-to-highest range shaded (°C).</p><div class="chartbox"><canvas id="a-temp"></canvas></div></div>
      <div class="card"><h3>Humidity and cloud cover</h3><p>${how} averages, both in percent.</p><div class="chartbox"><canvas id="a-hum"></canvas></div></div>
      <div class="card"><h3>Rain</h3><p>${how} total, in millimetres.</p><div class="chartbox"><canvas id="a-rain"></canvas></div></div>
      <div class="card"><h3>Ozone against UV</h3><p>Each dot is one day: its average ozone against its peak UV.</p><div class="chartbox"><canvas id="a-sc"></canvas></div></div>
      <div class="card"><h3>An average day: ozone</h3><p>Average for each hour of the day (IST) over this period, in µg/m³.</p><div class="chartbox"><canvas id="a-doz"></canvas></div></div>
      <div class="card"><h3>An average day: UV index</h3><p>Average for each hour of the day (IST) over this period.</p><div class="chartbox"><canvas id="a-duv"></canvas></div></div>
    </div>

    <div class="grid two" style="margin-top:18px">
      <div class="card"><h3>How things moved together</h3><p>Correlation in daylight hours of this period: +1 means they rise together, −1 means one rises as the other falls, 0 means no link.</p>
        <div class="tw"><table class="ptable"><thead><tr><th>Pair</th><th class="num">r</th><th>What it means here</th></tr></thead><tbody>
          ${relRow('Ozone and sunlight', rel.ozone_vs_sunlight, r => dir(r, 'more sunlight, more ozone', 'more sunlight, less ozone'))}
          ${relRow('Ozone and UV index', rel.ozone_vs_uv, r => dir(r, 'they rise together', 'they move opposite ways'))}
          ${relRow('Ozone and temperature', rel.ozone_vs_temperature, r => dir(r, 'hotter hours have more ozone', 'hotter hours have less ozone'))}
          ${relRow('Ozone and humidity', rel.ozone_vs_humidity, r => dir(r, 'humid hours have more ozone', 'humid hours have less ozone'))}
          ${relRow('UV index and cloud', rel.uv_vs_cloud, r => dir(r, 'cloudier hours have higher UV', 'cloudier hours have lower UV'))}
        </tbody></table></div>
        <p style="margin-top:10px">${escHtml(rel.note)}</p></div>
      <div class="card"><h3>${how} values</h3><p>The same numbers as the charts.</p>
        <div class="tw"><table class="ptable"><thead><tr><th>${how === 'Daily' ? 'Day' : how === 'Weekly' ? 'Week' : 'Month'}</th><th class="num">O₃ avg</th><th class="num">O₃ max</th><th class="num">Peak UV</th><th>Risk</th><th class="num hide-sm">Temp °C</th><th class="num hide-sm">Rain mm</th></tr></thead><tbody>
          ${rows.map(r => `<tr><td>${escHtml(r.label)}</td><td class="num">${fmtNum(r.ozone_mean, 0)}</td><td class="num">${fmtNum(r.ozone_max, 0)}</td><td class="num">${fmtNum(r.uv_max, 1)}</td><td>${r.uv_risk ? riskBadge(r.uv_risk) : '—'}</td><td class="num hide-sm">${fmtNum(r.temp_mean, 1)}</td><td class="num hide-sm">${fmtNum(r.precip_sum, 1)}</td></tr>`).join('')}
        </tbody></table></div></div>
    </div>

    <div class="card data-source-card" style="margin-top:18px"><span class="eyebrow">Data sources &amp; status</span>
      <div class="source-list">${d.data_status.sources.map(x => `<div><strong>${escHtml(x.name)}</strong><span>${escHtml(x.purpose)}</span><em>${escHtml(x.status)}</em></div>`).join('')}</div>
      <p style="margin-top:10px;font-size:.84rem">${escHtml(d.data_status.note)}</p>
      <p style="margin-top:6px;font-size:.82rem">Contains modified Copernicus Atmosphere Monitoring Service information; weather data by Open-Meteo.com (CC BY 4.0).</p>
    </div>`;

    const dashed = { borderDash: [5, 4], pointRadius: 0, backgroundColor: 'transparent' };
    const few = rows.length <= 45;
    const pt = { pointRadius: few ? 2 : 0 };
    chart('a-oz', 'line', labels, [ds('Average', rows.map(r => one(r.ozone_mean)), C.one, { fill: false, ...pt }), ds('Highest hour', rows.map(r => one(r.ozone_max)), C.two, { fill: false, ...dashed })], 'µg/m³');
    chart('a-uv', 'bar', labels, [{ label: 'Peak UV index', data: rows.map(r => r.uv_max), backgroundColor: rows.map(r => UV_COLOR[r.uv_risk] || '#87939a'), borderRadius: 4, maxBarThickness: 22 }], 'UV index',
      { o: { plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` Peak UV ${fmtNum(c.parsed.y, 1)} · ${rows[c.dataIndex].uv_risk || ''}` } } } } });
    chart('a-temp', 'line', labels, [
      ds('Highest', rows.map(r => one(r.temp_max)), C.one, { borderWidth: 0, pointRadius: 0, fill: false }),
      ds('Lowest to highest', rows.map(r => one(r.temp_min)), C.one, { borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: C.one + '2e' }),
      ds('Average', rows.map(r => one(r.temp_mean)), C.one, { fill: false, ...pt })], '°C',
      { o: { plugins: { legend: { display: true, labels: { filter: it => it.text !== 'Highest', boxWidth: 14, boxHeight: 3 } } } } });
    charts['a-temp'].options.scales.y.beginAtZero = false; charts['a-temp'].update();
    chart('a-hum', 'line', labels, [ds('Humidity', rows.map(r => one(r.humidity_mean)), C.one, { fill: false, ...pt }), ds('Cloud cover', rows.map(r => one(r.cloud_mean)), C.two, { fill: false, ...dashed })], '%');
    chart('a-rain', 'bar', labels, [{ label: 'Rain', data: rows.map(r => one(r.precip_sum)), backgroundColor: C.one, borderRadius: 4, maxBarThickness: 22 }], 'mm');
    const dots = (complete.length ? complete : d.daily).filter(r => r.ozone_mean !== null && r.uv_max !== null);
    chart('a-sc', 'scatter', undefined, [{ label: 'One day', data: dots.map(r => ({ x: r.ozone_mean, y: r.uv_max, day: r.date })), backgroundColor: C.one + 'b3', borderColor: '#fff', borderWidth: 1, pointRadius: 4, pointHoverRadius: 6 }], 'Peak UV index',
      { o: { interaction: { mode: 'nearest', intersect: true }, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => ` ${short(c.raw.day)}: ozone ${fmtNum(c.raw.x, 0)} µg/m³, peak UV ${fmtNum(c.raw.y, 1)}` } } },
        scales: { x: { type: 'linear', title: { display: true, text: 'Average ground-level ozone (µg/m³)', color: '#657982' }, grid: { color: '#e6eeea' } }, y: { beginAtZero: true, title: { display: true, text: 'Peak UV index', color: '#657982' }, grid: { color: '#e6eeea' } } } } });
    const hours = d.average_day.map(h => `${String(h.hour_ist).padStart(2, '0')}:00`);
    chart('a-doz', 'line', hours, [ds('Ozone', d.average_day.map(h => h.ozone), C.one, { fill: true, pointRadius: 0 })], 'µg/m³', { x: 'Hour of day (IST)' });
    chart('a-duv', 'line', hours, [ds('UV index', d.average_day.map(h => h.uv), C.one, { fill: true, pointRadius: 0 })], 'UV index', { x: 'Hour of day (IST)' });
    window.lucide && lucide.createIcons();
  }

  async function run() {
    const lat = Number($('#latitude').value), lon = Number($('#longitude').value);
    const from = $('#from').value, to = $('#to').value, today = todayIST();
    if (!Number.isFinite(lat) || !Number.isFinite(lon) || $('#latitude').value === '' || $('#longitude').value === '') return showError('Choose a place', 'Pick a city, click the map or type a latitude and longitude.');
    if (!BOUNDS.contains([lat, lon])) return showError('Outside supported area', 'Choose a point inside India.');
    if (!from || !to) return showError('Choose the dates', 'Set both a "From" and a "To" date.');
    if (from > to) return showError('Check the dates', 'The "From" date must be on or before the "To" date.');
    if (to > today) return showError('Check the dates', 'The "To" date cannot be in the future.');
    if (from < EARLIEST) return showError('Check the dates', 'History starts on 4 August 2022, when the CAMS record for India begins.');
    if (span(from, to) > MAX_DAYS) return showError('Range too long', 'Choose at most 366 days at a time.');

    const known = [...saved, ...presets].find(p => Math.abs(p.lat - lat) < 0.02 && Math.abs(p.lon - lon) < 0.02);   // within ~2 km: use that place's name
    place = setPlace(lat, lon, known ? known.name : null);
    marker.setLatLng([lat, lon]);
    $('#out').innerHTML = '<div class="card"><p>Loading real history… (CAMS ozone and UV, plus archived weather)</p></div>';
    try {
      render(await API.getHistory(lat, lon, from, to));
    } catch (e) {
      const m = e.message || 'Unknown error';
      if (/provider|unavailable|Open-Meteo|no_data/i.test(m)) showError('History unavailable', 'A data provider did not return history, so nothing is shown. ' + m);
      else showError('Could not load history', m);
    }
  }

  function choose(lat, lon) {
    $('#latitude').value = Number(lat).toFixed(5); $('#longitude').value = Number(lon).toFixed(5);
    const hit = [...$('#preset').options].find(o => o.dataset.lat && Math.abs(o.dataset.lat - lat) < 0.0005 && Math.abs(o.dataset.lon - lon) < 0.0005);
    $('#preset').value = hit ? hit.value : '';
    run();
  }

  function fillPresets() {
    const sel = $('#preset'), byRegion = {};
    presets.forEach(p => (byRegion[p.region] = byRegion[p.region] || []).push(p));
    const opt = (p, v) => `<option value="${escHtml(v)}" data-lat="${p.lat}" data-lon="${p.lon}">${escHtml(p.name)}</option>`;
    sel.innerHTML = '<option value="">Custom point</option>'
      + (saved.length ? `<optgroup label="Your saved locations">${saved.map(p => opt(p, 's:' + p.id)).join('')}</optgroup>` : '')
      + Object.entries(byRegion).map(([region, list]) => `<optgroup label="${escHtml(region)}">${list.map(p => opt(p, 'p:' + p.id)).join('')}</optgroup>`).join('');
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const today = todayIST();
    $('#to').value = today; $('#from').value = shift(today, -29);
    ['from', 'to'].forEach(id => { $('#' + id).min = EARLIEST; $('#' + id).max = today; });
    place = getPlace() || DEFAULT;
    $('#latitude').value = place.lat; $('#longitude').value = place.lon;

    map = L.map('map', { minZoom: 4, maxZoom: 14, maxBounds: BOUNDS.pad(0.08), maxBoundsViscosity: 0.85 }).setView([22.5, 79], 5);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap contributors' }).addTo(map);
    marker = L.marker([place.lat, place.lon]).addTo(map);
    map.on('click', e => choose(e.latlng.lat, e.latlng.lng));

    $('#run').addEventListener('click', run);
    $('#per').addEventListener('change', () => { if (last) render(last); });
    $('#preset').addEventListener('change', e => { const o = e.target.selectedOptions[0]; if (o && o.dataset.lat) choose(Number(o.dataset.lat), Number(o.dataset.lon)); });
    document.querySelectorAll('.range-row button').forEach(b => b.addEventListener('click', () => {
      const end = todayIST(); $('#to').value = end; $('#from').value = shift(end, -(Number(b.dataset.days) - 1)); run();
    }));

    try { presets = (await API.getPresets()).map(p => ({ id: p.id, name: p.name, region: p.region, lat: p.latitude, lon: p.longitude })); } catch (_) { presets = []; }
    fillPresets();
    OGAccount.onUser(async () => { try { saved = await OGAccount.locations.list(); } catch (_) { saved = []; } fillPresets(); });
    run();
  });
})();
