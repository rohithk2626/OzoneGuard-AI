"""NASA OMTO3G (total-column ozone) service tests.

No NASA login is available in tests, so the file-reading logic runs on a small synthetic
file laid out like the real product (several candidate scenes per 0.25-degree cell, fill
values in empty slots, attributes stored as 1-element arrays). Network calls are replaced.
"""
import os
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import h5py
import numpy as np
import pytest

from backend.services import nasa_service

FILL = np.float32(-1.2676506e30)
RECENT = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT00:00:00.000Z")


def _expected(lat):
    return 240 + 1.5 * (lat - 8)          # the synthetic ozone field rises smoothly with latitude


def _build(path, hole=None):
    rng = np.random.default_rng(1)
    lats, lons = np.arange(0, 40, 0.25) + 0.125, np.arange(60, 100, 0.25) + 0.125
    shape = (3, len(lats), len(lons))
    lat = np.broadcast_to(lats[None, :, None], shape).astype(np.float32) + rng.uniform(-0.1, 0.1, shape).astype(np.float32)
    lon = np.broadcast_to(lons[None, None, :], shape).astype(np.float32) + rng.uniform(-0.1, 0.1, shape).astype(np.float32)
    o3 = _expected(lat).astype(np.float32)
    empty = rng.random(shape) < 0.45
    if hole:                               # a data gap (swath edge / row anomaly): (lat0, lat1, lon0, lon1)
        empty |= (lat > hole[0]) & (lat < hole[1]) & (lon > hole[2]) & (lon < hole[3])
    for a in (lat, lon, o3):
        a[empty] = FILL
    with h5py.File(path, "w") as h:
        g = h.create_group("HDFEOS/GRIDS/OMI Column Amount O3/Data Fields")
        for name, arr in (("ColumnAmountO3", o3), ("Latitude", lat), ("Longitude", lon)):
            d = g.create_dataset(name, data=arr)
            d.attrs["_FillValue"] = np.array([FILL], dtype=np.float32)
        g.create_dataset("QualityFlags", data=np.zeros(shape, dtype=np.uint16))
    return path


@pytest.fixture()
def with_token(monkeypatch, tmp_path):
    monkeypatch.setattr(nasa_service, "settings",
                        replace(nasa_service.settings, nasa_earthdata_token="test-token", nasa_cache_dir=str(tmp_path / "cache")))
    nasa_service._granule_cache.update(at=0.0, value=None)
    nasa_service._points_cache.clear()
    monkeypatch.setattr(nasa_service, "_discover_latest_granule", lambda: {
        "id": "g1", "time_start": RECENT, "url": "https://example.test/OMI-Aura_L2G-OMTO3G_2026m1006.he5", "granule": "g1"})
    return tmp_path


def test_ozone_requires_token(monkeypatch):
    monkeypatch.setattr(
        nasa_service,
        "settings",
        replace(nasa_service.settings, nasa_earthdata_token=""),
    )
    result = nasa_service.get_current_ozone(17.385, 78.487)
    assert result["status"] == "requires_earthdata_auth"
    assert result["value"] is None


@pytest.mark.parametrize("lat,lon", [(17.385, 78.4867), (28.61, 77.21), (8.52, 76.94), (34.15, 77.58)])
def test_nearest_observation_from_product_layout(tmp_path, lat, lon):
    nasa_service._points_cache.clear()
    value, distance, cell = nasa_service._nearest_ozone(_build(tmp_path / "g.he5"), lat, lon)
    assert distance < 0.3                                   # an observation in or next to the cell
    assert value == pytest.approx(_expected(lat), abs=1.0)  # and the fill values were ignored
    assert 150 < value < 500


def test_live_path_end_to_end(with_token, monkeypatch):
    src = _build(with_token / "src.he5")
    calls = []

    def fake_download(granule, path):
        calls.append(path)
        shutil.copy(src, path)
    monkeypatch.setattr(nasa_service, "_download_granule", fake_download)
    a = nasa_service.get_current_ozone(17.385, 78.4867)
    assert a["status"] == "live" and a["unit"] == "DU"
    assert a["value"] == pytest.approx(_expected(17.385), abs=1.0)
    assert a["observation_time"] == RECENT and a["observation_age_days"] == 2 and a["distance_degrees"] < 0.3
    b = nasa_service.get_current_ozone(28.61, 77.21)          # second place: same cached file, no new download
    assert b["status"] == "live" and len(calls) == 1


