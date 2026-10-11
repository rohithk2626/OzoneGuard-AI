<div align="center">

# 🌿 OzoneGuard AI

### A clearer view of ozone, UV and the atmosphere around you.

Explore environmental conditions across India with local context, historical trends and 24-hour forecasts—all in one place.

[![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Coverage](https://img.shields.io/badge/region-India-138808)](#)
[![Forecast](https://img.shields.io/badge/forecast-24%20hours-2563EB)](#)

[Explore the app](#quick-start) · [API reference](#api-at-a-glance) · [Scientific limitations](docs/scientific-limitations.md)

</div>

---

> **About the data.** Ozone and UV information comes from atmospheric models and satellite products, not a network of ground sensors. Forecasts and historical analysis are informative, not official alerts or medical advice. See [scientific limitations](docs/scientific-limitations.md) before interpreting results.

## Contents

- [Why OzoneGuard AI](#1--why-ozoneguard-ai)
- [Explore the platform](#2--explore-the-platform)
- [How the forecast works](#3--how-the-forecast-works)
- [Architecture and technology](#4--architecture-and-technology)
- [Quick start](#5--quick-start)
- [Accounts and saved places](#6--accounts-and-saved-places)
- [API at a glance](#7--api-at-a-glance)
- [Tests](#8--tests)
- [Data and model workflows](#9--data-and-model-workflows)
- [Project documentation](#10--project-documentation)
- [Sources and attribution](#11--sources-and-attribution)

## 1 · Why OzoneGuard AI

Ozone, sunlight, clouds and local weather all contribute to the UV conditions people experience. OzoneGuard AI brings these signals together for locations across India, making it easier to explore what is happening now, how conditions have changed and what the next day may look like.

The platform follows three views:

| View | What you can explore |
|------|----------------------|
| **PAST** | Daily ozone, UV and weather history, hourly averages and relationships between variables |
| **NOW** | Local weather, UV, place information and—when available—NASA satellite total-column ozone |
| **FUTURE** | 24-hour surface-ozone and UV forecasts, uncertainty ranges and UV-risk context |

## 2 · Explore the platform

| Page | What it does |
|------|--------------|
| [Location](frontend/locations.html) | Choose a point on the map or use your location to explore local conditions. Locations outside India are not accepted. |
| [Predictions](frontend/predictions.html) | View the next 24 hours of surface ozone and UV forecasts, uncertainty ranges, peak UV and higher-risk periods. |
| [Analytics](frontend/analytics.html) | Explore daily ozone, UV and weather history, average conditions by hour and measured correlations. |
| [Dashboard](frontend/dashboard.html) | Bring current, forecast and recent conditions together for a selected place. |
| [About](frontend/about.html) | Learn about the platform and its environmental context. |

### What the numbers mean

- **Surface ozone** is reported in µg/m³; **total-column ozone** from NASA is reported in Dobson Units (DU). They describe different parts of the atmosphere and should not be confused.
- UV risk categories follow the [WHO UV Index guidance](https://www.who.int/news-room/questions-and-answers/item/radiation-the-ultraviolet-(uv)-index).
- Historical and forecast values are model-derived. They are not direct measurements at the selected point.
- If a required provider or model is unavailable, the API reports an error rather than making up a value.

## 3 · How the forecast works

The project trains separate multi-horizon machine-learning models for surface ozone and UV. The models use atmospheric, weather and solar-position features and are evaluated against simple baselines and other candidate algorithms. The [model results](docs/ml-results.md) describe the evaluation and measured errors.

For a live forecast, the API fetches current input data for the selected location, builds the model features and returns hourly predictions with uncertainty ranges. The response also includes prediction-quality context, such as distance to a training location.

Training data combines CAMS atmospheric information with archived weather forecasts and calculated solar position. A location must fall within the India boundary used by the backend; locations in the sea or neighbouring countries are rejected.

More detail: [prediction pipeline](docs/prediction-pipeline.md) · [data sources](docs/prediction-data-sources.md) · [data provenance](docs/data-provenance.md) · [limitations](docs/scientific-limitations.md).

## 4 · Architecture and technology

| Layer | Technology | Role |
|-------|------------|------|
| Web interface | HTML, CSS and JavaScript | Location, forecast, analytics, dashboard and account pages |
| API | Python, FastAPI and Pydantic | Versioned endpoints, validation, provider access and static website hosting |
| Forecasting | pandas, NumPy, scikit-learn, XGBoost and LightGBM | Feature preparation, model training and inference |
| Data | CAMS / Open-Meteo, NASA Earthdata | Atmospheric, weather and optional satellite information |
| Accounts | Firebase Authentication | Optional sign-in and synced saved locations |
| Deployment | Docker and Docker Compose | Containerized API and website |

The backend serves the frontend and API from the same process. Pre-trained model artifacts are included in `models/`, so running the app does not require training them again.

## 5 · Quick start

### Requirements

- Python 3.10 or later
- Git (if cloning the repository)
- Optional: Docker Desktop for containerized setup

### Run locally

From the project root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

Open **http://127.0.0.1:8000** to use the website. The interactive API documentation is at **http://127.0.0.1:8000/docs**.

### Run with Docker

Copy `.env.example` to `.env`, then from the project root:

```bash
docker compose -f deployment/docker-compose.yml up --build
```

The website and API are available at **http://127.0.0.1:8000**.

## 6 · Accounts and saved places

The core site, forecasts and analytics can be used without configuring accounts. Login, signup and Firebase-synced saved places require your own Firebase project:

1. Follow the [Firebase setup guide](docs/firebase-setup.md).
2. Add your Firebase web-app configuration to `frontend/js/firebase-config.js`.

Without Firebase setup, saved places remain in the browser. Do not commit private credentials or tokens; `.env` is excluded from Git.

## 7 · API at a glance

All application endpoints are under `/api/v1`. See the [full API documentation](docs/api-documentation.md) or open `/docs` while the app is running.

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `GET` | `/api/v1/health` | Check API health |
| `GET` | `/api/v1/location/validate?lat=&lon=` | Check whether a coordinate is within India |
| `GET` | `/api/v1/location/presets` | List preset model locations |
| `GET` | `/api/v1/location/overview?lat=&lon=` | Get local weather, UV and place information |
| `GET` | `/api/v1/ozone/current?lat=&lon=` | Get NASA total-column ozone when available |
| `GET` | `/api/v1/predictions/24h?lat=&lon=` | Get the 24-hour surface-ozone and UV forecast |
| `GET` | `/api/v1/predictions/model-info` | Read model metadata and headline metrics |
| `GET` | `/api/v1/analytics/history?lat=&lon=&start=&end=` | Get historical ozone, UV and weather data |
| `GET` | `/api/v1/analytics/limits` | Get the supported history date range |

Example forecast for Hyderabad:

```bash
curl "http://127.0.0.1:8000/api/v1/predictions/24h?lat=17.385&lon=78.4867"
```

## 8 · Tests

Install the project dependencies, then run the test suite from the project root:

```bash
pytest -q
```

## 9 · Data and model workflows

The following commands are for rebuilding the analysis and models; they are **not** required to run the website:

```bash
python -m ml.collect_data fetch
python -m ml.preprocess
python -m ml.features
python -m ml.correlation
python -m ml.train
python -m ml.report
```

Data collection can take time and depends on upstream provider availability. See the [ML guide](ml/README.md) and [prediction pipeline](docs/prediction-pipeline.md) for prerequisites, inputs and outputs.

To compare CAMS output with ground-station observations, provide station CSV files or configure an OpenAQ API key:

```bash
python -m ml.validate_ground_truth csv data/external/stations/*.csv
python -m ml.validate_ground_truth openaq --start 2026-01-01 --end 2026-03-31
```

## 10 · Project documentation

| Document | What it covers |
|----------|----------------|
| [API documentation](docs/api-documentation.md) | Routes, inputs, responses and error behavior |
| [Architecture](docs/architecture.md) | Application structure and components |
| [Architecture decisions](docs/architecture-decisions.md) | Key design choices |
| [Prediction pipeline](docs/prediction-pipeline.md) | Data alignment, features and live inference |
| [Data sources](docs/prediction-data-sources.md) | Investigated and selected datasets |
| [Data provenance](docs/data-provenance.md) | Origins of the data used by the system |
| [Data quality](docs/data-quality-report.md) | Quality checks and results |
| [Leakage audit](docs/data-leakage-audit.md) | Feature and evaluation leakage review |
| [ML results](docs/ml-results.md) | Model comparison, evaluation and uncertainty |
| [Scientific limitations](docs/scientific-limitations.md) | Intended use and interpretation caveats |
| [Firebase setup](docs/firebase-setup.md) | Optional accounts and saved-place configuration |

## 11 · Sources and attribution

Atmospheric data includes modified information from the [Copernicus Atmosphere Monitoring Service (CAMS)](https://atmosphere.copernicus.eu/). Weather data is provided by [Open-Meteo](https://open-meteo.com/) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Optional total-column ozone is obtained from NASA's OMTO3G satellite product when Earthdata access is configured.

OzoneGuard AI is an educational and informational project. It is not an official air-quality or UV-warning service and is not a substitute for professional medical advice.
