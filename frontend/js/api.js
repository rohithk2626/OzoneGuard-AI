/* Centralized API layer. Every value shown on the site comes from the FastAPI backend:
 *   NOW     /api/v1/location/overview      live weather, UV, NASA total-column ozone
 *   FUTURE  /api/v1/predictions/24h        trained ML models
 *   PAST    /api/v1/analytics/history      real CAMS + weather history
 * No numbers are generated in the browser. Accounts and saved locations are handled
 * by js/account.js (Firebase), not by the backend.
 */
/* Where the backend is:
 *  - page opened from the backend itself (http://127.0.0.1:8000, or the deployed site) -> same address ('')
 *  - page opened from a separate local file server (e.g. Live Server on port 5500)     -> http://127.0.0.1:8000
 *  - window.OZONE_API_BASE_URL, if set before this script, always wins. */
const _LOCAL_HOSTS = ['localhost', '127.0.0.1'];
const API_CONFIG = {
  BASE_URL: window.OZONE_API_BASE_URL ??
    (_LOCAL_HOSTS.includes(location.hostname) && location.port !== '8000' ? 'http://127.0.0.1:8000' : '')
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
    throw new Error('Cannot reach the OzoneGuard backend at ' + API_CONFIG.BASE_URL + '. Is it running?');
  }
  let body = null;
  try { body = await response.json(); } catch (_) {}
  if (!response.ok) {
    let detail = body?.detail || body?.message || `Request failed (${response.status})`;
    if (Array.isArray(detail)) detail = detail.map(d => d.msg || JSON.stringify(d)).join('; ');
    else if (detail && typeof detail === 'object') detail = [detail.status, detail.message].filter(Boolean).join(': ') || JSON.stringify(detail);
    throw new Error(detail);
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
  getPredictions24h(lat, lon) { return request(`/api/v1/predictions/24h?lat=${_enc(lat)}&lon=${_enc(lon)}`); },

  /* PAST: start / end are YYYY-MM-DD (Indian days). */
  getHistory(lat, lon, start, end) {
    return request(`/api/v1/analytics/history?lat=${_enc(lat)}&lon=${_enc(lon)}&start=${_enc(start)}&end=${_enc(end)}`);
  },
  getHistoryLimits() { return request('/api/v1/analytics/limits'); }
};