def test_far_away_observation_is_not_shown(with_token, monkeypatch):
    src = _build(with_token / "src.he5", hole=(12, 23, 73, 84))      # no data for ~5 degrees around Hyderabad
    monkeypatch.setattr(nasa_service, "_download_granule", lambda granule, path: shutil.copy(src, path))
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "unavailable" and r["value"] is None and "No value is shown" in r["message"]


def test_login_page_is_not_cached_as_data(with_token, monkeypatch):
    class Resp:
        status_code = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield b"<html><body>Earthdata Login</body></html>"
    monkeypatch.setattr(nasa_service.requests, "get", lambda *a, **k: Resp())
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "unavailable" and r["value"] is None and "token" in r["message"].lower()
    cache = with_token / "cache"
    assert not any(cache.glob("*.he5")) and not any(cache.glob("*.part"))


def test_rejected_token_message(with_token, monkeypatch):
    class Resp:
        status_code = 401
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(nasa_service.requests, "get", lambda *a, **k: Resp())
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "unavailable" and "HTTP 401" in r["message"]


class _Granule(dict):
    def data_links(self, access=None):
        return [f"https://example.test/{self['umm']['GranuleUR']}.he5"]


def _granule(day):
    return _Granule(umm={"GranuleUR": f"OMTO3G_{day}", "TemporalExtent": {"RangeDateTime": {"BeginningDateTime": f"{day}T00:00:00.000Z"}}}, meta={"native-id": day})


def test_search_asks_for_the_newest_granule(monkeypatch):
    """CMR lists granules oldest-first (from 2004); the service must not pick one of those."""
    calls = []

    def fake_search(**kw):
        calls.append(kw)
        if kw.get("sort_key") == "-start_date":
            return [_granule("2026-10-06"), _granule("2026-10-05")]
        return [_granule("2004-10-01"), _granule("2004-10-20")]
    monkeypatch.setattr(nasa_service.earthaccess, "search_data", fake_search)
    g = nasa_service._discover_latest_granule()
    assert calls[0]["sort_key"] == "-start_date" and g["time_start"].startswith("2026-10-06")


def test_search_falls_back_to_recent_time_windows(monkeypatch):
    calls = []

    def fake_search(**kw):
        calls.append(kw)
        if "sort_key" in kw:
            raise ValueError("Unknown key sort_key")             # an older earthaccess
        return [_granule("2026-10-04"), _granule("2026-10-06"), _granule("2026-10-05")] if "temporal" in kw else [_granule("2004-10-01")]
    monkeypatch.setattr(nasa_service.earthaccess, "search_data", fake_search)
    g = nasa_service._discover_latest_granule()
    assert "temporal" in calls[1] and g["time_start"].startswith("2026-10-06")


def test_old_file_is_labelled_stale(with_token, monkeypatch):
    src = _build(with_token / "src.he5")
    monkeypatch.setattr(nasa_service, "_discover_latest_granule", lambda: {
        "id": "old", "time_start": "2004-10-20T00:00:00.000Z", "url": "https://example.test/old.he5", "granule": "old"})
    monkeypatch.setattr(nasa_service, "_download_granule", lambda granule, path: shutil.copy(src, path))
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "stale" and r["observation_age_days"] > 8000 and "not a current reading" in r["message"]


def _poison_nearest(path, lat, lon, quality=None, xtrack=None):
    """Give the observation closest to (lat, lon) a fake 88 DU value and the given flags."""
    with h5py.File(path, "r+") as h:
        g = h["HDFEOS/GRIDS/OMI Column Amount O3/Data Fields"]
        la, lo = g["Latitude"][...], g["Longitude"][...]
        ok = la > -1e29                                            # skip fill values in empty slots
        d = np.full(la.shape, np.inf)
        d[ok] = (la[ok].astype(np.float64) - lat) ** 2 + (lo[ok].astype(np.float64) - lon) ** 2
        idx = np.unravel_index(np.argmin(d), d.shape)
        o3 = g["ColumnAmountO3"][...]; o3[idx] = 88.0; g["ColumnAmountO3"][...] = o3
        if quality is not None:
            q = g["QualityFlags"][...]; q[idx] = quality; g["QualityFlags"][...] = q
        if xtrack is not None:
            x = np.zeros(la.shape, dtype=np.uint8); x[idx] = xtrack
            g.create_dataset("XTrackQualityFlags", data=x)
    return path


