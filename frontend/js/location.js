let map, marker, qp;
let selectedCoordinates = null;

const INDIA_CENTER = [22.5, 79];
const INDIA_MAX_BOUNDS = L.latLngBounds([6.0, 68.0], [37.5, 97.5]);

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function coordinateLabel(lat, lon) {
  return `${Number(lat).toFixed(5)}° ${lat >= 0 ? 'N' : 'S'}, ${Number(lon).toFixed(5)}° ${lon >= 0 ? 'E' : 'W'}`;
}

function uvRiskClass(level) {
  return String(level || 'Unavailable').toLowerCase().replaceAll(' ', '-');
}

function formatNumber(value, digits = 1) {
  return value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits);
}

function renderMetric(title, value, unit, icon) {
  return `<div class="card metric-card"><div class="card-icon"><i data-lucide="${icon}"></i></div><h3>${title}</h3><strong>${escapeHtml(value)}${unit ? ` <small>${escapeHtml(unit)}</small>` : ''}</strong></div>`;
}

function renderSelectedLocation(data) {
  const out = document.querySelector('#out');
  const { latitude: lat, longitude: lon, place } = data.location;
  const weather = data.weather || {};
  const ozone = data.ozone || {};
  const risk = data.risk || {};
  const placeName = place?.city || place?.state || 'Selected point in India';
  const uv = weather.uv_index;
  const hasUv = uv !== null && uv !== undefined;

  out.innerHTML = `
    <div class="selected-location-card">
      <div class="result-head">
        <div>
          <p class="eyebrow">Selected location</p>
          <h2>${escapeHtml(placeName)}</h2>
          <p>${escapeHtml(coordinateLabel(lat, lon))}${place?.state ? ` · ${escapeHtml(place.state)}` : ''}</p>
        </div>
        <div class="place-actions">
          <button class="btn" id="save-place" type="button"><i data-lucide="bookmark-plus"></i>Save this location</button>
          <a class="btn ghost" href="predictions.html"><i data-lucide="trending-up"></i>Next 24 hours</a>
          <a class="btn ghost" href="analytics.html"><i data-lucide="chart-line"></i>History</a>
          <span class="save-msg" id="save-msg" role="status"></span>
        </div>
      </div>

      <div class="now-grid">
        <div class="card risk-card" style="--c:${hasUv ? uvCat(uv).color : '#8a90a8'}">
          <p class="eyebrow">Current UV risk</p>
          <h2>${escapeHtml(risk.level || 'Unavailable')}</h2>
          <p>${hasUv ? `Current UV Index is ${formatNumber(uv, 1)}.` : 'UV data is currently unavailable.'}</p>
          ${hasUv ? uvScale(uv) : ''}
          ${hasUv ? `<p class="risk-tip">${escapeHtml(uvCat(uv).tip)}</p>` : ''}
        </div>
        <div class="metric-strip">
          ${renderMetric('Ozone layer (total column)', formatNumber(ozone.value, 0), ozone.unit || 'DU', 'layers')}
          ${renderMetric('UV Index', formatNumber(uv, 1), '', 'sun')}
          ${renderMetric('Temperature', formatNumber(weather.temperature, 1), weather.temperature_unit || '°C', 'thermometer')}
          ${renderMetric('Humidity', formatNumber(weather.humidity, 0), weather.humidity_unit || '%', 'droplets')}
          ${renderMetric('Cloud Cover', formatNumber(weather.cloud_cover, 0), '%', 'cloud')}
          ${renderMetric('Wind', formatNumber(weather.wind_speed, 1), 'km/h', 'wind')}
        </div>
      </div>

      <div class="grid two" style="margin-top:16px">
        <div class="card data-source-card">
          <p class="eyebrow">Data sources</p>
          <div class="source-list">
            ${(data.data_sources || []).map(source => `<div><strong>${escapeHtml(source.name)}</strong><span>${escapeHtml(source.purpose)}</span><em>${escapeHtml(source.status)}</em></div>`).join('')}
          </div>
          ${ozone.status === 'requires_earthdata_auth' ? `<div class="note" style="margin-top:14px">NASA ozone is not fabricated when satellite access is unavailable. Configure NASA Earthdata authentication on the backend to populate the ozone observation.</div>` : ''}
          ${ozone.status === 'unavailable' ? `<div class="note" style="margin-top:14px"><strong>Satellite ozone unavailable.</strong> ${escapeHtml(ozone.message || '')}</div>` : ''}
          ${ozone.value !== null && ozone.value !== undefined && ozone.observation_time ? `<p style="margin-top:12px;font-size:.875rem">Ozone layer value: NASA OMI satellite pass of ${escapeHtml(new Date(ozone.observation_time).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }))}, nearest observation about ${formatNumber((ozone.distance_degrees || 0) * 111, 0)} km away.${ozone.status === 'stale' ? ` <strong>${escapeHtml(ozone.message || '')}</strong>` : ''}</p>` : ''}
        </div>
        <div class="card">
          <p class="eyebrow">Observation</p>
          <h3>${escapeHtml(weather.time || '—')}</h3>
          <div class="facts">
            <div><span>Timezone</span><b>${escapeHtml(weather.timezone || '—')}</b></div>
            <div><span>Data retrieved</span><b>${escapeHtml(new Date(data.generated_at).toLocaleString())}</b></div>
          </div>
        </div>
      </div>
    </div>`;

  document.querySelector('#save-place').addEventListener('click', () => savePlace(placeName === 'Selected point in India' ? null : placeName, lat, lon));
  if (window.lucide) lucide.createIcons();
}

