"""Deterministic solar geometry (NOAA Solar Calculator equations).

Solar position is computed from (lat, lon, UTC time) only, so it is exactly
known for any future hour and can never leak observations.
Accuracy of the NOAA approximation is ~0.01° in elevation for 1950-2050,
far finer than anything the models can resolve.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _julian_day(ts: pd.DatetimeIndex | pd.Series) -> np.ndarray:
    t = pd.to_datetime(ts, utc=True)
    if isinstance(t, pd.Series):
        t = pd.DatetimeIndex(t)
    return t.to_julian_date().to_numpy(dtype=float)


def solar_position(times_utc, lat, lon) -> dict[str, np.ndarray]:
    """Return solar elevation/zenith (degrees) and declination.

    ``times_utc`` must be timezone-aware UTC (or naive values meaning UTC).
    ``lat``/``lon`` can be scalars or arrays broadcastable to times.
    """
    jd = _julian_day(times_utc)
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    jc = (jd - 2451545.0) / 36525.0

    geom_mean_long = np.mod(280.46646 + jc * (36000.76983 + jc * 0.0003032), 360)
    geom_mean_anom = 357.52911 + jc * (35999.05029 - 0.0001537 * jc)
    ecc = 0.016708634 - jc * (0.000042037 + 0.0000001267 * jc)
    m = np.radians(geom_mean_anom)
    eq_ctr = (np.sin(m) * (1.914602 - jc * (0.004817 + 0.000014 * jc))
              + np.sin(2 * m) * (0.019993 - 0.000101 * jc) + np.sin(3 * m) * 0.000289)
    true_long = geom_mean_long + eq_ctr
    omega = 125.04 - 1934.136 * jc
    app_long = true_long - 0.00569 - 0.00478 * np.sin(np.radians(omega))
    mean_obliq = 23 + (26 + ((21.448 - jc * (46.815 + jc * (0.00059 - jc * 0.001813)))) / 60) / 60
    obliq_corr = mean_obliq + 0.00256 * np.cos(np.radians(omega))
    decl = np.degrees(np.arcsin(np.sin(np.radians(obliq_corr)) * np.sin(np.radians(app_long))))

    var_y = np.tan(np.radians(obliq_corr / 2)) ** 2
    l0 = np.radians(geom_mean_long)
    eq_time = 4 * np.degrees(
        var_y * np.sin(2 * l0) - 2 * ecc * np.sin(m) + 4 * ecc * var_y * np.sin(m) * np.cos(2 * l0)
        - 0.5 * var_y ** 2 * np.sin(4 * l0) - 1.25 * ecc ** 2 * np.sin(2 * m)
    )  # minutes

    frac_day = np.mod(jd + 0.5, 1.0)  # fraction of UTC day
    true_solar_time = np.mod(frac_day * 1440 + eq_time + 4 * lon, 1440)
    hour_angle = np.where(true_solar_time / 4 < 0, true_solar_time / 4 + 180, true_solar_time / 4 - 180)

    lat_r = np.radians(lat)
    decl_r = np.radians(decl)
    cos_zen = np.sin(lat_r) * np.sin(decl_r) + np.cos(lat_r) * np.cos(decl_r) * np.cos(np.radians(hour_angle))
    cos_zen = np.clip(cos_zen, -1, 1)
    zenith = np.degrees(np.arccos(cos_zen))
    elevation = 90 - zenith

    # Earth-sun distance correction factor (affects irradiance by ~±3.4 %)
    rad_vector = (1.000001018 * (1 - ecc ** 2)) / (1 + ecc * np.cos(np.radians(geom_mean_anom + eq_ctr)))

    # Daylight duration (hours) from sunrise hour angle (refraction-corrected 90.833°)
    cos_ha0 = (np.cos(np.radians(90.833)) / (np.cos(lat_r) * np.cos(decl_r)) - np.tan(lat_r) * np.tan(decl_r))
    ha0 = np.degrees(np.arccos(np.clip(cos_ha0, -1, 1)))
    daylight_hours = 8 * ha0 / 60

    return {
        "solar_elevation": elevation,
        "solar_zenith": zenith,
        "cos_zenith": np.maximum(cos_zen, 0.0),
        "declination": decl,
        "earth_sun_distance_au": rad_vector,
        "daylight_hours": daylight_hours,
        "true_solar_time_min": true_solar_time,
    }
