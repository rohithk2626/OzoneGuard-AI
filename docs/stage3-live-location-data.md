# Stage 3 — Live Location Data

The Location page now sends the exact selected latitude/longitude to FastAPI.

## Live providers

- **Open-Meteo:** current weather and UV Index for the selected coordinate.
- **OpenStreetMap Nominatim:** reverse geocoding to show a human-readable place.
- **NASA OMI/Aura OMTO3G:** selected as the satellite total-column ozone source.

## NASA ozone status

NASA GES DISC data access requires Earthdata authentication. The application intentionally does **not** substitute a mock ozone value when authenticated NASA data is unavailable. The API returns `requires_earthdata_auth` so the UI can show the limitation transparently.

The next ozone integration step is to add an Earthdata-authenticated retrieval/subsetting adapter for the OMTO3G product and extract the grid cell(s) covering the selected coordinate.

## Location contract

`GET /api/v1/location/overview?lat={latitude}&lon={longitude}` returns:

- selected coordinates
- reverse-geocoded place
- current weather
- current UV Index
- UV risk classification
- NASA ozone source/status
- data-source status
- retrieval timestamp
