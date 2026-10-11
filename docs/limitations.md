# Limitations

* Prediction system: see `scientific-limitations.md` (full list).
* India validation uses the official Survey of India outline (DataMeet `india-composite`, CC0), simplified and widened by about 20 km so coastal and border towns stay valid. A point just outside the coast or border can therefore still be accepted.
* Analytics and the Dashboard show real data fetched on demand from Open-Meteo. A one-year range takes a few seconds; ranges are limited to 366 days and start no earlier than 4 August 2022.
* Accounts and saved locations need a Firebase project (`firebase-setup.md`). They were tested against a stand-in for Firebase and the real SDK offline, not against a real Firebase project.
* The ground-truth check (`ml/validate_ground_truth.py`) exists but has not been run on real station data; its OpenAQ downloader is untested against the live service.
* NASA total-column ozone on the Location page requires an Earthdata token (`blockers.md`).
