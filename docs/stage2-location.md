# Stage 2 — Coordinate-Based Location Workflow

The Location page now uses the FastAPI backend for map/GPS coordinate selection.

## Flow

1. User clicks any point inside the supported India geographic bounds.
2. The frontend captures the exact latitude and longitude.
3. Coordinates are sent to `GET /api/v1/location/overview`.
4. FastAPI validates the coordinate and returns the selected location object.
5. The frontend displays the selected coordinates and backend status.

## Endpoints

- `GET /api/v1/location/validate?lat={lat}&lon={lon}`
- `GET /api/v1/location/overview?lat={lat}&lon={lon}`

## Current limitation

Stage 2 uses India's broad latitude/longitude bounds rather than a detailed land-boundary polygon. This will be replaced with a proper India boundary/geospatial check before the real environmental data services are connected.

The environmental values on Predictions, Analytics, Dashboard, and the legacy location compatibility functions remain mock data until their respective stages are implemented.
