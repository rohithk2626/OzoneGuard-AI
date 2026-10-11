import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500,http://127.0.0.1:8000,http://localhost:8000,null")
    return [item.strip() for item in raw.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    app_version: str = os.getenv("APP_VERSION", "0.2.0")
    cors_origins: list[str] = None  # type: ignore[assignment]
    nasa_earthdata_token: str = os.getenv("NASA_EARTHDATA_TOKEN", "").strip()
    nasa_cmr_url: str = os.getenv("NASA_CMR_URL", "https://cmr.earthdata.nasa.gov/search/granules.umm_json")
    nasa_short_name: str = os.getenv("NASA_SHORT_NAME", "OMTO3G")
    nasa_version: str = os.getenv("NASA_VERSION", "004")
    nasa_cache_dir: str = os.getenv("NASA_CACHE_DIR", "data/raw/nasa")
    nasa_cache_max_age_hours: int = int(os.getenv("NASA_CACHE_MAX_AGE_HOURS", "30"))

    def __post_init__(self):
        object.__setattr__(self, "cors_origins", _origins())


settings = Settings()
