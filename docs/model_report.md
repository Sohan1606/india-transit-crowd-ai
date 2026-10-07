# INDIA TRANSIT CROWD AI — Model report

> **PREDICT THE CROWD. PLAN THE JOURNEY.**

## Model scope

- **System:** Mumbai · SUBURBAN · Central Railway (`mumbai-local-central`).
- **Model version:** `2.0.0-india`; trained 2026-10-07T05:11:48.614112+00:00.
- **Observed source rows:** 152,640; **supervised rows:** 143,736; **entities:** 53.
- **Source window:** 2026-06-09T00:00:00+05:30 through 2026-10-06T23:00:00+05:30 (timestamps use the source timezone).
- **Explicit zero observations retained:** 0; **missing observations filled:** 0.
- **Target:** next consecutive station-hour boardings (`passengers_per_hour`), not onboard load or physical occupancy.
- **Source:** Central Railway observed passenger demand (synthetic_development) — https://github.com/Sohan1606/india-transit-crowd-ai/tree/feature/future-demand-dataset/data/development/synthetic.
- **License:** Provided by the dataset owner for development use; not a public feed — see data/licenses/ODbL-1.0.txt.

Only this verified Bengaluru BMRCL/Namma Metro model family is enabled. No India-wide, bus, live, or other-operator predictions are represented by this report.

## Chronological evaluation design

Chronological global target-time split over unique station-hour timestamps: earliest 70% train, next 15% validation, latest 15% test; same timestamp never crosses partitions.

| Partition | Rows | Unique target hours | Start | End |
|---|---:|---:|---|---|
| Train | 100,594 | 1898 | 2026-06-16 00:00:00+05:30 | 2026-09-03 01:00:00+05:30 |
| Validation | 21,571 | 407 | 2026-09-03 02:00:00+05:30 | 2026-09-20 00:00:00+05:30 |
| Test | 21,571 | 407 | 2026-09-20 01:00:00+05:30 | 2026-10-06 23:00:00+05:30 |

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

**Validation-selected model:** Random Forest (MAE first; RMSE tie-break).

| Rank | Candidate | Validation | Test | Fit (s) |
|---:|---|---:|---:|---:|
| 1 | Random Forest | MAE 392.43 · RMSE 570.73 · R² 0.972 | MAE 388.91 · RMSE 539.25 · R² 0.973 | 27.973 |
| 2 | Decision Tree | MAE 417.02 · RMSE 607.96 · R² 0.968 | MAE 422.78 · RMSE 599.20 · R² 0.967 | 1.085 |
| 3 | Xgboost | MAE 443.62 · RMSE 640.40 · R² 0.965 | MAE 483.46 · RMSE 665.46 · R² 0.960 | 0.892 |
| 4 | Linear Regression | MAE 558.92 · RMSE 776.59 · R² 0.948 | MAE 589.57 · RMSE 806.30 · R² 0.941 | 0.207 |
| 5 | Svr | MAE 559.17 · RMSE 768.66 · R² 0.949 | MAE 578.79 · RMSE 802.01 · R² 0.941 | 0.121 |
| 6 | Seasonal Naive | MAE 981.19 · RMSE 1,522.54 · R² 0.801 | MAE 1,063.54 · RMSE 1,587.98 · R² 0.769 | 0.000 |

## Historical-relative classification benchmark

**Validation-selected model:** Xgboost (macro-F1, then HIGH recall).

| Rank | Candidate | Validation | Test | Fit (s) |
|---:|---|---:|---:|---:|
| 1 | Xgboost | macro-F1 0.737 · HIGH recall 0.755 | macro-F1 0.673 · HIGH recall 0.835 · SEVERE recall 0.156 | 2.133 |
| 2 | Random Forest | macro-F1 0.700 · HIGH recall 0.605 | macro-F1 0.671 · HIGH recall 0.823 · SEVERE recall 0.127 | 22.427 |
| 3 | Svm | macro-F1 0.690 · HIGH recall 0.798 | macro-F1 0.587 · HIGH recall 0.790 · SEVERE recall 0.023 | 1.133 |
| 4 | Logistic Regression | macro-F1 0.684 · HIGH recall 0.683 | macro-F1 0.627 · HIGH recall 0.718 · SEVERE recall 0.266 | 6.009 |
| 5 | Decision Tree | macro-F1 0.656 · HIGH recall 0.479 | macro-F1 0.633 · HIGH recall 0.578 · SEVERE recall 0.382 | 1.154 |
| 6 | Baseline | macro-F1 0.165 · HIGH recall 0.000 | macro-F1 0.169 · HIGH recall 0.000 · SEVERE recall 0.000 | 0.011 |

Risk thresholds are trained-only historical percentiles, frozen for validation/test/inference:

- Global training cuts: P50 **4,660**, P80 **9,068**, P95 **11,957** station boardings per hour.
- Threshold hierarchy: station/entity when adequately sampled → city/mode/operator system → global training fallback. Minimum entity targets: 500; minimum system targets: 500.
- Labels: LOW ≤ P50; MODERATE > P50 and ≤ P80; HIGH > P80 and ≤ P95; SEVERE > P95.
- These labels express relative historical demand only; they are not calibrated physical crowding, capacity or safety levels.

## PCA / DBSCAN station profiles

- Fitted on observed records through the training cutoff only; entities: 53.
- Two-component PCA variance retained: 0.9713.
- DBSCAN groups (excluding noise): 3; noise points: 7; ε=0.8325, min_samples=3.
- Cluster IDs and noise labels are algorithm outputs, not source-provided entity types. No manual cluster labels are assigned.

## Model-backed explanations

- Global: Permutation importance on chronological validation observations, scoring increase in MAE; associational, not causal.
- Local: At inference, one feature at a time is replaced with its training median and the selected model is re-run; not SHAP and not causal attribution.
- Uncertainty: No calibrated prediction interval or confidence percentage is produced.

## Limitations

- Only the registered Central Railway SUBURBAN family 'mumbai-local-central' has a trained model in this project; no India-wide, network-wide, live, bus, or other-operator prediction is implied by its numbers.
- The target is passengers per hour per hour. It is not onboard load, occupancy, capacity utilisation, crowding safety level, or the number of people currently on a train or platform.
- No weather, disruption, fare-change, event, transfer, origin-destination or service-frequency variable is joined to the model beyond the columns this dataset publishes.
- Tree and linear models cannot extrapolate beyond the observed feature range; forecasts far past the data frontier regress toward recent levels rather than inventing new ones.
- The source series ends 2026-10-06. It begins 2026-06-09. A request for a date or hour after that frontier is returned as a model forecast and labelled as one; a value inside it is a historical replay of an observation, never a live reading.
- This family's values are synthetic development data and are served as a demo: every response carries the synthetic disclosure, and no metric here is evidence about real passengers. The architecture is the point; the numbers are illustrative.
- Models were fitted on 152,640 of 354,888 available rows (120 days from 2026-06-09 to 2026-10-06) because a wider fit exceeds the memory of the runner that produced them; the complete stored history is still served as observations, and every metric above describes that window.
- Forecasts past the most recent observation are recursive one-hour model calls, limited to 336 hours from the data frontier; the uncertainty of those calls is not calibrated and is reported as historical-relative bands, never as a confidence percentage.
- No confidence percentage is produced. A missing observation must never be read as zero demand, and a forecast must never be read as a measurement.

This report describes the specific source snapshot and trained model artifact only. It does not validate performance for another operator, mode, city, present-day service or the whole country.
