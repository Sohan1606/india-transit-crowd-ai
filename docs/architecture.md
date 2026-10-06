# India Transit Crowd AI — Architecture

**PREDICT THE CROWD. PLAN THE JOURNEY.**  
Last reviewed: 2026-10-05.

## Design boundary

The application is a multimodal India transit **discovery** surface, but passenger-demand prediction is enabled only for one verified family in this release: Bengaluru Namma Metro / BMRCL hourly station boardings. Static schedules, GTFS, API announcements and network maps are not passenger-demand observations and cannot enter a model target.

## Data and model path

```text
Verified source archive (pinned BMRCL upstream revision)
      │  source ID + pinned URL/hash + license/attribution
      ▼
Source adapter registry (ml/data_pipeline/adapters.py, source.py)
      │  schema checks, local-time parsing, stable station IDs, no gap filling
      ▼
Canonical observed-demand records
      │  one system / city / mode / operator / entity / local timestamp / count
      ▼
Validation + leakage-safe temporal features
      │  only observations strictly before target T
      ▼
Model-family registry (system ID → mode/operator/entity/timezone/artifact path)
      │  presently: bengaluru-namma-metro only
      ├── separate regression benchmark and saved champion
      ├── separate relative-demand classification benchmark and saved champion
      ├── train-only frozen risk distributions
      └── training-window PCA + DBSCAN station analytics
      ▼
Family-scoped artifact directory
      ├── transitcrowd.joblib
      ├── model_report.json
      ├── station_analytics.json
      └── evaluation_replay.json
      ▼
FastAPI inference / analytics endpoints ── same-origin Vite or Nginx proxy ── React UI

Official/community transit schedules ──> discovery catalog only (never into demand targets)
```

## Boundaries and responsibilities

- **Source adapters (`ml/data_pipeline/`)** establish what the count means, its publisher/provenance, license, timezone, resolution, entity key and source ID. The adapter rejects unexpected columns, fractional/negative counts, duplicate station-hour keys and malformed rows rather than silently repairing them.
- **Canonical validation (`ml/data_pipeline/cleaning.py`)** enforces one consistent system family per dataset and one observed record per entity-hour. Explicit zero counts remain observed zeros; absent hours remain absent. Timezone is taken from the registered family.
- **Feature builder (`ml/features/forecasting.py`)** makes station/entity-hour lag, rolling and calendar features. Histories must be contiguous where a feature requires continuity. The target is the next consecutive observed hour; no target-hour passenger count is used as a feature.
- **Model registry (`ml/training/registry.py`)** maps `system_id` to city, mode, operator, entity type, measure, timezone, source adapter and family-specific artifact directory. A new system needs verified data and its own training/evaluation before it can be enabled. The current registry has one family only.
- **Training (`ml/training/train.py`)** benchmarks real candidate models on a global chronological split of unique target hours; the validation period selects winners. Three expanding-window `TimeSeriesSplit` folds are run inside training. The later test is measurement only. Thresholds are fitted on training targets and frozen; PCA/DBSCAN is fitted on training-period station profiles.
- **Inference (`backend/app/inference/service.py`)** loads a saved family artifact and normalized data at startup. It never trains on a request. It verifies that system IDs, station IDs and normalized-data checksum agree with the artifact metadata. Any projection after the final source observation is explicitly a historical-snapshot projection, not a live forecast.
- **API (`backend/app/api/routes.py`)** is system/station aware. Unknown systems return 404, catalogued-but-unsupported systems return 409 with a reason, missing model/data returns 503, and insufficient history/horizon/input returns a validation error. No unsupported endpoint returns fabricated station counts.
- **Frontend (`frontend/src/`)** exposes the same India city → mode → operator discovery flow for enabled and unavailable systems. Selecting an unsupported system clears stale station results and shows why prediction is unavailable. It uses relative `/api` paths through Vite or Nginx; browser code never calls a local backend address.

## Canonical record contract

The normalized station-hour CSV uses:

`system_id, city, mode, operator, entity_id, entity_name, entity_type, timestamp, demand_count, measure, source_id`

For the bundled source, `entity_type=STATION`, `measure=hourly_station_boardings`, `source_id=bmrcl-ridership-hourly`, and timestamps are timezone-aware `Asia/Kolkata`. A future bus family could use `entity_type=STOP` or another explicit observed-count entity only if its own source actually measures that entity; it cannot silently reuse station semantics.

## API surface

All application endpoints are under `/api`:

| Endpoint | Purpose |
|---|---|
| `GET /health` | Model/data readiness and loaded system ID. |
| `GET /systems` | India system catalog and per-system prediction status. |
| `GET /demand-sources` | Verified model-source IDs and observed-demand candidates under review. |
| `GET /metadata` | Active family, source provenance, coverage, license, timezone and defaults. |
| `GET /stations?system_id=...` | Stations backed by the active normalized source. |
| `POST /predict` | Model estimate, percentile band, independent classifier check, sensitivity and nearby-hour model recommendations. |
| `GET /history?system_id=...&station_id=...` | Published observations only; missing hours are omitted. |
| `GET /heatmap?system_id=...&station_id=...` | Weekday/hour means from available published observations. |
| `GET /station-comparison?...` | Same-target station model outputs with station-specific training-history context. |
| `GET /station-analytics` | Saved PCA/DBSCAN station profiles. |
| `GET /model-performance` | Saved chronological benchmark and source-specific report. |

## Runtime and deployment

- Local API: `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
- Local UI: `cd frontend && npm ci && npm run dev`; Vite proxies `/api` to port 8000.
- Docker Compose: API uses the family artifact, normalized CSV and provenance sidecar; Nginx proxies `/api` to FastAPI.
- Render configuration is in `render.yaml`; set `CORS_ORIGINS` to the exact deployed frontend origin.
- Vercel frontend: configure build-time `VITE_API_BASE` to the hosted API's `/api` base and configure backend CORS.

The runtime image needs the pinned XGBoost CPU package because the saved regression artifact contains an XGBoost estimator. The training, runtime, Docker and deployment paths all point to the same BMRCL model family; there is no legacy route model fallback.
