"""SYNTHETIC frames for testing pipeline MECHANICS only.

These values are deterministic arithmetic patterns, not environmental data,
and are never used for training or reported as results.
"""
import numpy as np
import pandas as pd

from ml import config


def synthetic_frame(hours=24 * 6, start="2024-03-01T00:00:00Z"):
    t = pd.date_range(start, periods=hours, freq="h", tz="UTC")
    i = np.arange(hours, dtype=float)
    df = pd.DataFrame({"time_utc": t})
    for k, v in enumerate(config.CAMS_VARS):
        df[f"cams_{v}"] = i + 1000 * (k + 1)       # value encodes its own index
    for k, v in enumerate(config.WX_VARS):
        df[f"wx_{v}"] = i + 100000 * (k + 1)
    df["wx_wind_direction_10m"] = 90.0
    return df
