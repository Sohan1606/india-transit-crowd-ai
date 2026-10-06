# India Transit Crowd AI — Final handoff

**Handoff date:** 2026-10-06 (Asia/Kolkata)  
**Project:** `/home/user/transitcrowd-ai`  
**New archive target:** `/home/user/TransitCrowd-AI-INDIA-FINAL.zip`  
**Legacy archive:** `/home/user/TransitCrowd-AI-FINAL.zip` is intentionally left untouched.  
**Delivery scope:** India-focused multimodal transit discovery; verified passenger-demand prediction is enabled for Bengaluru Namma Metro / BMRCL only.

## Executive handoff

This is a migration of the existing React + TypeScript + Vite, FastAPI and ML project—not an equivalent-functionality rewrite. The premium responsive product shell, presentation component names, model-serving boundary, evaluation workflow, and useful engineering structure have been adapted and retained. The former New York/MTA data, artifacts, metrics and active product claims have been retired. A detailed preserved / modified / removed / added record is in [`docs/migration.md`](docs/migration.md).

The product catalogs selected Indian transit systems by city, mode and operator. It does **not** imply nationwide or multimode prediction. The only enabled model family is `bengaluru-namma-metro`, trained on verified hourly Namma Metro/BMRCL station boardings. Static GTFS and timetables support discovery only; they are never treated as passenger counts.

## Deliverables

- **India archive:** `/home/user/TransitCrowd-AI-INDIA-FINAL.zip` (separate from the legacy ZIP).
- **Project handoff:** this file, `FINAL_HANDOFF.md`.
- **Measured model report:** [`docs/model_report.md`](docs/model_report.md).
- **Machine-readable benchmark:** `backend/models/bengaluru-namma-metro/model_report.json`.
- **Saved model bundle:** `backend/models/bengaluru-namma-metro/transitcrowd.joblib`.
- **Saved station profiles:** `backend/models/bengaluru-namma-metro/station_analytics.json`.
- **Persisted-champion test replay:** `backend/models/bengaluru-namma-metro/evaluation_replay.json`.
- **Pinned source snapshot and license:** `data/raw/india/bmrcl-station-hourly.csv.zip`, `data/processed/namma_metro_station_hourly.csv`, `data/licenses/ODbL-1.0.txt` and `data/licenses/BMRCL-ATTRIBUTION.md`.
- **Migration record:** [`docs/migration.md`](docs/migration.md).

The ZIP includes source code, tests, docs, deployment configuration, the compact source snapshot/normalized dataset, license notices and the enabled model-family artifacts. It excludes `.env`/secrets, `node_modules`, virtual environments, caches, generated build output, QA screenshots and unnecessary bulk downloads. The pinned data and model files needed to reproduce or run the verified family are retained.

## Verified prediction source and scope

