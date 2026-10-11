"""WHO/WMO/UNEP/ICNIRP Global Solar UV Index exposure categories.

Source: WHO (2002) "Global Solar UV Index: A Practical Guide", ISBN 9241590076.
The UV Index is reported as a whole number, so categories are assigned to the
value rounded to the nearest integer: 0-2 Low, 3-5 Moderate, 6-7 High,
8-10 Very High, 11+ Extreme.
"""
from __future__ import annotations

import numpy as np

RISK_LABELS = ["Low", "Moderate", "High", "Very High", "Extreme"]
_UPPER = [2, 5, 7, 10]  # inclusive upper bound of each band on the rounded index


def uv_risk_index(uv) -> np.ndarray:
    r = np.floor(np.asarray(uv, dtype=float) + 0.5)  # round half up (np.round is banker's rounding)
    return np.searchsorted(_UPPER, r, side="left").clip(0, 4)


def uv_risk_label(uv: float | None) -> str:
    if uv is None or not np.isfinite(uv):
        return "Unavailable"
    return RISK_LABELS[int(uv_risk_index([uv])[0])]
