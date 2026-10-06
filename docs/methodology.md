# Methodology

**Question:** Can historical BMRCL/Namma Metro station boardings support a one-hour-ahead estimate of station entries, and can a training-only historical distribution describe that estimate as relative demand? The answer is evaluated only for the verified Bengaluru dataset snapshot, not for other modes, cities or present-day service.

## Data preparation

`BMRCLRidershipAdapter` reads the pinned semicolon-delimited `Date;Hour;Station;Ridership` source. It validates the exact schema, whole non-negative passenger counts, station names and duplicate `(station, local hour)` keys; creates stable entity IDs; and localizes date/hour in `Asia/Kolkata`. A schema change, checksum mismatch or invalid count raises a source error rather than silently dropping rows.

`clean_normalized_demand` enforces the shared record contract and one system/operator family per training call. Reported zeros are valid observations. Missing station-hours stay missing. No schedule fields, vehicle-capacity values, occupancy or synthetic passenger targets are introduced. The source's August 19–31 discontinuity and changing station roster remain visible in normalized records and are not bridged.

## Forecast target and features

For a station and target hour `T`, the model estimates the observed boarding count at `T` from values available strictly before `T`. The forecast origin is `T − 1 hour`.

Features comprise:

- **Known-at-target calendar:** hour, weekday, day-of-month, month, ISO week, weekend indicator and a weekday peak-hour indicator.
- **Station identity:** stable `entity_id`, encoded as a categorical model input.
- **Observed history only:** 1-, 24- and 168-hour lags; rolling means over the previous 3, 24 and 168 hours; 24- and 168-hour rolling standard deviations; same clock hour one day and one week earlier.

A row is eligible only if the required prior-hour windows and target observation are consecutive and present. Missing-hour gaps invalidate affected windows. The model never sees the target count as a feature; timezone-aware target timestamps determine calendar fields using the registered family timezone.

The same one-step model is used for later targets by iterative recursion when requested. The API bounds that recursive projection to 336 hours beyond each station's latest observation and labels it as a projection from the historical source frontier. Recursive error can compound; this is not a present-day/live service forecast.

## Chronological evaluation

The supervised examples are split globally by unique target timestamp so all stations for one target hour stay together:

| Partition | Rows | Unique target hours |
|---|---:|---:|
| Train | 43,865 | 571 |
| Validation | 10,126 | 122 |
| Final test | 10,209 | 123 |

The earliest 70% of unique target hours train models; the next 15% select champions on validation; the latest 15% provide the final held-out measurement. The test is not used to select candidates. Three expanding-window `TimeSeriesSplit` folds are run inside the chronological training period; thresholds are refitted from each fold's training rows only. The selected champion is fitted on train+validation and evaluated on the held-out test. [`docs/model_report.md`](model_report.md) is the detailed machine-generated run report; the family directory retains JSON metrics and an independent persisted-artifact replay.

### Regression benchmark

Candidates are seasonal naive (same-hour previous day, prior-hour fallback), Linear Regression, Decision Tree, Random Forest, linear SVR and XGBoost. Regression is measured with MAE, RMSE and R². Validation MAE selects the winner; validation RMSE is the tie-break. The current saved champion is **XGBoost**. It beats the validation seasonal-naive baseline (MAE 36.26 versus 90.03 boardings/hour); exact validation, final-test and replay values are in the model report.

### Secondary historical-relative classification

A separate model predicts the four historical-relative labels using the same leakage-safe features. Candidates are a most-frequent baseline, Logistic Regression, Decision Tree, Random Forest, Linear SVM and XGBoost. Validation macro-F1 selects the classifier, with HIGH recall as the tie-break. Accuracy, macro/weighted precision and F1, macro recall, class-specific HIGH/SEVERE recall, confusion matrices, Cohen's kappa and multiclass ROC-AUC (when valid probabilities exist) are recorded.

The product's primary band is obtained by comparing the regression estimate with frozen training-only percentiles. The separately trained classifier is returned as a clearly labeled cross-check; it does not silently replace the documented percentile rule. The saved classifier champion is **Random Forest**. This classification task represents relative historical demand labels, not actual capacity-based crowding.

## Frozen historical-relative thresholds

Thresholds are fitted only on next-hour target values in the training partition, then frozen for validation, test and inference. The saved current global training cuts are:

| Cut | Training value |
|---|---:|
| P50 | 223 boardings/hour |
| P80 | 612 boardings/hour |
| P95 | 1,399 boardings/hour |

The resolver prefers station/entity cuts with at least 500 training targets, then the family-level city/mode/operator distribution with at least 500 targets, then the global training distribution. Sample counts and the chosen fallback are returned by the API.

| Label | Rule |
|---|---|
| LOW | demand ≤ P50 |
| MODERATE | P50 < demand ≤ P80 |
| HIGH | P80 < demand ≤ P95 |
| SEVERE | demand > P95 |

These are historical-relative **demand** labels. The source has no train capacity, onboard sensor, passenger load or station-density denominator. The labels must not be interpreted as physical occupancy, seat availability, safety, or a cross-station safety ranking.

## Station profiles: PCA + DBSCAN

PCA and DBSCAN are fitted using only source rows through the chronological training cutoff. Per-station features include mean demand; observed morning, afternoon and evening means; weekend mean; observed-demand P95; variance; coefficient of variation; top-six-clock-hour demand concentration; and P95-to-mean ratio. Top-hour concentration is calculated from clock-hour means with observed source records; absent bins are not assigned synthetic zero counts. Missing aggregate features (if any) are filled with cross-entity feature medians only for the profile matrix, never in the observed-demand series or forecast targets.

The pipeline applies `StandardScaler`, two-component PCA and Euclidean DBSCAN in the PCA coordinates. `min_samples=3`; epsilon is the observed 75th percentile of distances to the `min_samples`-th nearest station. The current fit retains 0.8999 of standardized-feature variance in two PCs and reports two DBSCAN clusters with 13 noise stations. IDs and noise labels are algorithm outputs; the project does not manually invent station segment names.

## Explainability and recommendations

- **Global sensitivity:** permutation importance on chronological validation rows for the train-only fitted regression champion, scored as increase in MAE. It is associational, not causal.
- **Local sensitivity:** at request time, each numeric feature is changed individually to its training-partition median and the persisted regression model is re-run. The signed prediction difference is shown against that reference. It is not SHAP, a causal explanation or a calibrated uncertainty interval; correlated inputs are not jointly adjusted.
- **Nearby-hour recommendations:** the same station model is queried for eligible hours within ±3 hours, excluding the selected hour. Any “lower-demand” option is a lower model estimate only, not a guarantee of lower occupancy or available capacity.
- **Station comparisons:** each estimate is shown with its station-specific training-history percentile. The percentile contextualizes station history; it is not a comparable safety rating between stations.

No confidence percentage or calibrated prediction interval is produced.

## Limitations and responsible use

1. The snapshot ends September 30, 2025, spans only two discontinuous periods and has a changing August station roster. It is not live and cannot describe current 2026 service conditions.
2. The late test period is short and cannot establish annual seasonality or generalization to a new station, operator, city or transit mode.
3. Recursive estimates beyond the latest observation may compound error and are bounded to 336 hours. Historical source gaps are not actual zero boarding counts.
4. No current timetables, delays, disruption, weather, special events, transfer flows, service frequency, capacity or onboard occupancy are joined to the model.
5. No calibrated confidence or uncertainty interval exists. This is an offline academic decision-support prototype, not the sole basis for operational or safety decisions.
6. Other Indian datasets and GTFS references require separate provenance, license, access, target-resolution and evaluation review before prediction is enabled.
