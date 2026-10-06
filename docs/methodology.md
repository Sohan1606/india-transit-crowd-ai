# Methodology

**Question:** Can historical station-level boardings support a prediction of demand at a time the source has not yet published, and can a training-only historical distribution describe that estimate as relative demand? Two families are evaluated, each at its own granularity: BMRCL/Namma Metro station-hours one hour ahead (Bengaluru snapshot only), and CMRL station-days one day ahead including projections past the last observed day (Chennai). Neither result transfers to other modes, cities or present-day service.

## Data preparation

`BMRCLRidershipAdapter` reads the pinned semicolon-delimited `Date;Hour;Station;Ridership` source. It validates the exact schema, whole non-negative passenger counts, station names and duplicate `(station, local hour)` keys; creates stable entity IDs; and localizes date/hour in `Asia/Kolkata`. A schema change, checksum mismatch or invalid count raises a source error rather than silently dropping rows.

`clean_normalized_demand` enforces the shared record contract and one system/operator family per training call. Reported zeros are valid observations. Missing station-hours stay missing. No schedule fields, vehicle-capacity values, occupancy or synthetic passenger targets are introduced. The source's August 19–31 discontinuity and changing station roster remain visible in normalized records and are not bridged.

## Dataset admission before methodology

A candidate must pass ten criteria in `scripts/validate_demand_dataset.py` before any model is fitted: actual observed target values, known and consistent time ordering, stable entity identity, quantified missingness, no future value used as a past feature, documented provenance and rights, enough observations for a chronological split, known granularity, compatible measures, and a genuine period that can be held out as future. The report is committed per system (`data/research/<system_id>_validation_gate.json`).

The leakage check is functional, not structural: the row for the exact target period of one entity is altered to a different value, and the supervised frame must come out byte-identical at and before that period for every column. Rows after the altered target may legitimately change because a later target uses the altered value as a lag — that is future-to-past influence, which is allowed. Target-day calendar fields are the only permitted exception. This probe is what caught an earlier implementation that indexed lags from the origin row (`shift(lag - 1)`), which made the one-day lag the target itself: MAE 0.00 on validation and test, macro-F1 1.000, and an "importance" ranking that ranked the three constant columns highest. Both families now pass the probe (Bengaluru: 17 columns; Chennai: 17 columns) and are recomputed on every run.

The gate also refuses on rights and semantics, not only shape. The Mumbai suburban-rail PDF extract fails six criteria and is therefore published as a labelled historical baseline, with its 2016/2021/2031 forecast block quarantined as `HISTORICAL STUDY MODEL OUTPUT` and `eligible_as_supervised_label: false` — never as a training label, because training on a demand model's own outputs is circular and cannot be verified against reality.

## Forecast target and features

For a station and target hour `T`, the model estimates the observed boarding count at `T` from values available strictly before `T`. The forecast origin is `T − 1 hour`.

Features comprise:

- **Known-at-target calendar:** hour, weekday, day-of-month, month, ISO week, weekend indicator and a weekday peak-hour indicator.
- **Station identity:** stable `entity_id`, encoded as a categorical model input.
- **Observed history only:** 1-, 24- and 168-hour lags; rolling means over the previous 3, 24 and 168 hours; 24- and 168-hour rolling standard deviations; same clock hour one day and one week earlier.

A row is eligible only if the required prior-hour windows and target observation are consecutive and present. Missing-hour gaps invalidate affected windows. The model never sees the target count as a feature; timezone-aware target timestamps determine calendar fields using the registered family timezone.

The same one-step model is used for later targets by iterative recursion when requested. The API bounds that recursive projection to 336 hours beyond each station's latest observation (60 days for the daily family) and labels it as a projection from the historical source frontier. Recursive error can compound; this is not a present-day/live service forecast.

### Daily family (Chennai / CMRL)

For a station-line entity and target **day** `D`, the model estimates observed entries on `D` from history strictly before `D`. The forecast origin is `D − 1 day`, and the features are:

- **Known-at-target calendar:** day-of-week, day-of-month, month, ISO week, weekend indicator, and `days_before_public_holiday` only when a holiday table is registered (currently none, so the column is omitted rather than zero-filled).
- **Entity identity:** stable `entity_id` (`line-<line>-<station-code>`), so an interchange contributes two entities and is never summed.
- **Observed history only:** 1-, 2-, 7- and 14-day lags; 7- and 28-day rolling mean/standard deviation of entries, weekday demand and missing-row share; same-weekday mean over the previous 4 weeks; 7- and 14-day rolling means of total and completed services.

