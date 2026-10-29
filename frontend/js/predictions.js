/* FUTURE: 24-hour ozone / UV predictions from GET /api/v1/predictions/24h.
 * No values are generated in the browser. If the backend cannot produce a
 * real forecast, the page shows the reason instead of a number. */
let pmap, pmarker, qp;
const P_BOUNDS = L.latLngBounds([6.0, 68.0], [37.5, 97.5]);
const RISK_COLOR = UV_COLOR;   /* WHO category colours, defined once in js/main.js */

const esc = v => String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const num = (v, d=1) => v === null || v === undefined || Number.isNaN(Number(v)) ? '—' : Number(v).toFixed(d);
const istTime = iso => new Date(iso).toLocaleTimeString('en-IN', {hour:'2-digit', minute:'2-digit', hour12:true, timeZone:'Asia/Kolkata'});
const istDay = iso => new Date(iso).toLocaleDateString('en-IN', {weekday:'short', day:'numeric', month:'short', timeZone:'Asia/Kolkata'});
const badge = r => `<span class="badge" style="--c:${RISK_COLOR[r] || '#87939a'}">${esc(r)}</span>`;

/* The selected point is shared with the other pages (js/main.js). */
function saveCoords(lat, lon) { setPlace(lat, lon); }
function loadCoords() { return getPlace(); }

function showError(title, message) {
  $('#out').innerHTML = `<div class="note" role="alert"><strong>${esc(title)}</strong><br>${esc(message)}</div>`;
}

async function forecast(lat, lon) {
  lat = Number(lat); lon = Number(lon);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return showError('Invalid coordinates', 'Enter a numeric latitude and longitude.');
  if (!P_BOUNDS.contains([lat, lon])) return showError('Outside supported area', 'Choose a point inside India.');
  $('#latitude').value = lat.toFixed(5); $('#longitude').value = lon.toFixed(5);
  if (qp) qp.sync(lat, lon);
  pmarker.setLatLng([lat, lon]); saveCoords(lat, lon);
  $('#out').innerHTML = '<div class="card state">Running the forecast models… (fetching latest CAMS composition and weather forecast)</div>';
  try {
    render(await API.getPredictions24h(lat, lon, $('#model').value));
  } catch (e) {
    const msg = e.message || 'Unknown error', why = (e.code || '') + ' ' + msg;
    if (/model_not_trained|artifacts/i.test(why)) showError('Predictions unavailable', 'The forecast models have not been trained on this server yet. ' + msg);
    else if (/provider|unavailable|Open-Meteo/i.test(why)) showError('Predictions unavailable', 'A required live data provider did not respond, so no forecast was produced. ' + msg);
    else showError('Prediction failed', msg);
  }
}

