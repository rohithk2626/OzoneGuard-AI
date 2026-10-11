"""Central configuration for the OzoneGuard AI prediction pipeline.

Every timestamp in the pipeline is UTC. Conversion to IST happens only in the
frontend / API presentation layer.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
RAW_OPENMETEO = RAW / "openmeteo"
INTERMEDIATE = DATA / "intermediate"
PROCESSED = DATA / "processed"
SAMPLES = DATA / "samples"
MODELS = ROOT / "models"
REPORTS = ROOT / "docs" / "figures"

DATASET_VERSION = "og-cams-ifs-2022.08-2026.10-v1"
MODEL_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# Sampling locations: 38 points across all six Indian regions.
# role == "train" -> used for train/validation/test (temporal split)
# role == "spatial_holdout" -> NEVER used in training; evaluates generalisation
# to unseen coordinates (the website accepts arbitrary map clicks).
# ---------------------------------------------------------------------------
LOCATIONS = [
    # id, name, region, lat, lon, role
    ("delhi", "Delhi", "North", 28.61, 77.21, "train"),
    ("chandigarh", "Chandigarh", "North", 30.73, 76.78, "train"),
    ("lucknow", "Lucknow", "North", 26.85, 80.95, "train"),
    ("srinagar", "Srinagar", "North", 34.08, 74.80, "train"),
    ("dehradun", "Dehradun", "North", 30.32, 78.03, "train"),
    ("leh", "Leh", "North", 34.15, 77.58, "train"),
    ("amritsar", "Amritsar", "North", 31.63, 74.87, "spatial_holdout"),
    ("jaipur", "Jaipur", "West", 26.91, 75.79, "train"),
    ("ahmedabad", "Ahmedabad", "West", 23.02, 72.57, "train"),
    ("mumbai", "Mumbai", "West", 19.08, 72.88, "train"),
    ("pune", "Pune", "West", 18.52, 73.86, "train"),
    ("bhuj", "Bhuj", "West", 23.25, 69.67, "train"),
    ("jodhpur", "Jodhpur", "West", 26.24, 73.02, "spatial_holdout"),
    ("panaji", "Panaji", "West", 15.50, 73.83, "spatial_holdout"),
    ("bhopal", "Bhopal", "Central", 23.26, 77.41, "train"),
    ("nagpur", "Nagpur", "Central", 21.15, 79.09, "train"),
    ("raipur", "Raipur", "Central", 21.25, 81.63, "train"),
    ("jabalpur", "Jabalpur", "Central", 23.18, 79.99, "train"),
    ("indore", "Indore", "Central", 22.72, 75.86, "spatial_holdout"),
    ("kolkata", "Kolkata", "East", 22.57, 88.36, "train"),
    ("patna", "Patna", "East", 25.59, 85.14, "train"),
    ("bhubaneswar", "Bhubaneswar", "East", 20.30, 85.82, "train"),
    ("varanasi", "Varanasi", "East", 25.32, 82.97, "train"),
    ("ranchi", "Ranchi", "East", 23.34, 85.31, "spatial_holdout"),
    ("guwahati", "Guwahati", "Northeast", 26.14, 91.74, "train"),
    ("shillong", "Shillong", "Northeast", 25.58, 91.89, "train"),
    ("agartala", "Agartala", "Northeast", 23.83, 91.29, "train"),
    ("itanagar", "Itanagar", "Northeast", 27.08, 93.61, "train"),
    ("imphal", "Imphal", "Northeast", 24.82, 93.94, "spatial_holdout"),
    ("hyderabad", "Hyderabad", "South", 17.39, 78.49, "train"),
    ("chennai", "Chennai", "South", 13.08, 80.27, "train"),
    ("bengaluru", "Bengaluru", "South", 12.97, 77.59, "train"),
    ("thiruvananthapuram", "Thiruvananthapuram", "South", 8.52, 76.94, "train"),
    ("kochi", "Kochi", "South", 9.93, 76.27, "train"),
    ("visakhapatnam", "Visakhapatnam", "South", 17.69, 83.22, "train"),
    ("mangaluru", "Mangaluru", "South", 12.91, 74.86, "train"),
    ("madurai", "Madurai", "South", 9.93, 78.12, "spatial_holdout"),
    ("kurnool", "Kurnool", "South", 15.83, 78.04, "spatial_holdout"),
]

# Historical period. CAMS global via Open-Meteo starts 2022-08-04 for India.
START_DATE = "2022-08-04"
END_DATE = "2026-10-05"

# Chronological split on the forecast ISSUE time. Training rows whose TARGET
# time crosses into validation are purged (see features.split_frame).
TRAIN_END = "2024-09-30T23:00:00Z"
VAL_END = "2025-09-30T23:00:00Z"
# test = everything after VAL_END

HORIZONS = list(range(1, 25))
# Issue times used to build training rows (UTC hours). Every 6 h keeps the
# dataset CPU-sized; all 4 are native CAMS output times.
ISSUE_HOURS_UTC = (0, 6, 12, 18)

# Open-Meteo variables ------------------------------------------------------
CAMS_VARS = ["ozone", "uv_index", "uv_index_clear_sky", "nitrogen_dioxide", "aerosol_optical_depth"]
WX_VARS = [
    "temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure",
    "cloud_cover", "precipitation", "shortwave_radiation", "wind_speed_10m",
    "wind_direction_10m", "uv_index", "uv_index_clear_sky",
]

# Physical plausibility limits used by QC (value outside -> set NaN + flag)
PHYSICAL_LIMITS = {
    "cams_ozone": (0.0, 600.0),            # µg/m³ surface ozone
    "cams_uv_index": (0.0, 25.0),
    "cams_uv_index_clear_sky": (0.0, 25.0),
    "cams_nitrogen_dioxide": (0.0, 1000.0),
    "cams_aerosol_optical_depth": (0.0, 10.0),
    "wx_temperature_2m": (-60.0, 60.0),
    "wx_relative_humidity_2m": (0.0, 100.0),
    "wx_dew_point_2m": (-80.0, 40.0),
    "wx_surface_pressure": (400.0, 1100.0),  # hPa (Leh ~ 560 hPa)
    "wx_cloud_cover": (0.0, 100.0),
    "wx_precipitation": (0.0, 500.0),
    "wx_shortwave_radiation": (0.0, 1500.0),
    "wx_wind_speed_10m": (0.0, 300.0),     # km/h
    "wx_wind_direction_10m": (0.0, 360.0),
    "wx_uv_index": (0.0, 25.0),
    "wx_uv_index_clear_sky": (0.0, 25.0),
}

TARGETS = {
    "ozone": "cams_ozone",       # surface (ground-level) ozone, µg/m³
    "uv": "cams_uv_index",       # all-sky UV index (dimensionless)
}

RANDOM_STATE = 42
