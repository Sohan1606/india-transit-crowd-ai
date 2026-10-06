# India Transit Crowd AI — Final handoff

**Handoff date:** 2026-10-06 (Asia/Kolkata)  
**Project:** `/home/user/repo` (git branch `feature/future-demand-dataset`)  
**Delivered archive:** `/home/user/TransitCrowd-AI-INDIA-FINAL.zip`, built from the committed tree of this branch.  
**Delivery scope:** India-focused multimodal transit discovery; verified passenger-demand prediction is enabled for two gate-passed families — Bengaluru Namma Metro / BMRCL (station-hour) and **Chennai Metro / CMRL (station-day, added on this branch)**. Mumbai suburban rail carries a verified historical survey dataset and is deliberately **not** prediction-enabled.

## Executive handoff

This is a migration of the existing React + TypeScript + Vite, FastAPI and ML project—not an equivalent-functionality rewrite. The premium responsive product shell, presentation component names, model-serving boundary, evaluation workflow, and useful engineering structure have been adapted and retained. The former New York/MTA data, artifacts, metrics and active product claims have been retired. A detailed preserved / modified / removed / added record is in [`docs/migration.md`](docs/migration.md).

The product catalogs selected Indian transit systems by city, mode and operator. It does **not** imply nationwide or multimode prediction. Two model families are enabled, each with its own artifacts, granularity and dataset: `bengaluru-namma-metro` (verified hourly Namma Metro/BMRCL station boardings, preserved unchanged) and `chennai-cmrl-metro` (verified daily CMRL station entries, which is the family that forecasts **days the source has not published yet**). Static GTFS and timetables support discovery only; they are never treated as passenger counts.

The dataset question this branch answers, in one line: **Mumbai suburban rail has genuine observed passenger counts, but not a time series** — the 2011-12/2013 MRVC–Wilbur Smith survey is five single-weekday snapshots and its 2016/2021/2031 numbers are a travel-demand model's outputs — so it fails the Phase-15 gate and is shipped as a labelled baseline plus an append-only collector, while the future-prediction capability was built on Chennai instead.

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
- **Second (day-granularity) model family:** `backend/models/chennai-cmrl-metro/` — `transitcrowd.joblib`, `model_report.json`, `evaluation_replay.json` (one-step replay **and** the recursive future projection), `future_forecast.json` (saved snapshot for 2026-10-07).
- **Dataset research deliverables:** [`docs/chennai-metro-dataset.md`](docs/chennai-metro-dataset.md), [`docs/mumbai-wilbur-smith-dataset.md`](docs/mumbai-wilbur-smith-dataset.md), [`docs/future-prediction-dataset-research.md`](docs/future-prediction-dataset-research.md).
- **Validation gate (10 criteria per candidate):** `scripts/validate_demand_dataset.py`, reports `data/research/chennai-cmrl-metro_validation_gate.json` and `data/research/bengaluru-namma-metro_validation_gate.json`, plus the Mumbai gate inside `data/research/mumbai_suburban_rail_pdf_observed.metadata.json`.
- **Mumbai observed/modelled separation:** `data/research/mumbai_suburban_rail_pdf_observed.csv` (249 records with table + page citations) and `data/research/mumbai_suburban_rail_MODELLED_od_forecast.csv` (quarantined, `eligible_as_supervised_label: false`).
- **Observation collector for systems without history:** `scripts/collect_transit_observations.py` (append-only, deduped, checksummed, never interpolates).

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

### Added family: Chennai Metro / CMRL (station-day)

