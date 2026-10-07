# India Transit Crowd AI

**PREDICT THE CROWD. PLAN THE JOURNEY.**

An India-focused, multimodal transit discovery and passenger-demand forecasting project built by migrating the existing React + TypeScript + Vite, FastAPI and machine-learning implementation. The product catalogues Indian city/mode/operator references, and **real passenger-demand prediction is enabled only where verified observed data supports a future-labelled target**: Bengaluru Namma Metro / BMRCL station-hour boardings (unchanged) and **Chennai Metro / CMRL station-day entries**, which is the family that forecasts a date the source has not yet published. Mumbai suburban rail carries a verified 2011-12 / 2013 survey dataset and is explicitly **not** prediction-enabled, with the failing criteria shown in the UI.

> A station boarding is an entry count for a historical hour. It is not the number of passengers currently onboard a train, a capacity/occupancy measure, a safety rating, or a live-service observation.

## Product scope

| Capability | This release |
|---|---|
| Prediction families | Bengaluru · Metro · BMRCL (`bengaluru-namma-metro`, hourly) and Chennai · Metro · CMRL (`chennai-cmrl-metro`, daily) — separate model families, separate artefact directories, never pooled |
| Verified prediction data | 92,280 observed station-hours (BMRCL) and 10,965 observed station-days (CMRL), each pinned by SHA-256 |
| Source windows | Bengaluru 2025-08-01 → 2025-09-30 in two discontinuous periods; Chennai 2026-01-24 → 2026-10-05, 255 consecutive days, one day behind today |
| Future prediction | Chennai forecasts are projected past the data frontier (up to 60 days) and scored recursively; requests at/below the frontier are labelled `historical_replay`, never "future" |
| Assessed and refused | Mumbai suburban rail (MRVC/Wilbur Smith survey extract: one weekday per survey window, licence unresolved) — dataset shipped as a historical baseline, prediction disabled with reasons |
| Network discovery | India system catalog includes selected official/community GTFS and network references |
| Unsupported systems | Explicitly show that verified demand data/model artifacts are unavailable; schedules never become passenger-count targets |
| Other modes/cities | No bus, other-metro, nationwide, live-position, occupancy or capacity predictions are enabled |

The Bengaluru source includes **92,280 observed station-hour records across 83 stations**, including **18,200 source-reported zeros**. No missing observations were filled. August 19–31 is absent in the source; station coverage also changes during August. See [`docs/dataset.md`](docs/dataset.md) and [`data/licenses/BMRCL-ATTRIBUTION.md`](data/licenses/BMRCL-ATTRIBUTION.md).

The Chennai source includes **10,965 observed station-day records across 43 station-line entities** over **255 consecutive days** with **no missing station-days**; the measure is verified as one counting event per journey (mean 1.0061 against the system-wide ticket count over all 255 days). Its history is ~8.4 months, so it carries weekly seasonality and holidays but no annual cycle. See [`docs/chennai-metro-dataset.md`](docs/chennai-metro-dataset.md).

## What the product does

- Discovers India transit systems by city, mode and operator, with network-source provenance and an explicit prediction-availability state.
- Forecasts next-hour station boardings from a saved BMRCL regression model using only earlier, contiguous observed station history. Recursive projection is bounded to 336 hours from the station's data frontier and is clearly labeled as a projection from a historical snapshot.
- Forecasts **future days** for Chennai Metro: for a date after the last observed day the response states `forecast_kind: "post_frontier_projection"`, `is_model_forecast: true`, the training cut-off and the data frontier, and is explicitly not labelled as an observation. `GET /api/future-preview?system_id=chennai-cmrl-metro&days=N` returns the network-wide projection for the next N unobserved days; `GET /api/source-gap` states how far the archive trails today and what is needed to close the gap.
- Shows a secondary LOW / MODERATE / HIGH / SEVERE label from frozen training-only historical percentiles, plus a separately trained classifier cross-check. These are relative-demand bands, not occupancy or safety levels.
- Provides actual observed-history and weekday/hour views; absent source hours remain absent rather than being drawn as zero or forecast values.
- Shows station comparisons, model-backed feature sensitivity, lower-demand nearby modelled time windows, measured model benchmarks (including a leakage-free recursive projection so "future accuracy" is not confused with "one-step accuracy"), and training-only PCA/DBSCAN station profiles.
- Refuses, rather than fakes: day-granularity systems return 409 for `heatmap`/`target_hour` instead of splitting a daily total into invented hours; systems without observed station-level demand (Mumbai suburban rail, DMRC, PMPML, Kochi, Hyderabad) return 409 with the reason and the exact criteria they would have to meet.
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