/* Saved locations: Firestore when signed in, this browser otherwise (js/account.js). */
async function savePlace(name, lat, lon) {
  const note = document.querySelector('#save-msg'), button = document.querySelector('#save-place');
  button.disabled = true; note.className = 'save-msg'; note.textContent = 'Saving…';
  try {
    const saved = await OGAccount.locations.add({ name, lat, lon });
    const where = OGAccount.locations.mode() === 'cloud' ? 'your account' : 'this device (sign in to keep it on every device)';
    note.textContent = saved.already ? `Already saved as "${saved.name}".` : `Saved to ${where}.`;
    note.classList.add('ok');
  } catch (error) {
    note.textContent = OGAccount.message(error); note.classList.add('err');
  }
  button.disabled = false;
}

function renderLocationError(message) {
  document.querySelector('#out').innerHTML = `<div class="note location-error" role="alert"><strong>Location not available.</strong><br>${escapeHtml(message)}</div>`;
}

async function selectCoordinates(lat, lon, source = 'map') {
  const latitude = Number(lat), longitude = Number(lon);
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return renderLocationError('Invalid coordinates were received.');

  selectedCoordinates = { latitude, longitude, source };
  document.querySelector('#latitude').value = latitude.toFixed(5); document.querySelector('#longitude').value = longitude.toFixed(5);
  if (qp) qp.sync(latitude, longitude);
  marker.setLatLng([latitude, longitude]).bindPopup(`<b>Selected point</b><br>${escapeHtml(coordinateLabel(latitude, longitude))}`).openPopup();
  document.querySelector('#out').innerHTML = '<div class="card state">Loading live weather and UV conditions…</div>';

  try {
    const data = await API.getLocationOverview(latitude, longitude);
    renderSelectedLocation(data);
    const place = data.location?.place || {};
    setPlace(latitude, longitude, place.city || place.district || place.state || null);
  } catch (error) {
    renderLocationError(error.message || 'The backend could not process this location.');
  }
}

function useGps() {
  if (!navigator.geolocation) return renderLocationError('Geolocation is not supported by this browser.');
  document.querySelector('#out').innerHTML = '<div class="card state">Getting your current coordinates…</div>';
  navigator.geolocation.getCurrentPosition(
    ({ coords }) => {
      const { latitude, longitude } = coords;
      if (!INDIA_MAX_BOUNDS.contains([latitude, longitude])) return renderLocationError('Your current location is outside the supported India map area.');
      map.setView([latitude, longitude], 10); selectCoordinates(latitude, longitude, 'gps');
    },
    error => renderLocationError(error.code === 1 ? 'Location permission was denied. Select a point manually on the map.' : 'Your current location could not be determined.'),
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 300000 }
  );
}

document.addEventListener('DOMContentLoaded', () => {
  map = L.map('map', { minZoom: 4, maxZoom: 16, maxBounds: INDIA_MAX_BOUNDS.pad(0.08), maxBoundsViscosity: 0.85 }).setView(INDIA_CENTER, 5);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '© OpenStreetMap contributors' }).addTo(map);
  marker = L.marker(INDIA_CENTER).addTo(map).bindPopup('<b>OzoneGuard AI</b><br>Select any point inside India.').openPopup();
  map.on('click', event => selectCoordinates(event.latlng.lat, event.latlng.lng, 'map'));
  document.querySelector('#gps').addEventListener('click', useGps);
  qp = quickPick(document.querySelector('#preset'), (lat, lon) => { map.setView([lat, lon], 10); selectCoordinates(lat, lon, 'preset'); });
  document.querySelector('#clear-location').addEventListener('click', () => {
    selectedCoordinates = null; if (qp) qp.sync(null); marker.setLatLng(INDIA_CENTER).bindPopup('<b>OzoneGuard AI</b><br>Select any point inside India.').openPopup();
    map.setView(INDIA_CENTER, 5); document.querySelector('#out').innerHTML = '<div class="card state">Select any point on the India map to begin.</div>';
  });
  document.querySelector('#coordinate-form').addEventListener('submit', event => {
    event.preventDefault(); const lat = Number(document.querySelector('#latitude').value), lon = Number(document.querySelector('#longitude').value);
    if (!INDIA_MAX_BOUNDS.contains([lat, lon])) return renderLocationError('Those coordinates are outside the supported India geographic area.');
    map.setView([lat, lon], 10); selectCoordinates(lat, lon, 'coordinates');
  });
  document.querySelector('#out').innerHTML = '<div class="card state">Select any point on the India map to begin.</div>';
  if (window.lucide) lucide.createIcons();

  /* Opened from a saved location on the dashboard: show that place straight away. */
  let handed = false;
  try { handed = sessionStorage.getItem('og_open_place') === '1'; sessionStorage.removeItem('og_open_place'); } catch (_) {}
  const last = getPlace();
  if (handed && last && INDIA_MAX_BOUNDS.contains([last.lat, last.lon])) {
    document.querySelector('#latitude').value = last.lat; document.querySelector('#longitude').value = last.lon;
    map.setView([last.lat, last.lon], 9); selectCoordinates(last.lat, last.lon, 'saved');
  }
});
