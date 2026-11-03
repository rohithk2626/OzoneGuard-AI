# Stage 4 — NASA OMI/Aura ozone

OzoneGuard AI uses NASA OMI/Aura OMTO3G V004 total-column ozone. OMTO3G is a daily Level-2G global gridded product at 0.25° × 0.25°.

## Authentication

NASA GES DISC data access requires Earthdata Login. Generate a user bearer token and put it in `.env` as `NASA_EARTHDATA_TOKEN`. Never put the token in frontend JavaScript or commit `.env`.

## Runtime flow

1. FastAPI receives the selected latitude/longitude.
2. The NASA service queries CMR for the newest OMTO3G V004 granule.
3. The data file is downloaded with the Earthdata bearer token and cached under `data/raw/nasa/`.
4. HDF-EOS5 is read with h5py.
5. `ColumnAmountO3` is screened and the nearest valid observation to the selected coordinate is returned. An observation is valid only if:
   - its `QualityFlags` quality code (lowest 4 bits) is 0 (good) or 1 (good, sun-glint corrected). Code 7 means the sample was skipped and its value is meaningless (on 1 Nov 2026 such a sample put 88 DU over Hyderabad, where the real value was about 260 DU);
   - its `XTrackQualityFlags` is 0, i.e. the detector row is not affected by the OMI row anomaly;
   - the value is between 50 and 700 DU.
6. If the newest daily pass has no valid observation within 1.5° (about 165 km), the cached passes from up to 3 days earlier are tried, and the result is labelled with that pass's date (`from_earlier_pass: true`). The satellite covers India in strips, so on a given day roughly 1 in 9 places falls in a gap; with this fallback, all 38 reference places had a value on every day tested (27 Oct to 1 Nov 2026).
7. Only the newest 4 daily files (about 150 MB each) are kept in `data/raw/nasa/`; older ones, and downloads interrupted more than a day ago, are deleted automatically.

The selected coordinate is never silently replaced by a city. The response reports the source grid/pixel, the approximate coordinate distance and the date of the pass used.
