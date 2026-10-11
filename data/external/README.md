# External data

NASA OMI/Aura OMTO3G is accessed through NASA Earthdata. The backend uses the `earthaccess` library to resolve cloud-hosted CMR granules to authenticated HTTPS distribution links when running on a local machine outside AWS us-west-2.

Keep `NASA_EARTHDATA_TOKEN` in the local `.env` file only. Never commit the token.