- **Source:** [Vonter/bmrcl-ridership-hourly](https://github.com/Vonter/bmrcl-ridership-hourly), a station-wise hourly ridership compilation documented as RTI-sourced; pinned commit `6c44579b5ff3428a88bddc44baf84e436a940612`.
- **Measure:** source `Ridership`, interpreted by its data dictionary as passengers boarding at that station during the hour. It is **not** onboard load, current occupancy, train capacity or a live count.
- **Coverage:** August 1–18 and September 1–30, 2025 (Asia/Kolkata); August 19–31 is absent and the station roster changes during August.
- **Observed data:** 92,280 station-hour rows across 83 stations; 18,200 explicit source zeros retained; zero missing-hour fills. Missing observations remain missing.
- **License:** Open Database License (ODbL) 1.0 as stated by the upstream repository. The pinned license text, attribution, share-alike notice and upstream underlying-rights caution are preserved in `data/licenses/`.
- **Pinned raw ZIP SHA-256:** `a0469f3365c53ca25d9aed5396775fc1c6018cfc0b93e245e8bc3e1c9524bd81`.
- **Normalized CSV SHA-256:** `9cbc3981092d42792a6c50a2af032cf3c6f018b8e41ed0aa297716e486adb062`.

No synthetic demand, imputed station-hour rows, fabricated stations, live positions, capacity, occupancy, confidence percentages or nationwide predictions are used. The trained target is next-consecutive-hour **station boardings**.

## Other Indian sources reviewed

These are documented as future candidates or network references, not active model inputs. Provenance, granularity, access, license notes and forecast suitability are detailed in [`docs/dataset.md`](docs/dataset.md) and exposed through `GET /api/demand-sources`.

### Observed-demand leads

- **Delhi Metro / DMRC:** Delhi Transport Stack catalogs hourly station-entry/exit footfall as approval-based Excel. It was not downloaded or approved, and dataset-specific re-use terms need confirmation. OTD static DMRC GTFS is schedule/network data, not footfall.
- **Mumbai MMRDA Metro / Monorail:** data.gov.in lists a daily line-level monorail ridership resource for 2024-10-01 through 2025-09-21, including ticket/media categories and totals. The reviewed resource view did not expose an individual license field; recheck the downloadable resource metadata and permissions before reuse. The file is not bundled or used for training.
- **Chennai CMRL:** OpenCity lists monthly system usage totals through June 2026 with resource metadata marked Public Domain. Monthly totals are too coarse for next-hour station forecasting; re-fetch and verify metadata before ingestion.

None of these sources is registered or prediction-enabled. Catalog presence is not model availability.

### Network / schedule-only references

Delhi OTD bus and DMRC static data, Mumbai BEST/TMT/KDMT community GTFS, Pune PMPML GTFS, Kochi KMRL open GTFS and Hyderabad HMRL GTFS are discovery references. Their contents are schedules, stops, routes, trips or fares—not observed boardings or occupancy. OTD use terms/access conditions apply; the community Mumbai/Pune feed licenses do not by themselves establish rights in the underlying operator data. No private-key real-time API, live vehicle location or live demand feed is assumed.

## Model method and measured results

### Chronological evaluation

- 64,200 supervised next-hour examples are evaluated using unique target timestamps split chronologically; all stations at a timestamp stay in the same partition.
- Train: **43,865** rows; validation: **10,126**; final held-out test: **10,209**.
- The final test does not select champions. Three expanding-window time-series folds run inside training. Thresholds are training-only and frozen; station PCA/DBSCAN profiles use records through the training cutoff.
- Features use station identity, known-at-target calendar fields and strictly earlier contiguous history. Missing-hour gaps are not bridged.

### Saved champion test results

| Task | Saved champion | Held-out test metric |
|---|---|---|
| Next-hour boarding regression | XGBoost | MAE **44.5757**, RMSE **91.0624**, R² **0.95958** |
| Historical-relative band classification | Random Forest | Macro-F1 **0.76902**, HIGH recall **0.64922**, SEVERE recall **0.85470** |

`evaluation_replay.json`, the saved bundle, `model_report.json` and `docs/model_report.md` have been reconciled to the same persisted-champion test outputs. The full candidate comparisons, validation results and other metrics are in the report.

### Bands, profiles and explanations

- Global training-only cuts: P50 **223**, P80 **612**, P95 **1,399** boardings/hour. Risk band rules: LOW ≤ P50; MODERATE > P50 through P80; HIGH > P80 through P95; SEVERE > P95. The resolver prefers sufficiently sampled station/entity cuts, then system-level cuts, then global fallback.
- These labels describe historical-relative demand only. They are not physical crowding, safety, capacity or occupancy levels.
- Two-component PCA retains **0.8999** of profile-feature variance. Training-window DBSCAN identifies **2** clusters and **13** noise stations (`epsilon ≈ 0.9577`, `min_samples=3`). Cluster labels are algorithm outputs, not named station types. A fresh fit matched the saved station profiles.
- Global permutation importance and request-time model sensitivity are associational, not causal. No calibrated interval or confidence percentage is produced. Nearby-hour recommendations are lower model estimates only, not capacity guarantees.

## Product and API behavior

The responsive UI supports India city → mode → operator → station discovery and clearly distinguishes a verified model from systems with no verified demand source/model. Selecting an unsupported system clears prior prediction results and explains why no forecast is available. Observed history and heatmaps contain source observations only; absent hours are not drawn as zero counts.

FastAPI routes are under `/api`; key routes include `GET /health`, `/systems`, `/demand-sources`, `/metadata`, `/stations`, `/history`, `/heatmap`, `/station-analytics`, `/model-performance`, `POST /predict` and `/station-comparison`. Catalogued-but-unsupported prediction requests return an explicit unavailable response; missing artifacts/data and insufficient history are not replaced with sample values. The browser talks to relative `/api` paths through the Vite proxy.

A browser smoke request at Attiguppe for 2025-10-01 00:00 IST returned a persisted-model estimate of approximately **0.964 boardings/hour** (displayed rounded to 1), labeled LOW by that station's training-history thresholds. This is a one-step projection beyond the historical snapshot frontier, not a current observation or today’s ridership.

## Verification completed

### Automated checks

- Backend: `python -m pytest backend/tests -q` — **18 passed**; six non-failing SciPy/scikit-learn L-BFGS-B deprecation warnings.
- Python syntax/import compilation: `python -m compileall -q backend ml scripts` — **passed**.
- Frontend: `npm ci` — **passed**, zero reported package vulnerabilities; `npm test` — **8 passed** after the ResizeObserver test mock was updated; `npm run build` — **passed** with TypeScript checking and Vite production bundling.

### Live API and browser

- Live `GET /api/health` reported `status=ok`, `model_ready=true` and `data_ready=true` for `bengaluru-namma-metro`. A direct unsupported DMRC prediction request returned **409** with the no-verified-demand reason; an unknown station returned **404**.
- Desktop Chromium at **1440×1000**: loaded all 10 catalog cards and the ready BMRCL model, completed a real prediction, and showed the unsupported Delhi Metro state without a station forecast form.
- Mobile Chromium at **390×844**: mobile navigation opened and closed; prediction/unavailable UI remained usable. Document and body widths matched the viewport on both sizes, including unsupported state.
- The final smoke run recorded **37 API responses, all HTTP 200**, with no page errors, console errors or failed browser requests.

### Deployment limits

- Docker is not installed (`docker: command not found`), so no Docker image/Compose run was possible. No hosted Render/Vercel deployment was performed. Included deployment configuration and instructions are not evidence of a deployed service.

## Run locally

Requires Python 3.13 and Node.js 20+ with npm. The enabled model and normalized source are included; retraining/redownloading requires network access.

```bash
# From the extracted India project root
python3.13 -m venv .venv
source .venv/bin/activate              # PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.txt

# Terminal 1: API
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2: UI
cd frontend
npm ci
npm run dev
```

Open the Vite URL (normally `http://localhost:5173`). FastAPI docs are at `http://localhost:8000/api/docs`. The frontend proxies relative `/api` calls to port 8000.

### Reproduce the source and model pipeline

```bash
# Project root; network required only to redownload the pinned upstream ZIP
python scripts/download_data.py
python scripts/prepare_data.py
python scripts/train_models.py
python scripts/evaluate_models.py
```

The downloader checks the pinned archive checksum. Replacing the upstream revision requires a new source review, provenance and checksum; do not bypass the check. New mode/operator families must have their own verified passenger-demand source, licensing review, adapter, chronological evaluation and saved artifact before the catalog can enable prediction.

## Limits to carry into a presentation

- The source is a historical snapshot ending 2025-09-30, not a live feed or current 2026 service dataset. It has a long August gap and a changing station roster.
- The late holdout is short; these results do not establish annual seasonality or generalization to other dates, stations, operators, cities or modes.
- Boardings are station entry counts, not the number onboard a train. No capacity/occupancy field, delay, disruption, weather, event or current timetable input is joined to the model.
- Recursive projection is bounded to 336 hours from a station’s latest source frontier and error can compound. No calibrated uncertainty interval is available.
- GTFS and other network/schedule data must not be described as ridership. Do not claim India-wide prediction, live vehicles, real-time crowding, safety ratings or availability of unsupported model families.
