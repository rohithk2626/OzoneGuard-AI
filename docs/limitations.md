# Limitations

* Prediction system: see `scientific-limitations.md` (full list).
* India validation uses the official Survey of India outline (DataMeet `india-composite`, CC0), simplified and widened by about 20 km so coastal and border towns stay valid. A point just outside the coast or border can therefore still be accepted.
* Analytics and the Dashboard show real data fetched on demand from Open-Meteo. A one-year range takes a few seconds; ranges are limited to 366 days and start no earlier than 4 August 2022.
* Accounts and saved locations need a Firebase project (`firebase-setup.md`). They were tested against a stand-in for Firebase and the real SDK offline, and in November 2026 against a real Firebase project (sign-up, sign-in and saving a place).
* The ground-truth check was run on 7 CPCB stations for 2025 (November 2026): CAMS ozone averages 3.7 times the station readings (bias +64 µg/m³), so forecast ozone values are on the CAMS scale. See `ground-truth-validation.md`. The OpenAQ downloader is still untested against the live service.
* NASA total-column ozone on the Location page requires an Earthdata token (`blockers.md`).