Chennai's data is **not** redistributed: the raw archive and the normalized CSV are git-ignored and rebuilt by `scripts/download_cmrl_data.py`, which pins commit `72ee5ea` and verifies three SHA-256 digests, because CMRL asserts no bulk-reuse terms and the tracker's MIT licence covers only its code ([`data/licenses/CMRL-DATA-NOTICE.md`](data/licenses/CMRL-DATA-NOTICE.md)). The Mumbai suburban-rail extract under `data/research/` is reference-only for the same reason — the 2013 PDF prints no licence — and its 2016/2021/2031 forecast block is quarantined in a separate file as `HISTORICAL STUDY MODEL OUTPUT`, never as a training label.

Other observed-demand leads were reviewed before selecting the model architecture: Delhi's approval-based metro hourly footfall and daily MMRDA metro/monorail counts (the only newer *observed* Mumbai transit series found; not retrievable from this environment, licence field not visible, line-level only). Their access, granularity, licensing and forecast suitability are documented in [`docs/dataset.md`](docs/dataset.md) and surfaced by `GET /api/demand-sources`. None is enabled in the model registry. Delhi OTD, Mumbai BEST/TMT/KDMT, PMPML, Kochi and Hyderabad GTFS references support service discovery only; GTFS schedules are not observed demand.

## Reproduce the data pipeline

The source archive and normalized records are included in the project. A network connection is needed only to redownload the pinned upstream file.

```bash
# From the repository root. The downloader enforces the pinned SHA-256.
python scripts/download_data.py
python scripts/prepare_data.py
python scripts/train_models.py
python scripts/evaluate_models.py

# Chennai family: fetch → normalize → gate → train + future snapshot
python3 scripts/download_cmrl_data.py
python3 scripts/prepare_chennai_data.py
python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro   # 10-criterion gate
python3 scripts/train_chennai_models.py --target-date 2026-10-07
python3 scripts/train_chennai_models.py --refresh-only --target-date 2026-10-07  # reuse models

# Grow a source that has no history yet (append-only; never interpolates)
python3 scripts/collect_transit_observations.py --source cmrl
```

- `download_data.py` fetches only the pinned BMRCL archive and rejects an unexpected revision/checksum.
- `prepare_data.py` parses the source's semicolon-delimited fields, localizes the date/hour in Asia/Kolkata, assigns stable station IDs, validates whole counts, preserves reported zeros, and does not impute absent hours.
- `train_models.py` writes to `backend/models/<system_id>/` and regenerates `docs/model_report.md`. New model families must first have their source adapter, provenance, license, time granularity and demand semantics reviewed and registered — and pass `scripts/validate_demand_dataset.py`, which refuses to call a dataset trainable unless observed labels, a known time ordering, quantified missingness, a real future period and leakage-free features all hold.
- `prepare_chennai_data.py` refuses to run on an unpinned archive, checks that station counts behave like entries rather than entries+exits, and records a source vocabulary for every label it normalizes so no PDF wording is lost.
- `evaluate_models.py` independently replays the saved champions on the recorded test period without refitting or selecting a model.

## Model and evaluation method

The supervised target is the next consecutive observed station-hour boarding count. Features include station identity, target-hour calendar values, and 1/24/168-hour lags plus 3/24/168-hour rolling statistics from history strictly before the target. Missing source hours are not bridged into training windows.

Unique target timestamps are split chronologically: 70% train, 15% validation and 15% final test. All stations at the same target time stay in one partition. Three expanding-window `TimeSeriesSplit` folds run inside training; risk thresholds are refit on each fold's training rows. Validation selects the champions; the final test does not select them. The same discipline applies to the daily family (Chennai: 158 / 34 / 35 days, 6,794 / 1,462 / 1,505 rows), whose target is the next calendar day with lags 1/7/14/28 and 7/28-day rolling statistics — and whose published accuracy is a **recursive** projection beyond the cut-off (MAE 902.29, R² 0.8691, sMAPE 16.2% over 69 days), not the more flattering one-step number (MAE 711.82).

The actual benchmark compares a seasonal-naive baseline, Linear Regression, Decision Tree, Random Forest, linear SVR and XGBoost for regression, plus a most-frequent baseline, Logistic Regression, Decision Tree, Random Forest, Linear SVM and XGBoost for classification. The current saved artifact's regression champion is XGBoost; the classification champion is Random Forest. See [`docs/model_report.md`](docs/model_report.md) for exact metrics and partition details.