function render(d) {
  const P = d.predictions, pk = d.peak_uv, q = d.prediction_quality;
  const labels = P.map(p => istTime(p.time_ist));
  const win = d.high_risk_windows.length
    ? d.high_risk_windows.map(w => `<span>${istTime(w.start_ist)} – ${istTime(w.end_ist)}</span>`).join('')
    : '<em class="mut">No hour is forecast at High (6+) or above.</em>';
  const winUpper = d.possible_high_risk_windows_upper_bound.length && !d.high_risk_windows.length
    ? `<p class="s">Upper end of the range reaches High: ${d.possible_high_risk_windows_upper_bound.map(w => `${istTime(w.start_ist)}–${istTime(w.end_ist)}`).join(', ')}</p>` : '';
  const ev = q.evidence || {};
  const evLine = q.tier === 'high' ? ev.test_mae_seen_locations : ev.test_mae_unseen_holdout_locations;
  const peakIdx = P.findIndex(p => p.time_utc === pk.time_utc);

  $('#out').innerHTML = `
  <div class="pred-head"><div><span class="eyebrow">Forecast issued ${esc(istDay(d.issue_time_ist))}, ${esc(istTime(d.issue_time_ist))} IST</span>
    <h2>Next 24 hours${loadCoords()?.name ? ` · ${esc(loadCoords().name)}` : ''}</h2><p class="mut">${num(d.location.latitude,4)}° N, ${num(d.location.longitude,4)}° E · times shown in IST (UTC+5:30)</p></div></div>
  <div class="pred-kpis">
    <div class="card kpi peak" style="--c:${RISK_COLOR[pk.risk] || '#999'}"><div class="l">Peak UV</div><div class="v">${num(pk.value,1)}</div>
      <div class="s">${badge(pk.risk)} at ${esc(istTime(pk.time_ist))} · range ${num(pk.lower,1)}–${num(pk.upper,1)}</div>${uvScale(pk.value)}</div>
    <div class="card kpi"><div class="l">High-risk window (UV 6+)</div><div class="window-list">${win}</div>${winUpper}</div>
    <div class="card kpi"><div class="l">Surface ozone (max)</div><div class="v">${num(d.summary.max_ozone,0)}<small>µg/m³</small></div>
      <div class="s">min ${num(d.summary.min_ozone,0)} µg/m³ over the next 24 h</div></div>
    <div class="card kpi quality-${esc(q.tier)}"><div class="l">Prediction quality</div><div class="v" style="text-transform:capitalize">${esc(q.tier)}</div>
      <div class="s">${num(q.distance_to_nearest_training_point_km,0)} km from nearest training point${evLine ? ` · measured MAE: UV ${num(evLine.uv,2)}, O₃ ${num(evLine.ozone,1)} µg/m³` : ''}</div></div>
  </div>

  <div class="card" style="margin-top:18px"><h3>UV index forecast</h3><p>Line = model forecast; shaded band = 90% empirical range (split-conformal).</p><div class="chartbox"><canvas id="uvch"></canvas></div></div>
  <div class="card" style="margin-top:18px"><h3>Ground-level ozone forecast</h3><p>Surface ozone concentration (µg/m³) — not the total-column ozone (DU) shown on the Location page.</p><div class="chartbox"><canvas id="ozch"></canvas></div></div>

  <div class="grid two" style="margin-top:18px">
    <div class="card"><h3>Hourly forecast</h3><div class="tw"><table class="ptable"><thead><tr><th>Time (IST)</th><th class="num">UV</th><th>Risk</th><th class="num">O₃ µg/m³</th><th class="num hide-sm">O₃ anomaly (z)</th><th class="num hide-sm">Cloud %</th><th class="num hide-sm">Temp °C</th></tr></thead><tbody>
      ${P.map((p, i) => `<tr class="${i === peakIdx ? 'peak-row' : ''}"><td>${esc(istTime(p.time_ist))}</td>
        <td class="num">${num(p.uv.value,1)}<div class="range">${num(p.uv.lower,1)}–${num(p.uv.upper,1)}</div></td><td>${badge(p.uv.risk)}</td>
        <td class="num">${num(p.ozone.value,0)}<div class="range">${num(p.ozone.lower,0)}–${num(p.ozone.upper,0)}</div></td>
        <td class="num hide-sm">${p.ozone.anomaly ? num(p.ozone.anomaly.standardized,2) : '—'}</td>
        <td class="num hide-sm">${num(p.weather.cloud_cover_pct,0)}</td><td class="num hide-sm">${num(p.weather.temperature_c,1)}</td></tr>`).join('')}
    </tbody></table></div></div>
    <div class="card"><h3>How to read this</h3>
      <div class="facts">
        <div><span>Ozone target</span><b>${esc(d.targets.ozone.quantity)} (${esc(d.targets.ozone.unit)})</b></div>
        <div><span>UV target</span><b>${esc(d.targets.uv.quantity)}</b></div>
        <div><span>Ranges</span><b>~90% of past outcomes fell inside</b></div>
        <div><span>Ozone anomaly</span><b>${esc(d.data_status.anomaly)}</b></div>
        <div><span>Models</span><b>O₃: ${esc(d.model.ozone_algorithm)} · UV: ${esc(d.model.uv_algorithm)} · v${esc(d.model.version)}</b></div>
        <div><span>UV uses predicted ozone</span><b>${d.model.uv_uses_predicted_ozone ? 'yes' : 'no (did not improve validation error)'}</b></div>
      </div>
      <p style="margin-top:10px">${esc(d.uncertainty.meaning)}</p>
      <p style="margin-top:8px">${esc(q.explanation)}</p>
      <h3 style="margin-top:16px">General sun guidance</h3>
      <ul class="tip-list"><li>When UV is 3 or higher, consider shade, a hat, sunglasses and sunscreen.</li><li>When UV is 6 or higher, limit long periods in direct midday sun.</li><li>This is general environmental information, not medical advice.</li></ul>
    </div>
  </div>

  <div class="card data-source-card" style="margin-top:18px"><span class="eyebrow">Data sources &amp; status</span>
    <div class="source-list">${d.data_status.sources.map(s => `<div><strong>${esc(s.name)}</strong><span>${esc(s.purpose)}</span><em>${esc(s.status)}</em></div>`).join('')}</div>
    ${d.data_status.notes.length ? `<div class="note" style="margin-top:12px">${d.data_status.notes.map(esc).join('<br>')}</div>` : ''}
    <p style="margin-top:10px;font-size:.82rem">Contains modified Copernicus Atmosphere Monitoring Service information (via Open-Meteo, CC BY 4.0). Generated ${esc(new Date(d.generated_at).toLocaleString('en-IN', {timeZone:'Asia/Kolkata'}))} IST.</p>
  </div>`;

  const band = (key, lo, hi, color) => [
    ds('Upper range', P.map(p => p[key][hi]), color, {borderWidth: 0, pointRadius: 0, fill: false}),
    ds('90% range', P.map(p => p[key][lo]), color, {borderWidth: 0, pointRadius: 0, fill: '-1', backgroundColor: color + '30'}),
  ];
  const noUpper = {o: {plugins: {legend: {labels: {filter: it => it.text !== 'Upper range'}}}}};
  chart('uvch', 'line', labels, [...band('uv', 'lower', 'upper', '#e48a2c'),
    ds('Forecast UV index', P.map(p => p.uv.value), '#b8620b', {fill: false, pointRadius: P.map((_, i) => i === peakIdx ? 6 : 2)})], 'UV index', {x: 'Time (IST)', ...noUpper});
  chart('ozch', 'line', labels, [...band('ozone', 'lower', 'upper', '#5b6fd6'),
    ds('Forecast surface O₃', P.map(p => p.ozone.value), '#2e43b8', {fill: false})], 'µg/m³', {x: 'Time (IST)', ...noUpper});
  if (window.lucide) lucide.createIcons();
}

