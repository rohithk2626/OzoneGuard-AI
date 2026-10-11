# Blockers (genuine human actions only)

Nothing here stops the prediction system from working. Each item would *improve* it. Never paste secrets into chat — put them in `.env` only.

---

## 1. NASA Earthdata (total-column ozone: OMTO3G / TROPOMI on GES DISC)

* **WHY REQUIRED:** NOW page satellite ozone (already coded), and a possible daily total-column-ozone feature for the UV model.
* **WHAT WAS ATTEMPTED:** CMR discovery works without login; data download needs a token. No token available in the build environment.
* **EXACT BLOCKER:** Earthdata Login account + user token.
* **ALTERNATIVES:** ERA5 `tco3` (CDS account), MERRA-2 TO3 (same Earthdata login), TROPOMI via Copernicus Data Space (free account).
* **WHAT I MUST DO:** create an account and a token.
* **EXACT STEPS:** 1) https://urs.earthdata.nasa.gov → Register. 2) Profile → *Generate Token*. 3) Applications → Authorized Apps → approve "NASA GESDISC DATA ARCHIVE". 4) In the project folder copy `.env.example` to `.env` and set `NASA_EARTHDATA_TOKEN=<token>`.
* **COMMAND TO RUN AFTERWARD:** `uvicorn backend.main:app --reload` then open `http://127.0.0.1:8000/api/v1/ozone/current?lat=17.385&lon=78.487` — `status` should be `live`.

## 2. OpenAQ API key (ground-station surface ozone, e.g. CPCB)

* **WHY REQUIRED:** to validate CAMS surface ozone against real station measurements (the strongest scientific upgrade for the ozone model).
* **WHAT WAS ATTEMPTED:** OpenAQ v3 requires an `X-API-Key` header on every request; data.gov.in says no API exists for the CPCB hourly resource.
* **EXACT BLOCKER:** free OpenAQ account + key.
* **ALTERNATIVES:** manual CSV download from the CPCB CCR portal (airquality.cpcb.gov.in/ccr).
* **WHAT I MUST DO / STEPS:** 1) https://explore.openaq.org → sign up. 2) Account settings → API key. 3) add `OPENAQ_API_KEY=<key>` to `.env`.
* **COMMAND TO RUN AFTERWARD:** `python -m ml.validate_ground_truth openaq --start 2026-01-01 --end 2026-03-31` (or, with CSVs downloaded from CPCB: `python -m ml.validate_ground_truth csv data/external/stations/*.csv`). Writes `docs/ground-truth-validation.md`. The OpenAQ downloader has not been run against the live service yet.

## 3. Copernicus Atmosphere Data Store (ADS) key

* **WHY REQUIRED:** archived CAMS 24-h-lead forecasts would let us test whether OzoneGuard beats CAMS' own forecast; EAC4 would extend history back to 2003.
* **EXACT BLOCKER:** ECMWF account, ADS API key, per-dataset licence acceptance (must be clicked by a human).
* **STEPS:** 1) https://ads.atmosphere.copernicus.eu → register. 2) accept the CAMS licence on the dataset page. 3) put the key in `~/.cdsapirc` (not in chat).
* **COMMAND TO RUN AFTERWARD:** not yet implemented (future work).

## 4. Network access for the collector (build-environment only)

* The build sandbox could not reach Open-Meteo, so dataset v1 was fetched from a browser with the identical requests (see data-provenance.md). On a normal machine, `python -m ml.collect_data fetch` works without any key.

## 5. Firebase project (accounts and saved locations)

* **WHY REQUIRED:** login, signup and per-user saved locations.
* **WHAT WAS ATTEMPTED:** the pages and `frontend/js/account.js` are complete and were tested against a stand-in for Firebase and against the real SDK offline. A real project needs a Google account.
* **EXACT BLOCKER:** a Firebase project with Email/Password sign-in and Firestore enabled, and its four web config values.
* **WHAT I MUST DO / STEPS:** follow `docs/firebase-setup.md` (about 10 minutes): create the project, paste the config into `frontend/js/firebase-config.js`, enable Email/Password, create Firestore, publish `firebase/firestore.rules`.
* **CHECK AFTERWARD:** open `signup.html`, create an account, save a location, and confirm it appears under *Firestore Database → Data*.
