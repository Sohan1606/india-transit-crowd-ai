# India Transit Crowd AI — Architecture

**PREDICT THE CROWD. PLAN THE JOURNEY.**  
Last reviewed: 2026-10-06.

## Design boundary

The application is a multimodal India transit **discovery** surface, and passenger-demand prediction is enabled only for verified, gate-passed model families — one per system, one granularity each:

* `bengaluru-namma-metro` — BMRCL station-**hour** boardings (ODbL-1.0 archive, pinned by SHA-256).
* `chennai-cmrl-metro` — CMRL station-**day** entries (collector archive pinned by commit and three SHA-256 digests, not redistributed).

Systems whose data cannot support a future-labelled target are catalogued but prediction-disabled: the Mumbai suburban-rail survey extract is the clearest case (one typical weekday per survey window, licence unresolved), and its 2021/2031 forecast block is quarantined as model output. Static schedules, GTFS, API announcements and network maps are not passenger-demand observations and cannot enter a model target.

Registration is enforced by `scripts/validate_demand_dataset.py` (ten criteria, report written per system) and the feature builder's refusal to train without history strictly before the target. A dataset that cannot satisfy them yields documentation and a collector, not a model.

## Data and model path

```text
Verified source archive (pinned BMRCL / CMRL upstream revision)
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
      │  bengaluru-namma-metro (hourly) · chennai-cmrl-metro (daily)
      ├── separate regression benchmark and saved champion
      ├── separate relative-demand classification benchmark and saved champion
      ├── train-only frozen risk distributions
      └── training-window PCA + DBSCAN station analytics
      ▼
Family-scoped artifact directory
      ├── transitcrowd.joblib                # both families (bundle carries model_family + granularity)
      ├── model_report.json                  # both families
      ├── station_analytics.json             # hourly family only
      ├── evaluation_replay.json             # hourly family only (full hourly replay)
      └── future_forecast.json               # daily family: saved snapshot of a future day + recursive projection
      ▼
FastAPI inference / analytics endpoints ── same-origin Vite or Nginx proxy ── React UI

Official/community transit schedules ──> discovery catalog only (never into demand targets)
```

## Adaptive front door

```
any compatible CSV -> profile (ml/data_pipeline/profile.py)   column roles + measured period
                   -> decide (refuse on ties, ids, forecast-like columns, period conflicts)
                   -> normalize (ml/data_pipeline/cleaning.py, period-aware alignment)
                   -> gate (scripts/validate_demand_dataset.py, 10 criteria, conjunction)
                   -> register (data/registry/model_families.json, read by ml/training/registry.py)
                   -> train offline (ml/training/train_daily.py + ml/training/horizon.py)
                   -> artifacts (backend/models/<system_id>/: model, preprocessor, config, metadata,
                                 training cut-off, horizon bands, reports)
                   -> serve (backend/app/inference/{service.py,daily_service.py}: lookup only)
```

A registered family carries its own `granularity`, `period_seconds`, `target`, `measure`,
`dataset_relative_path` and `metadata_relative_path`, so the API routes a request to the right service
by family metadata (`backend/app/api/routes.py::_granularity`) rather than by a per-city branch.
`development_only: true` families are loaded by the tooling and skipped by
`backend/app/main.py::_build_services`, so a synthetic family can exist in a development checkout
without ever becoming answerable.

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
| `GET /future-preview?system_id=...&days=...` | Projection over the days/hours the source has not published yet, plus the recursive and one-step accuracy of that projection. |
| `GET /source-gap?system_id=...` | How far the archive trails today, when the next observation is expected, and what would close the gap. |
| `GET /api/systems` | Per-system `granularity`, `label_unit`, `max_horizon` and, for prediction-disabled systems, `prediction_unavailable_reason`. |

Granularity is enforced at the API edge: a day-granularity system rejects `target_hour` (422) and `heatmap` (409) rather than inventing hourly values, and an hourly system requires `target_hour`. Predictions for times at or before the data frontier are labelled `forecast_kind: "historical_replay"` / `is_model_forecast: false`; only post-frontier responses are labelled as forecasts.

## Runtime and deployment

- Local API: `uvicorn backend.app.main:app --host 0.0.0.0 --port 8000`.
- Local UI: `cd frontend && npm ci && npm run dev`; Vite proxies `/api` to port 8000.
- Docker Compose: API uses the family artifact, normalized CSV and provenance sidecar; Nginx proxies `/api` to FastAPI.
- Render configuration is in `render.yaml`; set `CORS_ORIGINS` to the exact deployed frontend origin.
- Vercel frontend: configure build-time `VITE_API_BASE` to the hosted API's `/api` base and configure backend CORS.

The runtime image needs the pinned XGBoost CPU package because the saved regression artifact contains an XGBoost estimator. The training, runtime, Docker and deployment paths all point to the same system-specific model family; there is no legacy route model fallback and no pooling of systems or granularities into one model.
