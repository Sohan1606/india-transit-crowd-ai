# India Transit Crowd AI

**PREDICT THE CROWD. PLAN THE JOURNEY.**

An India-focused, multimodal transit discovery and passenger-demand forecasting project built by migrating the existing React + TypeScript + Vite, FastAPI and machine-learning implementation. The product catalogues Indian city/mode/operator references, but **real passenger-demand prediction is enabled only for verified Bengaluru Namma Metro / BMRCL station-hour boardings** in this release.

> A station boarding is an entry count for a historical hour. It is not the number of passengers currently onboard a train, a capacity/occupancy measure, a safety rating, or a live-service observation.

## Product scope

| Capability | This release |
|---|---|
| Prediction family | Bengaluru · Metro · BMRCL (`bengaluru-namma-metro`) only |
| Verified prediction data | Hourly station-wise observed boardings from the pinned BMRCL/Namma Metro source |
| Source window | 2025-08-01 to 2025-09-30 in two discontinuous periods; source snapshot, not live |
| Network discovery | India system catalog includes selected official/community GTFS and network references |
| Unsupported systems | Explicitly show that verified demand data/model artifacts are unavailable; schedules never become passenger-count targets |
| Other modes/cities | No bus, other-metro, nationwide, live-position, occupancy or capacity predictions are enabled |

The source includes **92,280 observed station-hour records across 83 stations**, including **18,200 source-reported zeros**. No missing observations were filled. August 19–31 is absent in the source; station coverage also changes during August. See [`docs/dataset.md`](docs/dataset.md) and [`data/licenses/BMRCL-ATTRIBUTION.md`](data/licenses/BMRCL-ATTRIBUTION.md).

## What the product does

- Discovers India transit systems by city, mode and operator, with network-source provenance and an explicit prediction-availability state.
- Forecasts next-hour station boardings from a saved BMRCL regression model using only earlier, contiguous observed station history. Recursive projection is bounded to 336 hours from the station's data frontier and is clearly labeled as a projection from a historical snapshot.
- Shows a secondary LOW / MODERATE / HIGH / SEVERE label from frozen training-only historical percentiles, plus a separately trained classifier cross-check. These are relative-demand bands, not occupancy or safety levels.
- Provides actual observed-history and weekday/hour views; absent source hours remain absent rather than being drawn as zero or forecast values.
- Shows station comparisons, model-backed feature sensitivity, lower-demand nearby modelled time windows, measured model benchmarks, and training-only PCA/DBSCAN station profiles.
- Returns specific unsupported-system, missing-model, invalid-input and insufficient-history states instead of sample predictions or fabricated station metrics.

## Architecture

```text
Pinned BMRCL archive ──> verified source adapter ──> canonical station-hour records
                                                       │
                           schedules / GTFS ──> discovery catalog only (never demand)
                                                       │
                                                       ▼
                         leakage-safe features → mode/operator model registry
                                                       │
                  separate regression + classification + frozen risk thresholds
                                                       │
                       PCA/DBSCAN + explainability + measured reports
                                                       │
 React / Vite ── relative /api proxy ──> FastAPI ──> family-scoped saved artifacts
```

- `ml/data_pipeline/` provides the adapter registry, BMRCL parser, shared normalized record validation and provenance-aware preparation.
- `ml/features/`, `ml/training/`, `ml/evaluation/` and `ml/clustering/` implement leakage-safe time features, time-ordered model selection, metrics, thresholds and station profiles.
- `backend/app/` exposes India system discovery and artifact-backed station APIs. Requests never train a model.
- `frontend/src/` preserves the premium responsive product shell and adapts its navigation, inputs, data views and unavailable states to Indian systems.
- `backend/models/bengaluru-namma-metro/` stores the only enabled family artifact, its measured report, station analytics and a replay of the saved champion on the held-out period.
- [`docs/migration.md`](docs/migration.md) records what was preserved, modified, removed and added.

Detailed component contracts are in [`docs/architecture.md`](docs/architecture.md).

## Verified data and reuse