function useGps() {
  if (!navigator.geolocation) return showError('GPS unavailable', 'Geolocation is not supported by this browser.');
  navigator.geolocation.getCurrentPosition(
    ({coords}) => { pmap.setView([coords.latitude, coords.longitude], 8); forecast(coords.latitude, coords.longitude); },
    err => showError('Location not available', err.code === 1 ? 'Permission denied. Click the map instead.' : 'Your location could not be determined.'),
    {enableHighAccuracy: true, timeout: 10000, maximumAge: 300000});
}

document.addEventListener('DOMContentLoaded', () => {
  const start = loadCoords() || {lat: 17.385, lon: 78.4867};
  pmap = L.map('map', {minZoom: 4, maxZoom: 14, maxBounds: P_BOUNDS.pad(0.08), maxBoundsViscosity: 0.85}).setView([22.5, 79], 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {attribution: '© OpenStreetMap contributors'}).addTo(pmap);
  pmarker = L.marker([start.lat, start.lon]).addTo(pmap);
  pmap.on('click', e => forecast(e.latlng.lat, e.latlng.lng));
  $('#gps').addEventListener('click', useGps);
  $('#run').addEventListener('click', () => forecast($('#latitude').value, $('#longitude').value));
  $('#latitude').value = start.lat; $('#longitude').value = start.lon;
  qp = quickPick($('#preset'), (lat, lon) => { pmap.setView([lat, lon], 8); forecast(lat, lon); });
  qp.sync(start.lat, start.lon);
  try { const m = localStorage.getItem('og-model'); if (m !== null) $('#model').value = m; } catch (e) {}
  $('#model').addEventListener('change', () => {
    try { localStorage.setItem('og-model', $('#model').value); } catch (e) {}
    forecast($('#latitude').value, $('#longitude').value);
  });
  API.getModels().then(info => {
    for (const opt of $('#model').options) {
      const m = info.models[opt.value];
      if (opt.value === '') opt.textContent = `Server default (${info.default === 'lstm' ? 'LSTM' : 'XGBoost'})`;
      else if (m && !m.available) { opt.disabled = true; opt.textContent += ' (not trained)'; }
    }
  }).catch(() => {});
  if (loadCoords()) forecast(start.lat, start.lon);
});