- **Source:** CMRL's public passenger-flow API (`commuters-dataapi.chennaimetrorail.org`), history from `PratyushBalaji/chennai-metro-ridership-tracker`, pinned commit `72ee5eadb6ca890bfd9900d6464a1a371566c86b`, three raw-file SHA-256 digests verified at download.
- **Coverage:** 10,965 observed station-day rows, 43 station-line entities (41 physical stations), **255 consecutive days** 2026-01-24 → 2026-10-05, 0 missing station-days, 0 fills, 0 source-reported zeros.
- **Measure:** `daily_station_entries`, verified as one counting event per journey by comparing station sums with the system ticket count on every one of the 255 days (mean ratio **1.0061**, min 0.9502, max 1.2106).
- **Rights:** CMRL asserts no bulk-reuse terms and the tracker's MIT licence covers its code only, so the data is **not** redistributed — `scripts/download_cmrl_data.py` refetches and verifies; `data/licenses/CMRL-DATA-NOTICE.md` records the terms.
- **Future horizon:** the archive trails today by **1 day**, so 2026-10-06 onward is a genuine forecast; up to 60 days of recursive projection are served and labelled.
- **Gate:** 10 / 10 criteria pass → `data/research/chennai-cmrl-metro_validation_gate.json`.

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
| Next-hour boarding regression (Bengaluru) | XGBoost | MAE **44.5757**, RMSE **91.0624**, R² **0.95958** |
| Historical-relative band classification (Bengaluru) | Random Forest | Macro-F1 **0.76902**, HIGH recall **0.64922**, SEVERE recall **0.85470** |
| Next-day entry regression (Chennai) | XGBoost | validation MAE **684.62**; test MAE **711.82**, RMSE **1395.78**, R² **0.8706** |
| Next-day entry regression, **recursive future path** (Chennai) | XGBoost | MAE **902.29**, RMSE **1402.51**, R² **0.8691**, sMAPE **16.17%** over 2,967 rows / 69 projected days |
| Historical-relative band classification (Chennai) | XGBoost | validation macro-F1 **0.8304**; test macro-F1 **0.8422**, HIGH recall **0.915**, SEVERE recall **0.756** |

The recursive row — not the one-step number — is what a user of a future date actually receives, so it is published next to the champion. The seasonal-naive baseline's test MAE is **929.78**, i.e. the learned model is 23.4% better than "same weekday last week" on held-out days; a deliberately weak candidate (linear SVR, test R² −0.2031) is reported as a failure rather than dropped.

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

