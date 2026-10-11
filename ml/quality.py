"""Prediction-quality indicator for arbitrary coordinates.

Evidence base: models are trained on 30 points; 8 further points were held
out entirely (ml/train.py -> metrics.json["prediction_quality_evidence"]).
The indicator is a transparent, rule-based tier, NOT a probability:

* "high"   -- within 50 km of a training point (same/adjacent CAMS 0.4° cell):
              in-sample test-period error applies.
* "medium" -- 50-350 km from the nearest training point, inside India: the
              distance range covered by the spatial-holdout evaluation, whose
              measured error is reported alongside.
* "low"    -- farther than 350 km from any training point (not covered by
              the holdout evaluation -> accuracy NOT VERIFIED).
"""
from __future__ import annotations

import math

from ml import config

TRAIN_POINTS = [(l[3], l[4]) for l in config.LOCATIONS if l[5] == "train"]
HIGH_KM, MEDIUM_KM = 50.0, 350.0


def _hav(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(a))


def distance_to_training_km(lat: float, lon: float) -> float:
    return min(_hav(lat, lon, a, b) for a, b in TRAIN_POINTS)


def quality_tier(lat: float, lon: float) -> tuple[str, float]:
    d = distance_to_training_km(lat, lon)
    if d <= HIGH_KM:
        return "high", d
    if d <= MEDIUM_KM:
        return "medium", d
    return "low", d