@pytest.mark.parametrize("quality,xtrack", [(7, None), (65535, None), (3, None), (0, 113)])
def test_flagged_observations_are_ignored(tmp_path, quality, xtrack):
    """A skipped (code 7), missing (fill), poor (code 3) or row-anomaly reading must never be shown,
    even when it is the closest one: on 1 Nov 2026 such a reading put 88 DU over Hyderabad."""
    nasa_service._points_cache.clear()
    path = _poison_nearest(_build(tmp_path / "g.he5"), 17.385, 78.4867, quality, xtrack)
    value, distance, _ = nasa_service._nearest_ozone(path, 17.385, 78.4867)
    assert value == pytest.approx(_expected(17.385), abs=2.0)    # the next good reading, not 88 DU
    assert distance < 0.5


def test_good_quality_codes_are_kept(tmp_path):
    nasa_service._points_cache.clear()
    path = _poison_nearest(_build(tmp_path / "g.he5"), 17.385, 78.4867, quality=1)   # 1 = glint-corrected, still good
    value, _, _ = nasa_service._nearest_ozone(path, 17.385, 78.4867)
    assert value == pytest.approx(88.0)


# ------------------------------------------------------------------ earlier-pass fallback and cache clean-up
def _day_name(days_ago):
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return f"OMI-Aura_L2G-OMTO3G_{d:%Y}m{d:%m%d}_v004-test.he5"


def _newest_is(monkeypatch, days_ago):
    d = datetime.now(timezone.utc) - timedelta(days=days_ago)
    monkeypatch.setattr(nasa_service, "_discover_latest_granule", lambda: {
        "id": "new", "time_start": f"{d:%Y-%m-%d}T00:00:00.000Z",
        "url": f"https://example.test/{_day_name(days_ago)}", "granule": "new"})


def test_point_missed_today_uses_previous_pass(with_token, monkeypatch):
    """The satellite covers India in strips; when the newest pass misses a point, an earlier pass
    (here a day earlier) is used and labelled with its own date."""
    cache = with_token / "cache"; cache.mkdir()
    _build(cache / _day_name(3))                                           # yesterday's file: full coverage
    gap = _build(with_token / "gap.he5", hole=(12, 23, 73, 84))            # today's file: misses Hyderabad
    _newest_is(monkeypatch, 2)
    monkeypatch.setattr(nasa_service, "_download_granule", lambda granule, path: shutil.copy(gap, path))
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "live" and r["from_earlier_pass"] is True
    assert r["value"] == pytest.approx(_expected(17.385), abs=1.0)
    assert r["observation_age_days"] == 3 and "did not cover this point" in r["message"]
    d = nasa_service.get_current_ozone(28.61, 77.21)                       # Delhi is in today's strip
    assert d["from_earlier_pass"] is False and d["observation_age_days"] == 2


def test_fallback_never_uses_old_files(with_token, monkeypatch):
    cache = with_token / "cache"; cache.mkdir()
    _build(cache / _day_name(2 + nasa_service.FALLBACK_DAYS + 1))          # too old for the fallback
    _build(cache / "OMI-Aura_L2G-OMTO3G_2004m1020_v004-2024m1016t194413.he5")
    gap = _build(with_token / "gap.he5", hole=(12, 23, 73, 84))
    _newest_is(monkeypatch, 2)
    monkeypatch.setattr(nasa_service, "_download_granule", lambda granule, path: shutil.copy(gap, path))
    r = nasa_service.get_current_ozone(17.385, 78.4867)
    assert r["status"] == "unavailable" and r["value"] is None


def test_old_daily_files_are_deleted(with_token, monkeypatch):
    cache = with_token / "cache"; cache.mkdir()
    src = _build(with_token / "src.he5")
    for days in (3, 4, 5, 6, 7):
        shutil.copy(src, cache / _day_name(days))
    shutil.copy(src, cache / "OMI-Aura_L2G-OMTO3G_2004m1020_v004-2024m1016t194413.he5")   # 2004 leftover
    (cache / "notes.txt").write_text("not a NASA file")                                      # never touched
    (cache / "half.he5.part").write_text("interrupted download")
    os.utime(cache / "half.he5.part", (0, 0))                                                # older than a day
    _newest_is(monkeypatch, 2)
    monkeypatch.setattr(nasa_service, "_download_granule", lambda granule, path: shutil.copy(src, path))
    assert nasa_service.get_current_ozone(17.385, 78.4867)["status"] == "live"
    left = sorted(p.name for p in cache.iterdir())
    kept = [_day_name(2 + i) for i in range(nasa_service.KEEP_DAILY_FILES)]       # newest + fallback days
    assert left == sorted(kept + ["notes.txt"])