**Future-request semantics (this branch).** On the day family, `POST /api/predict` for 2026-10-07 at `line-01-stl` returned `predicted_demand: 18808.79`, `forecast_kind: "post_frontier_projection"`, `is_model_forecast: true`, `is_recursive_forecast: true`, `forecast_horizon_days: 2`, `data_frontier: 2026-10-05`, `training_cutoff: 2026-07-28` and a note stating the day has not been observed. The same request for an already-observed day (2026-06-15) returns `forecast_kind: "historical_replay"` with `is_model_forecast: false`, so a replayed past day can never be presented as a forecast. `GET /api/future-preview?system_id=chennai-cmrl-metro&days=N` projects the next N unobserved days network-wide (2026-10-06 → 346,732.8 entries; 2026-10-07 → 343,356.0), and `GET /api/source-gap` reports `days_behind_today: 1`. Granularity is enforced at the edge: `heatmap` and `target_hour` on the day family return **409**/**422** rather than invented hour values, and the hour family still requires `target_hour`. Mumbai returns **409** naming the six gate criteria it fails.

The UI follows the same rule: a day family shows a target **date** (no hour picker), reports "NEXT DAY STATION ENTRIES", renders observed weekday bars instead of an hour heatmap, and labels the answer "MODEL FORECAST" or "MODEL OUTPUT · NOT A FORECAST" from the payload.

## Verification completed

### Automated checks

Original delivery (Bengaluru only, recorded for the historical record): backend pytest **18 passed**; `compileall` passed; frontend `npm ci` passed, `npm test` **8 passed**, `npm run build` passed.

Re-run on 2026-10-06 after this branch's additions:

- Backend: `python3 -m pytest backend/tests -q` — **47 passed** (the original 18 unchanged, plus `test_chennai_daily_forecast.py` 16 and `test_mumbai_pdf_dataset.py` 13), 14 non-failing SciPy/scikit-learn deprecation warnings.
- Python syntax/import compilation: `python3 -m compileall -q backend ml scripts` — **passed**.
- Data gates: `python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro` and `--system-id bengaluru-namma-metro` — **10/10 criteria, eligible: True, no critical failures**; the Mumbai extract evaluates **4/10, eligible: false**.
- Leakage probe inside the gate: altering the target day changes no row at or before it, for both families (17 columns compared).
- Retrained from scratch and re-verified: `python3 scripts/train_chennai_models.py --target-date 2026-10-07` (131 s) → the shipped bundle now carries `model_family`, `granularity: day`, `bundle_format: transitcrowd-model-v2`, and `model_report.json` records `uses_test_metrics: false` with `selection_metric: validation MAE; tie-break on validation RMSE, then model key`.
- Frontend: `npm ci` passed; `npx tsc -b` **clean**; `npx vitest run` — **17 passed** (8 original + 9 new day-granularity tests covering the day-form, forecast-vs-replay labelling, weekday bars instead of an hour grid, and the API client's granularity-aware URLs); `npm run build` — **passed** (Vite production bundle).

### Re-run on 2026-10-06 after the integration / adaptability pass

- Backend: `python3 -m pytest backend/tests -q` — **65 passed** (47 previous + `test_adaptive_dataset_pipeline.py` 18 covering the periodic feature schema, semantic profiling, registration refusals, synthetic policy, JSON registry, `development_only` skipping and horizon bands), 14 non-failing warnings.
- `python3 -m compileall -q backend ml scripts` — **passed**.
- Frontend: `npx tsc -b` **clean**; `npx vitest run` — **20 passed** (17 + 3 new accuracy-reporting tests); `npm run build` **passed**.
- Gates after the generalization of `scripts/validate_demand_dataset.py`: re-ran both committed datasets; **all 10 verdicts and every headline number (rows, entities, periods, partitions, gap cells, coverage, eligibility) are identical** to the committed reports. Only two evidence *strings* grew more informative (period in seconds, full tz-aware bounds, the modal-spacing sentence, `provenance class: verified_project_source`); the committed `data/research/*_validation_gate.json` files were regenerated from this run so artifacts and code agree.
- Chennai retrained twice from the same input: `test MAE 711.82`, `macro-F1 0.8422`, recursive `MAE 902.2931 / RMSE 1402.5079`, split `6,794 / 1,462 / 1,505`, `future_forecast.json` and `evaluation_replay.json` byte-identical apart from `generated_at_utc`; the only `model_report.json` differences were `fit_seconds` and one float's last repr digit. Horizon bands are new content, not a change of model.
- Sandbox note (not a project defect): this container had lost its installed packages, so `xgboost`, `pymupdf`, `fastapi`, `httpx` and `pytest` were reinstalled. `xgboost` was pinned back to the declared `2.1.4` before retraining, because joblib bundles are version-sensitive. `pymupdf==1.28.2` is now declared in `backend/requirements.txt` (it was imported by the Mumbai extractor but never listed).
- Frontend `node_modules` is git-ignored and had to be re-created with `npm install` (216 packages) before `tsc`/`vitest`/`build` could be run for real.

### Live API and browser

- Live `GET /api/health` reported `status=ok`, `model_ready=true` and `data_ready=true` for `bengaluru-namma-metro`. A direct unsupported DMRC prediction request returned **409** with the no-verified-demand reason; an unknown station returned **404**.
- Desktop Chromium at **1440×1000**: loaded all 10 catalog cards and the ready BMRCL model, completed a real prediction, and showed the unsupported Delhi Metro state without a station forecast form.
- Mobile Chromium at **390×844**: mobile navigation opened and closed; prediction/unavailable UI remained usable. Document and body widths matched the viewport on both sizes, including unsupported state.
- The final smoke run recorded **37 API responses, all HTTP 200**, with no page errors, console errors or failed browser requests.

### Deployment limits

- Docker is not installed (`docker: command not found`), so no Docker image/Compose run was possible. No hosted Render/Vercel deployment was performed. Included deployment configuration and instructions are not evidence of a deployed service.

## Adaptivity, forecast semantics and cleanup — wrap-up record

### What the pipeline now accepts

`ANY compatible observed-demand table -> profile -> semantic validation -> normalization -> feature
generation -> chronological split -> model selection -> saved artifact -> fast inference`. Each step
adapts to the file instead of the file adapting to the code:

| Concern | Adapted by | Verified with |
| --- | --- | --- |
| Column names / datetime formats | `ml/data_pipeline/profile.py` scores every column on data evidence (parseable share, coverage, monotonicity, repeats per entity, integer share, variability, autocorrelation); names only add a capped ±0.30 prior | resolves `Date/Station/Total` (CMRL export) and `ServiceDate/StationName/RiderCount` equally; test: `test_profiler_uses_data_evidence_rather_than_column_names` |
| Granularity | measured modal timestamp spacing (5 min … 7 days), never declared; `--granularity` may only confirm it | `test_register_refuses_a_granularity_that_the_data_does_not_have`; 15-min grid understood end-to-end (`test_a_fifteen_minute_grid_is_understood…`) |
| Feature schema | `ml/features/periodic.py` scales lags/windows to the period; at 86 400 s it reproduces `ml/features/daily.py` exactly | `test_periodic_builder_matches_the_daily_builder_at_one_day` (row-for-row equality) |
| Missing periods / gaps | counted and reported, never bridged; period alignment enforced by `clean_normalized_demand(period_seconds=…)` | `test_cleaning_aligns_to_the_measured_period_not_to_an_assumed_hour` |
| Optional explanatory columns | kept in the sidecar mapping and the normalized extras; only documented-same-measure columns may be combined, additive relations are detected and refused as a single target | `test_profiler_refuses_to_choose_between_two_plausible_measures` |
| Entity identity | composite keys via `--entity-key-columns` (a per-line terminal report stays two entities rather than being summed) | live run against the raw CMRL archive: 43 line-scoped entities, 10/10 gate |

### What it refuses, with reasons

* two or more near-tied candidate demand columns → refusal listing them (`--demand-column` required);
* a column whose header marks it `forecast`/`predicted`/`modelled`/`simulated`, a per-row surrogate key, or a small-integer code column → disqualified as a label (overridable **only** for a declared development dataset, with the disqualifier printed);
* a declared granularity that contradicts the measured spacing;
* an irregular or single-timestamp grid (no period can be established);
* a dataset that declares itself synthetic/simulated/modelled → fails `target_values_are_actual_observations`, is never registered, lands under `data/development/`, and even `--allow-development-family` marks it `development_only` so `backend/app/main.py` skips it;
* any gate score below 10/10 — the gate is a conjunction, not a rating;
* training a period with no leakage-safe trainer (`day` and `hour` are implemented; `15min` and other supported periods are profiled, normalized, feature-checked and gated, then refused at the training step rather than answered with a day model).

### Historical and future request semantics

`POST /api/predict` now answers three different questions honestly and separately, for both granularities:

1. **Past period the source published** → prediction **plus** `actual_observed_demand`, `absolute_error`, `signed_error`, `absolute_percentage_error`, `evaluation_status: scored_against_observation` (measured live: BMRCL `attiguppe` 2025-09-15 09:00 → prediction 2 026.1 vs actual 2 048, 21.9 off, 1.07 %; Chennai `line-01-stl` 2026-09-30 → 14 179.6 vs 17 940, 20.96 %).
2. **Past period the source never published, or any future period** → `actual_observed_demand: null`, `observation_status: OBSERVED VALUE UNAVAILABLE`, `evaluation_status: not_scored_future_period` / `not_scorable_no_observation_for_target`. A 33-date sweep of post-frontier days found **no** future request carrying an observed value.
3. **Future period** → `MODEL FORECAST`, horizon, model key/version, `training_cutoff`, `data_frontier`, `origin_basis` (`data_frontier_recursive_seed` for multi-day projections instead of a misleading "previous day"), plus `horizon_status` (`within_validated_range` / `beyond_validated_range`) and an empirical `forecast_interval` labelled `calibrated: false`, `is_confidence_interval: false`. Past the 60-day technical ceiling: 422 with the measured reason; an hour asked of a day family: 409 with the alternative named; unknown entity: 404; unknown system: 404/409 per the catalog contract; malformed date: 422 from the request schema.

Horizon governance is measured, not asserted: `ml/training/horizon.py` re-runs the champion recursively over the validation partition (34 horizons × 43 entities = 1 462 pairs, 0 unprojectable) and records MAE/RMSE/p90/p95 per horizon against the validation-target standard deviation (3 873.6). Chennai: MAE 555.1 (+1 d), 821.2 (+7 d), 2 923.7 (+14 d, worst p90 5 388.9), 584.3 (+34 d). No horizon lost to the baseline, so `usable_horizon_days = 34` equals the measured window and the 60-day ceiling stands, documented as `limit_basis: no horizon inside the measured window lost to the mean-predictor baseline`.

### Performance audit

Inference performs no training, no cross-validation and no dataset rebuild; it loads persisted artifacts and projects step-by-step. Measured on this container (TestClient, warm process, x86 CPU): one-step / historical request ≈ **0.2–0.4 s**; `+7 days` recursive ≈ **1.5 s**; `+46 days` ≈ **7.2 s** (each horizon day re-scores the model over the entity series — the recursion, not the lookup, is the cost). `/api/metadata`, `/api/systems`, `/api/stations`, `/api/future-preview` respond in **3–20 ms**. Accuracy claims, refusal semantics and labels are unaffected by this; a faster long-horizon path would need a direct-multi-output model, which is not part of this delivery.

### Cleanup decisions (only genuinely dead/duplicate/stale work removed)

* **No file was deleted from the frontend.** Every component is reachable: each of the 12 section/component files is imported at least once, and `tailwind.config.js` is load-bearing (`@config` reference in `src/index.css`, `font-display` used in 37 places, 14 tailwind utility class usages), so it was kept despite `@tailwindcss/vite` also being present; `postcss.config.js` carries only `autoprefixer` and no duplicate `tailwindcss` plugin, i.e. no double processing to remove.
* Every exported type in `frontend/src/types/api.ts` is referenced; no stale field was found (`evaluation_context` is produced by `daily_service.py` and declared in `schemas/api.py`).
* Backend: no dead endpoint or duplicate service was found. `_granularity` and the response schema already route by family metadata, so the new families needed no per-city branches. Removed instead: `__pycache__`/`*.pyc` trees, a leftover `data/development/` experiment directory, two stray validation-gate files from manual runs, and an unreachable `if False else` expression left in the first draft of the horizon block.
* Added `data/development/` and `data/registry/` to `.gitignore` (locally regenerated, never shipped); declared `pymupdf==1.28.2` in `backend/requirements.txt`.
* Docs were corrected rather than extended where they had drifted: `README.md` (interval claim, payload example, replay scoring), `docs/methodology.md`, `docs/model_report.md`, `docs/dataset.md`, `docs/architecture.md`, and this file (project path, verification counts). No document now claims a capability that is not in the tree, and no claim in the tree is undocumented.

### Data, forecasting and adaptability audit (explicit answers)

1. *Is real observed data used?* Yes — two families, each pinned to a source commit/URL with SHA-256 verification; `data/research/*_validation_gate.json` records the evidence. No synthetic row is in either training set.
2. *Was anything fabricated or interpolated to look like data?* No. Gaps are counted (`missingness_quantified`), zeros are kept only when the source reported them, and `missing_*_filled: 0` is asserted in both sidecars.
3. *Does any model train on forecasts?* No. The Mumbai 2016/2021/2031 study output is quarantined with `eligible_as_supervised_label: false`, and the profiler now actively disqualifies forecast-named columns.
4. *Can it predict a genuinely future period?* Yes — 1 to 60 days past the Chennai frontier, recursively, labelled and horizon-banded; the API refuses beyond that.
5. *Is validation chronological and leakage-safe?* Yes — 70/15/15 by period with all entities in step; the target period is excluded from features and the gate's mutation probe confirms it.
6. *Does the model degrade honestly?* Yes — `uses_test_metrics: false`, one-shot test reporting, per-entity thresholds fall back to system thresholds with `risk_method` naming which was used, and artifacts lacking horizon bands say `unmeasured` instead of inventing accuracy.
7. *Is it dataset-adaptive?* Yes for `day`/`hour` end-to-end, and profile→gate for any supported period; training beyond those two is the one documented gap (see the refusal list above).
8. *Is inference fast and offline?* Yes for lookup and one-step; multi-day cost is the recursion (see performance audit). Nothing retrains at request time.

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
# Second family (Chennai): fetch -> normalize -> gate -> train + future snapshot
python3 scripts/download_cmrl_data.py
python3 scripts/prepare_chennai_data.py
python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro
python3 scripts/train_chennai_models.py --target-date 2026-10-07

# Mumbai PDF: extract observed records + quarantine the modelled forecast block
python3 scripts/extract_mumbai_pdf_surveys.py

# Any system without history: append observed days, then inspect gaps
python3 scripts/collect_transit_observations.py --source cmrl
python3 scripts/collect_transit_observations.py --status

# Original family (Bengaluru)
# Project root; network required only to redownload the pinned upstream ZIP
python scripts/download_data.py
python scripts/prepare_data.py
python scripts/train_models.py
python scripts/evaluate_models.py
```

The downloader checks the pinned archive checksum. Replacing the upstream revision requires a new source review, provenance and checksum; do not bypass the check. New mode/operator families must have their own verified passenger-demand source, licensing review, adapter, chronological evaluation and saved artifact before the catalog can enable prediction.

## Git and delivery state (this pass)

- **Branch:** `feature/future-demand-dataset` (no commits were made on `main`; `main` is untouched).
- **Commit added by this pass:** `d0165ce` — *feat(pipeline): adaptive dataset admission and self-describing forecast answers*;
  31 files changed, +2 746 / −76. Previous branch commit: `d22861d`.
- **Files added:** `ml/features/periodic.py`, `ml/data_pipeline/profile.py`, `ml/training/horizon.py`,
  `scripts/register_demand_dataset.py`, `backend/tests/test_adaptive_dataset_pipeline.py`.
  **Modified:** both inference services, `schemas/api.py`, `main.py`, `registry.py`, `train_daily.py`,
  `cleaning.py`, `validate_demand_dataset.py`, `PredictSection.tsx`, `MethodologySection.tsx`,
  `types/api.ts`, `day-granularity.test.tsx`, the Chennai artifacts (retrained + horizon bands), both committed
  gate reports, `backend/requirements.txt`, `.gitignore`, README, four docs and this file.
  **Deleted:** nothing.
- **Working tree:** clean (`git status --short` → 0 lines) at the time of packaging.
- **Push status:** not pushed, and it cannot be pushed from this environment. `git remote -v` returns nothing,
  `GITHUB_TOKEN`/`GH_TOKEN` are unset and the `gh` CLI is not installed, so the only available attempt failed with
  `fatal: 'origin' does not appear to be a git repository`. From a machine with credentials:
  `git remote add origin https://github.com/<owner>/india-transit-crowd-ai && git push -u origin feature/future-demand-dataset`.
  Nothing else about this delivery depends on that push; the code, artifacts, tests and docs are all in the branch and in the ZIP.
- **Archive:** `/home/user/TransitCrowd-AI-INDIA-FINAL.zip` (16.4 MB, 129 files) built with
  `git archive --format=zip --prefix=TransitCrowd-AI/ HEAD`, i.e. exactly the committed tree - no caches, no
  `node_modules`, no build output, no secrets, no operator-copyrighted CSVs. Verified by extracting it and running
  the suite inside the extraction: **64 passed, 1 skipped** (the Mumbai PDF reproducibility test skips because the
  source PDF is not redistributed) and `POST /api/predict` on the BMRCL family returns the prediction with
  `actual_observed_demand: 2048.0` and `absolute_error: 21.889…`. In a fresh extraction the Chennai family reports
  `prediction_available: false` with `Normalized observed-demand data not found: chennai_metro_demand_timeseries.csv`
  and `POST /api/predict` returns **503** naming that file - expected, because CMRL's data is refetched rather than
  redistributed (run `scripts/download_cmrl_data.py` then `scripts/prepare_chennai_data.py`, and `--refresh-only`
  retraining is not needed: the saved artifacts ship).

## Limits to carry into a presentation

- **Chennai is 8.4 months of data.** 255 days carry weekly seasonality and holidays but no annual cycle; one day of publication lag is permanent unless the collector keeps running; every station currently uses system-level risk cuts (`system_training_fallback`) because per-entity thresholds need 500 targets and each entity has 227.
- **Mumbai is not a forecast.** The PDF is one typical weekday per survey window (5 dates in total), most of its hourly tables are two-stage survey expansions, and the 2016/2021/2031 figures are a demand model's own output. Anyone presenting "Mumbai 2031 demand" is quoting a 2008-vintage model, not counted passengers.
- **No minute-level or 15-minute targets exist** in any Indian source reviewed, so those horizons are not offered at all.

- The source is a historical snapshot ending 2025-09-30, not a live feed or current 2026 service dataset. It has a long August gap and a changing station roster.
- The late holdout is short; these results do not establish annual seasonality or generalization to other dates, stations, operators, cities or modes.
- Boardings are station entry counts, not the number onboard a train. No capacity/occupancy field, delay, disruption, weather, event or current timetable input is joined to the model.
- Recursive projection is bounded to 336 hours from a station’s latest source frontier and error can compound. No calibrated uncertainty interval is available.
- GTFS and other network/schedule data must not be described as ridership. Do not claim India-wide prediction, live vehicles, real-time crowding, safety ratings or availability of unsupported model families.