The source adapter uses the exact archive at upstream commit `6c44579b5ff3428a88bddc44baf84e436a940612` from [Vonter/bmrcl-ridership-hourly](https://github.com/Vonter/bmrcl-ridership-hourly). The bundled raw ZIP's SHA-256 matches the pinned raw GitHub URL byte-for-byte: `a0469f3365c53ca25d9aed5396775fc1c6018cfc0b93e245e8bc3e1c9524bd81`. The normalized CSV hash is recorded in its metadata sidecar. The upstream database is marked **ODbL-1.0**; attribution, share-alike and rights-caution notices are preserved under `data/licenses/`.

Other observed-demand leads were reviewed before selecting the model architecture: Delhi's approval-based metro hourly footfall, daily MMRDA metro/monorail counts and monthly CMRL totals. Their access, granularity, licensing and forecast suitability are documented in [`docs/dataset.md`](docs/dataset.md) and surfaced by `GET /api/demand-sources`. None is enabled in the model registry. Delhi OTD, Mumbai BEST/TMT/KDMT, PMPML, Kochi and Hyderabad GTFS references support service discovery only; GTFS schedules are not observed demand.

## Reproduce the data pipeline

The source archive and normalized records are included in the project. A network connection is needed only to redownload the pinned upstream file.

```bash
# From the repository root. The downloader enforces the pinned SHA-256.
python scripts/download_data.py
python scripts/prepare_data.py
python scripts/train_models.py
python scripts/evaluate_models.py
```

- `download_data.py` fetches only the pinned BMRCL archive and rejects an unexpected revision/checksum.
- `prepare_data.py` parses the source's semicolon-delimited fields, localizes the date/hour in Asia/Kolkata, assigns stable station IDs, validates whole counts, preserves reported zeros, and does not impute absent hours.
- `train_models.py` writes to `backend/models/<system_id>/` and regenerates `docs/model_report.md`. New model families must first have their source adapter, provenance, license, time granularity and demand semantics reviewed and registered.
- `evaluate_models.py` independently replays the saved champions on the recorded test period without refitting or selecting a model.

## Model and evaluation method

The supervised target is the next consecutive observed station-hour boarding count. Features include station identity, target-hour calendar values, and 1/24/168-hour lags plus 3/24/168-hour rolling statistics from history strictly before the target. Missing source hours are not bridged into training windows.

Unique target timestamps are split chronologically: 70% train, 15% validation and 15% final test. All stations at the same target time stay in one partition. Three expanding-window `TimeSeriesSplit` folds run inside training; risk thresholds are refit on each fold's training rows. Validation selects the champions; the final test does not select them.

The actual benchmark compares a seasonal-naive baseline, Linear Regression, Decision Tree, Random Forest, linear SVR and XGBoost for regression, plus a most-frequent baseline, Logistic Regression, Decision Tree, Random Forest, Linear SVM and XGBoost for classification. The current saved artifact's regression champion is XGBoost; the classification champion is Random Forest. See [`docs/model_report.md`](docs/model_report.md) for exact metrics and partition details.

Risk boundaries are **LOW ≤ P50**, **MODERATE > P50 and ≤ P80**, **HIGH > P80 and ≤ P95**, and **SEVERE > P95**. Thresholds use training targets only and are frozen. The hierarchy prefers adequately sampled station thresholds (minimum 500 targets), then system-level thresholds (minimum 500), then the global training fallback. The values describe historical-relative demand only.

PCA/DBSCAN profiles are fitted on training-period station behaviour. Global permutation importance and per-request model sensitivity are tied to saved model outputs; both are associational, not causal. No uncalibrated confidence percentage or interval is generated. Details and limitations are in [`docs/methodology.md`](docs/methodology.md).

## Run locally

Prerequisites: Python 3.13, Node.js 20+, npm. Docker is optional.

```bash
# Repository root
python -m venv .venv
source .venv/bin/activate                 # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

# Terminal 1: API
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: frontend
cd frontend
npm ci
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`. Vite proxies relative `/api` calls to FastAPI. API documentation is at `http://localhost:8000/api/docs`.

### Production build and automated tests

```bash
# Backend and data/model tests (from repository root)
python -m pytest backend/tests -q
python -m compileall -q backend ml scripts

# Frontend (from frontend/)
npm test
npm run build
```

Seeded synthetic station counts are used **only** by backend test fixtures in temporary directories. They are not in the production dataset, model artifacts or frontend results.

## API examples

All endpoints are under `/api`:

- `GET /health`, `GET /systems`, `GET /demand-sources`
- `GET /metadata`, `GET /stations?system_id=bengaluru-namma-metro`
- `POST /predict`
- `GET /history?system_id=bengaluru-namma-metro&station_id=attiguppe&hours=168`
- `GET /heatmap?system_id=bengaluru-namma-metro&station_id=attiguppe`
- `GET /station-comparison?system_id=bengaluru-namma-metro&target_date=2025-10-01&target_hour=0&selected_station_id=attiguppe`
- `GET /station-analytics`, `GET /model-performance`

Example request using a target immediately after the source snapshot:

```json
{
  "system_id": "bengaluru-namma-metro",
  "station_id": "attiguppe",
  "target_date": "2025-10-01",
  "target_hour": 0
}
```

The result is a model output based on historical rows ending no later than 2025-09-30; it is not a 2026 observation or live-service forecast. A catalogued but unsupported system such as Delhi Metro returns **409** with the unavailable-data reason. An unavailable BMRCL artifact/data service returns **503**, not an unsupported-mode response.

## Deployment

- **Docker Compose:** `docker compose up --build` serves the frontend at `http://localhost:8080`; Nginx proxies `/api` to FastAPI. The backend image copies only the BMRCL artifact family, normalized dataset and provenance sidecar. XGBoost's CPU runtime and OpenMP library are included.
- **Render:** `render.yaml` points to the BMRCL family paths. Set `CORS_ORIGINS` to the exact frontend origin.
- **Vercel:** set the project root to `frontend`, build with `npm run build`, output `dist`, and set `VITE_API_BASE` to the deployed API URL ending in `/api`; configure the matching backend CORS origin.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — data contracts, model-family and API architecture.
- [`docs/dataset.md`](docs/dataset.md) — BMRCL provenance, ODbL and other Indian observed-demand/network source review.
- [`docs/methodology.md`](docs/methodology.md) — features, leakage controls, benchmarks, thresholds, PCA/DBSCAN and explanation design.
- [`docs/model_report.md`](docs/model_report.md) — measured performance for the bundled model artifact.
- [`docs/viva-notes.md`](docs/viva-notes.md) — presentation notes and likely questions.
- [`docs/migration.md`](docs/migration.md) — preserved/modified/removed/added migration record.
- [`FINAL_HANDOFF.md`](FINAL_HANDOFF.md) — final checks and packaging handoff.
