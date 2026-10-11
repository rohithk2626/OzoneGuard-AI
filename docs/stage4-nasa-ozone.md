# Stage 4 — NASA OMI/Aura ozone

OzoneGuard AI uses NASA OMI/Aura OMTO3G V004 total-column ozone. OMTO3G is a daily Level-2G global gridded product at 0.25° × 0.25°.

## Authentication

NASA GES DISC data access requires Earthdata Login. Generate a user bearer token and put it in `.env` as `NASA_EARTHDATA_TOKEN`. Never put the token in frontend JavaScript or commit `.env`.

## Runtime flow

1. FastAPI receives the selected latitude/longitude.
2. The NASA service queries CMR for the newest OMTO3G V004 granule.
3. The data file is downloaded with the Earthdata bearer token and cached under `data/raw/nasa/`.
4. HDF-EOS5 is read with h5py.
5. `ColumnAmountO3` is screened for valid values and the nearest valid observation to the selected coordinate is returned.

The selected coordinate is never silently replaced by a city. The response reports the source grid/pixel and approximate coordinate distance.
