# INDIA TRANSIT CROWD AI — Model report

> **PREDICT THE CROWD. PLAN THE JOURNEY.**

## Model scope

- **System:** Bengaluru · METRO · BMRCL (`bengaluru-namma-metro`).
- **Model version:** `2.0.0-india`; trained 2026-10-05T18:51:33.183794+00:00.
- **Observed source rows:** 92,280; **supervised rows:** 64,200; **entities:** 83.
- **Source window:** 2025-08-01T00:00:00+05:30 through 2025-09-30T23:00:00+05:30 (timestamps use the source timezone).
- **Explicit zero observations retained:** 18,200; **missing observations filled:** 0.
- **Target:** next consecutive station-hour boardings (`hourly_station_boardings`), not onboard load or physical occupancy.
- **Source:** BMRCL/Namma Metro station-wise hourly ridership (boardings) — https://github.com/Vonter/bmrcl-ridership-hourly.
- **License:** ODbL-1.0 — https://opendatacommons.org/licenses/odbl/1-0/.

Only this verified Bengaluru BMRCL/Namma Metro model family is enabled. No India-wide, bus, live, or other-operator predictions are represented by this report.

## Chronological evaluation design

Chronological global target-time split over unique station-hour timestamps: earliest 70% train, next 15% validation, latest 15% test; same timestamp never crosses partitions.

| Partition | Rows | Unique target hours | Start | End |
|---|---:|---:|---|---|
| Train | 43,865 | 571 | 2025-08-08 00:00:00+05:30 | 2025-09-20 18:00:00+05:30 |
| Validation | 10,126 | 122 | 2025-09-20 19:00:00+05:30 | 2025-09-25 20:00:00+05:30 |
| Test | 10,209 | 123 | 2025-09-25 21:00:00+05:30 | 2025-09-30 23:00:00+05:30 |

The final holdout is not used to select the winning model. Three expanding-window `TimeSeriesSplit` folds run within training data. Thresholds are refitted using each fold's training rows only.

The selected champions are refitted on train + validation; their reported test metrics are recomputed from the exact persisted champion objects and independently replayed without refitting. Other candidates are measured on their benchmark fits.

### Leakage controls

- Target features for hour T use entity-hour observations strictly before T.
- Only consecutive observed hourly histories train; missing station-hours stay missing and are not zero-filled.
- Explicit source zeros are retained as observations; no entity is discarded solely for low or zero demand.
- Risk thresholds are fitted from chronological train targets only and frozen for validation, test and inference.
- Validation selects the champion; the latest test window is reported once and never used for selection.
- PCA/DBSCAN behaviour features are fitted from observations through the training cutoff only.

## Regression benchmark

**Validation-selected model:** Xgboost (MAE first; RMSE tie-break).

| Rank | Candidate | Validation | Test | Fit (s) |
|---:|---|---:|---:|---:|
| 1 | Xgboost | MAE 36.26 · RMSE 71.07 · R² 0.980 | MAE 44.58 · RMSE 91.06 · R² 0.960 | 1.272 |
| 2 | Random Forest | MAE 36.32 · RMSE 76.24 · R² 0.977 | MAE 43.93 · RMSE 92.57 · R² 0.958 | 32.325 |
| 3 | Svr | MAE 37.85 · RMSE 77.59 · R² 0.976 | MAE 46.43 · RMSE 97.83 · R² 0.953 | 0.164 |
| 4 | Decision Tree | MAE 42.27 · RMSE 90.41 · R² 0.968 | MAE 50.05 · RMSE 103.17 · R² 0.948 | 0.804 |
| 5 | Linear Regression | MAE 55.93 · RMSE 91.59 · R² 0.967 | MAE 48.34 · RMSE 94.60 · R² 0.956 | 0.366 |
| 6 | Seasonal Naive | MAE 90.03 · RMSE 227.46 · R² 0.796 | MAE 101.11 · RMSE 222.87 · R² 0.758 | 0.000 |

## Historical-relative classification benchmark

**Validation-selected model:** Random Forest (macro-F1, then HIGH recall).

| Rank | Candidate | Validation | Test | Fit (s) |
|---:|---|---:|---:|---:|
| 1 | Random Forest | macro-F1 0.871 · HIGH recall 0.846 | macro-F1 0.769 · HIGH recall 0.649 · SEVERE recall 0.855 | 29.204 |
| 2 | Xgboost | macro-F1 0.844 · HIGH recall 0.838 | macro-F1 0.761 · HIGH recall 0.649 · SEVERE recall 0.872 | 5.177 |
| 3 | Decision Tree | macro-F1 0.785 · HIGH recall 0.743 | macro-F1 0.720 · HIGH recall 0.616 · SEVERE recall 0.859 | 0.606 |
| 4 | Logistic Regression | macro-F1 0.775 · HIGH recall 0.684 | macro-F1 0.749 · HIGH recall 0.670 · SEVERE recall 0.902 | 12.604 |
| 5 | Svm | macro-F1 0.769 · HIGH recall 0.614 | macro-F1 0.703 · HIGH recall 0.488 · SEVERE recall 0.885 | 1.667 |
| 6 | Baseline | macro-F1 0.179 · HIGH recall 0.000 | macro-F1 0.174 · HIGH recall 0.000 · SEVERE recall 0.000 | 0.027 |

Risk thresholds are trained-only historical percentiles, frozen for validation/test/inference:

- Global training cuts: P50 **223**, P80 **612**, P95 **1,399** station boardings per hour.
- Threshold hierarchy: station/entity when adequately sampled → city/mode/operator system → global training fallback. Minimum entity targets: 500; minimum system targets: 500.
- Labels: LOW ≤ P50; MODERATE > P50 and ≤ P80; HIGH > P80 and ≤ P95; SEVERE > P95.
- These labels express relative historical demand only; they are not calibrated physical crowding, capacity or safety levels.

## PCA / DBSCAN station profiles

- Fitted on observed records through the training cutoff only; entities: 83.
- Two-component PCA variance retained: 0.8999.
- DBSCAN groups (excluding noise): 2; noise points: 13; ε=0.9577, min_samples=3.
- Cluster IDs and noise labels are algorithm outputs, not source-provided entity types. No manual cluster labels are assigned.

## Model-backed explanations

- Global: Permutation importance on chronological validation observations, scoring increase in MAE; associational, not causal.
- Local: At inference, one feature at a time is replaced with its training median and the selected model is re-run; not SHAP and not causal attribution.
- Uncertainty: No calibrated prediction interval or confidence percentage is produced.

## Limitations

- Only the verified Bengaluru BMRCL/Namma Metro hourly station-boardings family has a trained model; no India-wide, bus, live or other-operator prediction is implied.
- This source is a historical snapshot ending 2025-09-30, with a documented 2025-08-19 through 2025-08-31 gap and a changing station roster during August.
- The holdout is a short late-period check; it does not establish yearly seasonality or generalization to current 2026 service conditions.
- Counts are station boardings, not onboard vehicle load or physical occupancy; capacity data is unavailable.
- No current timetable, disruption, weather, event, transfer, passenger-origin or service-frequency variables are joined to the model.
- Forecasts beyond the most recent observation are recursive one-hour model calls, limited to 336 hours from the data frontier; uncertainty is not calibrated.
- No confidence percentage is produced; missing target-period source observations must not be read as zero actual demand.

This report describes the specific source snapshot and trained model artifact only. It does not validate performance for another operator, mode, city, present-day service or the whole country.