Rows are built on a dense per-entity calendar grid *before* lagging, so a day the source skipped deletes the 1-day-lag rows for 7 and 28 days afterwards — the gap suppresses training rows instead of becoming a bridge feature. An entity needs 28 days of history before its first target.

Risk boundaries for the daily family are fitted on the supervised-frame targets rather than a separate target series, and every response carries `threshold_source`; with 227 target days per entity, no station clears the 500-target requirement, so all Chennai answers currently report `system_training_fallback` and the UI says so.

Because the last observed day is one day behind today, day-granularity responses split into two kinds: at/below the frontier → `forecast_kind: "historical_replay"`, `is_model_forecast: false`; beyond it → `post_frontier_projection`, `is_model_forecast: true`, with the horizon in days, the frontier, the training cut-off and a note naming the projection. Both kinds carry `model_training_cutoff` and `data_freshness_note`.

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

No confidence percentage is produced. The `forecast_interval` the API returns is an empirical p90 of absolute
error measured on validation days and is labelled `calibrated: false` / `is_confidence_interval: false` in every
response (see *Horizon validation and empirical forecast bands*).

## Horizon validation and empirical forecast bands

A projection more than one period ahead is produced by feeding the model its own answer and stepping
forward again (recursive forecasting). Error therefore compounds, and the product has to say how much.

`ml/training/horizon.py` measures it instead of assuming it. After the champion is selected, the
trainer re-runs it through the exact code path the API uses (`ml.training.forecast.project_future`)
across the **validation partition only**, per entity and per horizon day, and records for each horizon:
samples, MAE, RMSE, median absolute error, the p90 and p95 of absolute error, and the p90/p95 of
absolute *relative* error. Nothing on the test partition is consulted for this decision.

Two policy numbers come out of that table:

* **usable horizon** - the largest measured day whose MAE is still at or below the dispersion of the
  values being predicted (the standard deviation of validation targets). Beyond it a projection no
  longer beats "predict the average", so it is not a forecast of that particular day;
* **horizon limit** - the usable horizon when an error blow-up was actually measured inside the
  window, otherwise the documented technical ceiling (60 days for the day families, floored at 7 days
  so a small toy archive cannot silently disable the product).

`max_recursive_horizon_days` in the saved bundle is that limit; requests beyond it are refused with 422
and the measured reason.

For the shipped Chennai family: validation window 2026-07-29 to 2026-08-31, 34 horizons x 43 entities
= 1,462 projected (entity, day) pairs, 0 unprojectable. Measured MAE was 555.1 at +1 day, 821.2 at +7
days, 2,923.7 at +14 days (the worst horizon; p90 of absolute error 5,388.9), and 584.3 at +34 days,
against a validation-target standard deviation of 3,873.6. No horizon inside the measured window lost to
that baseline, so the limit stays at the documented 60 days and 34 days are labelled as validated.

**What `forecast_interval` is.** For every future answer the API returns
`forecast_interval.lower/upper` = prediction +/- the p90 of absolute error *at that horizon*, measured
as above. It is an empirical residual band, not a calibrated prediction interval: `calibrated: false`
and `is_confidence_interval: false` are part of the payload, and no coverage percentage is claimed. For
a horizon past the measured window the **widest** measured band is reused, `band_basis` reads
`worst_measured_horizon`, and `horizon_status` reads `beyond_validated_range` - the answer is never
silently presented as if it had been validated.

**Scoring against observations.** Every response also carries the stored observation for the requested
period when the source has one (`actual_observed_demand`, `absolute_error`, `signed_error`,
`absolute_percentage_error`, `evaluation_status: scored_against_observation`). When the source has not
published that period the fields say `OBSERVED VALUE UNAVAILABLE` / `not_scored_future_period` and the
actual stays null - no value is estimated, interpolated or replaced with zero in either direction.

## Limitations and responsible use

1. The snapshot ends September 30, 2025, spans only two discontinuous periods and has a changing August station roster. It is not live and cannot describe current 2026 service conditions.
2. The late test period is short and cannot establish annual seasonality or generalization to a new station, operator, city or transit mode.
3. Recursive estimates beyond the latest observation may compound error and are bounded to 336 hours. Historical source gaps are not actual zero boarding counts.
4. No current timetables, delays, disruption, weather, special events, transfer flows, service frequency, capacity or onboard occupancy are joined to the model.
5. No *calibrated* interval exists: the returned band is an empirical per-horizon absolute-error quantile,
   labelled uncalibrated in the payload, and horizons past the measured window widen to the worst measured band. This is an offline academic decision-support prototype, not the sole basis for operational or safety decisions.
6. Other Indian datasets and GTFS references require separate provenance, license, access, target-resolution and evaluation review before prediction is enabled.
