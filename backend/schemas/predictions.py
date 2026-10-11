"""Pydantic response schema for GET /api/v1/predictions/24h."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel


class Interval(BaseModel):
    value: Optional[float]
    lower: Optional[float]
    upper: Optional[float]


class OzoneHour(Interval):
    anomaly: Optional[dict[str, Optional[float]]] = None


class UVHour(Interval):
    risk: str
    risk_level: int


class HourlyPrediction(BaseModel):
    lead_hours: int
    time_utc: str
    time_ist: str
    ozone: OzoneHour
    uv: UVHour
    solar_elevation_deg: Optional[float]
    weather: dict[str, Optional[float]]


class PeakUV(BaseModel):
    value: Optional[float]
    lower: Optional[float]
    upper: Optional[float]
    time_utc: str
    time_ist: str
    risk: str


class Window(BaseModel):
    start_utc: str
    end_utc: str
    start_ist: str
    end_ist: str
    hours: int


class PredictionResponse(BaseModel):
    location: dict[str, Any]
    generated_at: str
    issue_time_utc: str
    issue_time_ist: str
    horizon_hours: int
    predictions: list[HourlyPrediction]
    peak_uv: PeakUV
    high_risk_windows: list[Window]
    possible_high_risk_windows_upper_bound: list[Window]
    summary: dict[str, Any]
    targets: dict[str, Any]
    uncertainty: dict[str, Any]
    prediction_quality: dict[str, Any]
    model: dict[str, Any]
    data_status: dict[str, Any]
    reference_cams_raw_forecast: list[dict[str, Any]]