Risk boundaries are **LOW ≤ P50**, **MODERATE > P50 and ≤ P80**, **HIGH > P80 and ≤ P95**, and **SEVERE > P95**. Thresholds use training targets only and are frozen. The hierarchy prefers adequately sampled station thresholds (minimum 500 targets), then system-level thresholds (minimum 500), then the global training fallback. The values describe historical-relative demand only.

PCA/DBSCAN profiles are fitted on training-period station behaviour. Global permutation importance and per-request model sensitivity are tied to saved model outputs; both are associational, not causal. No confidence percentage is generated; the only range the API returns is an
empirical per-horizon absolute-error band, labelled `calibrated: false` / `is_confidence_interval: false` and measured
by re-running the champion recursively on validation days ([`docs/methodology.md`](docs/methodology.md#horizon-validation-and-empirical-forecast-bands)). Details and limitations are in [`docs/methodology.md`](docs/methodology.md).

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
- `GET /future-preview?system_id=chennai-cmrl-metro&days=3`, `GET /source-gap?system_id=chennai-cmrl-metro`

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

A genuinely future request — same endpoint, the day-granularity family, a date the source has not published yet — carries that distinction in the payload (verbatim response, generated 2026-10-06 against the shipped artifact):

```json
{"system_id": "chennai-cmrl-metro", "station_id": "line-01-stl", "target_date": "2026-10-07"}
```

```json
{
  "station_name": "Thousand Lights (Blue Line)",
  "granularity": "day",
  "predicted_demand": 18808.791015625,
  "measure": "daily_station_entries",
  "risk": "SEVERE",
  "relative_demand_band": "SEVERE",
  "historical_percentile": 100.0,
  "risk_method": "system_training_fallback",
  "classification_check": "SEVERE",
  "regression_model": "xgboost",
  "forecast_horizon_days": 2,
  "is_model_forecast": true,
  "is_recursive_forecast": true,
  "forecast_kind": "post_frontier_projection",
  "origin_timestamp": "2026-10-05T00:00:00+05:30",
  "origin_basis": "data_frontier_recursive_seed",
  "actual_observed_demand": null,
  "observation_status": "OBSERVED VALUE UNAVAILABLE",
  "evaluation_status": "not_scored_future_period",
  "absolute_error": null,
  "horizon_status": "within_validated_range",
  "forecast_interval": {
    "lower": 16245.198415625,
    "upper": 21372.383615625,
    "level": "p90_of_absolute_error",
    "method": "empirical absolute-error quantile at the measured horizon, from a recursive projection over the validation partition",
    "horizon_days_used": 2,
    "band_basis": "measured_at_horizon",
    "calibrated": false,
    "is_confidence_interval": false
  },
  "data_frontier": "2026-10-05T00:00:00+05:30",
  "training_cutoff": "2026-07-28T00:00:00+05:30",
  "data_freshness_days": 1,
  "model_version": "2.1.0-india-daily",
  "forecast_note": "MODEL FORECAST. Day 2026-10-07 has not been observed by the source; 2 day(s) past the data frontier. Values beyond the frontier are produced by re-feeding the model its own one-day-ahead forecasts, so error can compound with horizon. This is not a live count, not occupancy and not a safety rating."
}
```

Asking the same family for an already-observed day (2026-06-15) returns `forecast_kind: "historical_replay"` with
`is_model_forecast: false` **and the comparison against the stored observation**: `actual_observed_demand: 17182.0`,
`absolute_error: 50.33`, `absolute_percentage_error: 0.2929`, `evaluation_status: "scored_against_observation"`, plus
`horizon_status: "not_applicable_historical"`. A period the source never published instead returns
`actual_observed_demand: null` with `observation_status: "OBSERVED VALUE UNAVAILABLE"` - the value is never estimated,
interpolated or replaced with zero. Requests past the validation-measured horizon (34 days for this family) still answer
but carry `horizon_status: "beyond_validated_range"` with the widest measured band applied.

## Registering another dataset

The pipeline is not hard-wired to these two systems. `scripts/audit_demand_dataset.py` audits any supplied CSV
first (inventory, measured grid and time slots, duplicates, and whether a precomputed `Target_*` column really
reproduces next-period demand - if it does not, it is ignored as ground truth). Then
A registered family also carries a serving mode: `production` for verified observed data, `demo` for a
dataset that admits it is synthetic (served, so the demonstration runs, with `SYNTHETIC DEMONSTRATION
DATA` / `NOT LIVE PASSENGER RIDERSHIP` on every answer and its metrics marked demonstration-only), and
**Mumbai is integrated under `demo`:** both supplied files were audited row by row, their
`Target_Next_Hour_Passengers` columns were found not to describe next-hour demand (2.7 % and 1.1-2.0 %
agreement with the chronological series) and are ignored as ground truth, and the two families are served
with a synthetic disclosure on every response. See [docs/mumbai-local-dataset.md](docs/mumbai-local-dataset.md)
and [docs/mumbai-metro-dataset.md](docs/mumbai-metro-dataset.md) for the audit-before-integration rule that
any supplied file - including the Mumbai Local and Mumbai Metro files - is subject to.

`scripts/register_demand_dataset.py` profiles any candidate CSV (column roles decided from data characteristics, observation period measured from timestamp
spacing), normalizes it to the canonical schema, runs the same ten-criterion gate and - only on a clean
pass - writes a model-family entry and trains it offline. Ambiguous targets, synthetic or modelled
columns, and a granularity that contradicts the data are refused with reasons. See
[`docs/dataset.md`](docs/dataset.md#registering-another-observed-demand-dataset-adaptive-path).

## Deployment

- **Docker Compose:** `docker compose up --build` serves the frontend at `http://localhost:8080`; Nginx proxies `/api` to FastAPI. The backend image copies only the BMRCL artifact family, normalized dataset and provenance sidecar. XGBoost's CPU runtime and OpenMP library are included.
- **Render:** `render.yaml` points to the BMRCL family paths. Set `CORS_ORIGINS` to the exact frontend origin.
- **Vercel:** set the project root to `frontend`, build with `npm run build`, output `dist`, and set `VITE_API_BASE` to the deployed API URL ending in `/api`; configure the matching backend CORS origin.

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — data contracts, model-family and API architecture.
- [`docs/dataset.md`](docs/dataset.md) — BMRCL and CMRL provenance, licences, gate results and the wider Indian observed-demand/network source review.
- [`docs/chennai-metro-dataset.md`](docs/chennai-metro-dataset.md) — the future-prediction family: source contract, measure-semantics evidence, gate results, model metrics, limitations.
- [`docs/mumbai-wilbur-smith-dataset.md`](docs/mumbai-wilbur-smith-dataset.md) — what the MRVC/Wilbur Smith PDF does and does not contain, and why it fails the gate.
- [`docs/future-prediction-dataset-research.md`](docs/future-prediction-dataset-research.md) — 20 numbered findings from the search for trainable datasets, plus the seven final success questions.
- [`docs/methodology.md`](docs/methodology.md) — features, leakage controls, benchmarks, thresholds, PCA/DBSCAN and explanation design.
- [`docs/model_report.md`](docs/model_report.md) — measured performance for the bundled Bengaluru artifact; the Chennai family's full benchmark tables live in [`docs/chennai-metro-dataset.md`](docs/chennai-metro-dataset.md) and `backend/models/chennai-cmrl-metro/model_report.json`.
- [`docs/viva-notes.md`](docs/viva-notes.md) — presentation notes and likely questions.
- [`docs/migration.md`](docs/migration.md) — preserved/modified/removed/added migration record.
- [`FINAL_HANDOFF.md`](FINAL_HANDOFF.md) — final checks and packaging handoff.

## Training on your own GPU

`docs/gpu-training.md` is the whole procedure (Windows PowerShell and bash). Nothing in it requires editing a
Python file: GPU use is selected by installing `backend/requirements-gpu.txt` and setting
`TRANSITCROWD_XGB_DEVICE=cuda`, after `python scripts/check_gpu.py` proves the wheel can drive the card.
`scripts/windows_gpu_training.ps1` runs the sequence end to end and finishes by measuring inference latency.

## Deployment notes

- The container and Render config no longer pin one model or one dataset. `backend/app/main.py` builds one
  service per family listed in `data/registry/model_families.json`, so an added family needs a registry entry and
  its data - not a Dockerfile edit - and a family with missing artifacts degrades alone instead of emptying the API.
- Serving reads small files: `data/processed` for Bengaluru and Chennai, and the committed gzip under
  `data/inference` for families registered through the script (2.1 MB and 2.7 MB for the two Mumbai ones). The
  79 MB and 149 MB source CSVs stay in Git LFS and are never packaged or parsed at startup.
- The frontend is a Vite SPA; `frontend/vercel.json` builds it and rewrites to `index.html`. Set the project
  environment variable **`VITE_API_BASE`** to the deployed API origin (for example
  `https://india-transit-crowd-ai-api.onrender.com/api`); with it unset the app calls `/api` on its own origin,
  which is what `docker-compose.yml` arranges with its nginx proxy. On Render, set `CORS_ORIGINS` to the
  frontend origin.
- Mumbai families are labelled demonstrations everywhere the label matters: `/api/metadata`, every prediction
  response, the prediction panel, the reports and the docs. Training them on faster hardware does not change what
  the data is.
