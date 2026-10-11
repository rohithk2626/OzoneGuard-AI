# OzoneGuard AI Architecture

OzoneGuard AI has three core product functions:

1. **Location / Now** — current ozone, UV, weather and UV risk for any selected coordinate in India.
2. **Predictions / Next 24 Hours** — hourly future ozone and UV predictions, UV risk and peak UV time.
3. **Analytics / Past** — historical ozone, UV and weather trends with date filters.

The frontend sends latitude/longitude to the FastAPI backend. Data-source services retrieve observations/forecasts, the ML pipeline produces future ozone and UV predictions, and historical observations are stored for analytics.

## FUTURE (implemented)

```
lat/lon → CAMS composition up to now + NWP weather forecast + solar geometry
       → ml.features.build_rows (same code as training)
       → surface-ozone model → UV model → 90 % conformal ranges → WHO UV risk, peak UV, high-risk windows
       → GET /api/v1/predictions/24h → predictions.html
```

See `prediction-pipeline.md` and `architecture-decisions.md`.
