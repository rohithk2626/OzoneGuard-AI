from typing import Any
from pydantic import BaseModel, Field


class Coordinates(BaseModel):
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)


class LocationValidation(BaseModel):
    valid: bool
    latitude: float
    longitude: float
    message: str


class LocationOverview(BaseModel):
    location: dict[str, Any]
    weather: dict[str, Any]
    ozone: dict[str, Any]
    risk: dict[str, Any]
    data_sources: list[dict[str, str]]
    generated_at: str
