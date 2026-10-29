/* Centralized API layer. Every value shown on the site comes from the FastAPI backend:
 *   NOW     /api/v1/location/overview      live weather, UV, NASA total-column ozone
 *   FUTURE  /api/v1/predictions/24h        trained ML models
 *   PAST    /api/v1/analytics/history      real CAMS + weather history
 * No numbers are generated in the browser. Accounts and saved locations are handled
 * by js/account.js (Firebase), not by the backend.
 */
/* Where the backend is:
 *  - page served by the backend itself, on any port (http://localhost:8000, :8080, the deployed site) -> same address ('')
 *  - page opened as a file, or from VS Code Live Server (port 5500/5501)                              -> http://127.0.0.1:8000
 *  - window.OZONE_API_BASE_URL, if set before this script, always wins. */
const _STATIC_DEV_PORTS = ['5500', '5501'];
const API_CONFIG = {
  BASE_URL: window.OZONE_API_BASE_URL ??
    (location.protocol === 'file:' || _STATIC_DEV_PORTS.includes(location.port) ? 'http://127.0.0.1:8000' : '')
};

const DATA_NOTE = 'Live weather, CAMS ozone/UV history and trained forecasts for any point in India. Educational project, not medical advice.';

async function request(path, opts = {}) {
  let response;
  try {
    response = await fetch(API_CONFIG.BASE_URL + path, {
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
      ...opts
    });
  } catch (_) {
    throw new Error('Cannot reach the OzoneGuard backend at ' + (API_CONFIG.BASE_URL || location.origin) + '. Is it running?');
  }
  let body = null;
  try { body = await response.json(); } catch (_) {}
  if (!response.ok) {
    let detail = body?.detail || body?.message || `Request failed (${response.status})`, code = '';
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    else if (detail && typeof detail === 'object') { code = detail.status || ''; detail = detail.message || detail.status || JSON.stringify(detail); }
    const err = new Error(detail);
    err.code = code;   /* machine-readable reason (e.g. provider_unavailable), kept out of the visible text */
    throw err;
  }
  return body;
}

const _enc = v => encodeURIComponent(v);

const API = {
  /* NOW */
  getLocationOverview(lat, lon) { return request(`/api/v1/location/overview?lat=${_enc(lat)}&lon=${_enc(lon)}`); },
  validateLocation(lat, lon) { return request(`/api/v1/location/validate?lat=${_enc(lat)}&lon=${_enc(lon)}`); },
  /* The 38 named points the models were trained and tested on (quick picks). */
  getPresets() { return request('/api/v1/location/presets'); },

  /* FUTURE */
  getPredictions24h(lat, lon, model) { return request(`/api/v1/predictions/24h?lat=${_enc(lat)}&lon=${_enc(lon)}${model ? `&model=${_enc(model)}` : ''}`); },
  getModels() { return request('/api/v1/predictions/models'); },

  /* PAST: start / end are YYYY-MM-DD (Indian days). */
  getHistory(lat, lon, start, end) {
    return request(`/api/v1/analytics/history?lat=${_enc(lat)}&lon=${_enc(lon)}&start=${_enc(start)}&end=${_enc(end)}`);
  },
  getHistoryLimits() { return request('/api/v1/analytics/limits'); }
};
