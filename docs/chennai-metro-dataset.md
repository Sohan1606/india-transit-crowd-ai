# Chennai Metro (CMRL) — observed station-day demand dataset

Status: **accepted for the primary future-prediction model**. This is the family in this
repository that can answer "how many people will enter this station on a day that has not
happened yet", and it can be scored afterwards.

| Fact | Value |
|---|---|
| System id | `chennai-cmrl-metro` |
| Operator / city | Chennai Metro Rail Limited (CMRL), Chennai, Tamil Nadu |
| Granularity | one calendar day per station-line entity |
| Measure | `daily_station_entries` — passengers recorded as using the station that day |
| Observed rows | **10,965** |
| Entities | **43** station-line entities (41 physical stations; 2 interchanges counted per corridor) |
| Coverage | **2026-01-24 → 2026-10-05**, 255 consecutive days, **0** missing days |
| Filled / interpolated cells | **0** |
| Operator-reported zeros | **0** |
| Lines | `01` (Blue) and `02` (Green) |
| Timezone | `Asia/Kolkata` |
| Validation gate | all ten criteria pass → `data/research/chennai-cmrl-metro_validation_gate.json` |
| Normalized dataset | `data/processed/chennai_metro_demand_timeseries.csv` (**generated, not committed**) + committed `.metadata.json` sidecar |

## 1. Where the numbers come from

CMRL operates a public passenger-flow portal. Its JSON API is the actual publisher:

```
GET https://commuters-dataapi.chennaimetrorail.org/api/PassengerFlow/stationData/1     per-line, per-station day totals
GET https://commuters-dataapi.chennaimetrorail.org/api/PassengerFlow/allTicketCount/1  system ticket count + ticket-type split
GET https://commuters-dataapi.chennaimetrorail.org/api/PassengerFlow/hourlybaseddata/1  network hourly totals (system-level)
```

The portal only serves *yesterday* (`/1`) or the running day (`/0`), so the historical
record comes from `PratyushBalaji/chennai-metro-ridership-tracker`, whose GitHub Actions
workflow appends the portal response to CSV files every day. This project reads that
archive at one **pinned revision**:

```
repository : https://github.com/PratyushBalaji/chennai-metro-ridership-tracker
commit     : 72ee5eadb6ca890bfd9900d6464a1a371566c86b
sha256     : Ridership/ChennaiMetro_Station_Ridership.csv  2630ea1b083e491c225ec49760156b01302e8bfbd4383784045576306a709190
             Ridership/ChennaiMetro_Daily_Ridership.csv     6f16712ee90aebeefa52ca49e4dc3f3c6e076368b4ab60a1783260e6adba02bc
             Ridership/ChennaiMetro_Hourly_Ridership.csv    4ae938c6c392a8bba8d1d412f30083e62e6031feb51e97774efe072c3323f19e
```

The adapter refuses a file whose digest differs (`ml/data_pipeline/cmrl.py`,
`CMRL_CHECKSUMS`), so a silent upstream rewrite cannot flow into the model.

**Rights and what is committed.** The tracker's MIT licence covers *its code*; it contains
no grant for CMRL's data, and CMRL publishes no bulk-open-data licence. Therefore this
repository commits **no operator counts**: not the upstream CSVs and not the normalized
station-day table. It commits the provenance sidecar and the trained model artifacts, and
regenerates the data with:

```bash
python3 scripts/download_cmrl_data.py     # fetch pinned revision, verify SHA-256
python3 scripts/prepare_chennai_data.py   # normalize into the canonical record contract
```

`scripts/prepare_chennai_data.py` writes `normalized_sha256` into the committed sidecar, so
a regeneration is verifiable against the artifact the model was trained on. If a user
regenerates and the digest differs, the service refuses to serve predictions and says so
(503, `checksum does not match`). Full notice: `data/licenses/CMRL-DATA-NOTICE.md`.

## 2. What the measure actually means (established, not assumed)

`daily_station_entries` is **one boarding event per journey at a station**, i.e. entries —
not entries + exits, not onboard load, not occupancy. The claim was tested rather than
inferred from a column name:

- For each of the 255 archive days, `sum(station Total)` over all line-scoped stations was
  divided by the same day's system ticket count from `allTicketCount`.
- Ratio: **mean 1.0061**, min 0.9502, max 1.2106. A value near 1.0 means each journey is
  counted once at a station; entries + exits would sit near 2.0.
- Values above 1.0 are explained by the two interchanges: Chennai Central (`SCC`) and
  Alandur (`SAL`) are each reported once per corridor, and the adapter keeps them as two
  entities and never sums them.
- Live check on 2026-10-05: stations summed 381,903 against a system ticket count of
  396,919 → 0.9622. The residual is ticket-type effects (a promotional or card revalidation
  can be counted as a ticket without a station record), which is exactly why the *station*
  field, not the system total, is used as the target.

The check is stored with the dataset (`measure_semantics_check` in the sidecar) so the next
reader can re-run it instead of trusting this page.

## 3. Record contract

`ml/data_pipeline/cmrl.py` emits only these columns; every field is either populated from
the source or absent (never invented):

| column | source | note |
|---|---|---|
| `system_id`, `city`, `mode`, `operator` | fixed by the registered family | `chennai-cmrl-metro` / Chennai / METRO / CMRL |
| `entity_id` | derived | `line-<line>-<code>`; keeps corridors separate for interchanges |
| `entity_name` | CMRL station code → published name | e.g. `Alandur (Blue Line)` |
| `entity_type` | fixed | `STATION` |
| `timestamp` | source `Date` at local midnight, `Asia/Kolkata` | day granularity aligns with the hourly family's validator |
| `demand_count` | source `Total` | integer, non-negative, no aggregation applied |
| `measure` | fixed | `daily_station_entries` |
| `source_id` | fixed | `cmrl-passenger-flow-daily` |

Rejected at load time, with an error rather than a drop: negative or fractional counts,
unparseable dates, station codes outside the pinned name map, and any duplicated
`(station, date)` pair. Payment-mode columns from the upstream file (`Paper QR`,
`Singara Chennai Card`, …) are deliberately **not** merged into the demand target.

## 4. Validation gate (Phase 15), computed

`python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro` — all ten
criteria pass. The interesting ones:

| criterion | evidence (from the run) |
|---|---|
| target values are actual observations | 10,965 rows, single measure, 0 negative, 0 fractional, 0 filled |
| time ordering is known | increasing, no duplicate days, all 43 entities |
| entity identity stable | one name per entity id; 43 entities on every one of 255 days |
| enough for a chronological split | 227 supervised target days → train 6,794 rows/158 days, validation 1,462/34, test 1,505/35 |
| missingness quantified | 0 missing entity-day cells of 10,965 expected (100.0% coverage) |
| **no future values in past features** | altering the 43 observations on 2026-10-05 left all 9,761 supervised rows at or before it **byte-identical** across 16 history/calendar columns |
| **genuine future test period exists** | source ends 2026-10-05, one day before today, so a request for a later date is a real forecast; 35 held-out days audit the projection path |
| licence rights understood | CMRL copyright recorded; policy = do not bundle, fetch and verify |
| provenance reproducible | pinned commit + two SHA-256 digests recorded |

The leakage row is a functional test, not a claim in prose. It exists because an earlier
draft of the daily feature builder aligned `lag_1` with the target day itself; that bug made
the test window report MAE 0.00 and macro-F1 1.0000. The fixed alignment is
`lag_k = y.shift(k)` on a target-indexed frame, and the probe now fails loudly if anyone
re-introduces it (`backend/tests/test_chennai_daily_forecast.py`).

## 5. Model family and measured results

`ml/training/train_daily.py` (version `2.1.0-india-daily`), 16 features: 6 calendar
(day-of-week, day-of-month, month, week-of-year, weekend, month-start) and 10 history
(`lag_1/7/14/28`, `rolling_mean_7/28`, `rolling_std_7/28`, `same_weekday_mean_4wk`,
`trend_ratio_7_28`). A target day needs 28 contiguous prior observation days, otherwise the
row is dropped — gaps delete rows instead of being bridged.

Regression, chronological partitions (validation picks the champion; the test window is
reported once and never used to pick anything):

| model | val MAE | val RMSE | test MAE | test RMSE | test R² |
|---|---|---|---|---|---|
| Seasonal naive (same weekday, last 4 weeks) | 809.92 | 1385.79 | 929.78 | 1829.02 | 0.7778 |
| Linear regression | 833.11 | 1247.38 | 922.87 | 1550.46 | 0.8403 |
| Decision tree | 798.56 | 1276.01 | 862.47 | 1548.36 | 0.8407 |
| Random forest | 714.81 | 1199.78 | 714.27 | 1362.09 | **0.8767** |
| Linear SVR | 3386.66 | 4398.96 | 3246.13 | 4255.59 | −0.2031 |
| **XGBoost (champion)** | **684.62** | **1174.48** | **711.82** | 1395.78 | 0.8706 |

XGBoost beats the seasonal-naive baseline by **23.4% MAE** on the unseen window
(711.82 vs 929.78), so the value added is real and not just a copy of last week. Linear SVR
is reported as a failure (R² < 0): no scaling/standardization pipeline rescues it on
per-entity one-hot inputs at this size, and the honest record is to keep it in the table.

Classification into frozen historical-relative bands (LOW ≤ q50 < MODERATE ≤ q80 <
HIGH ≤ q95 < SEVERE), global training cuts q50 = 5,614.5, q80 = 9,425.4, q95 = 16,106.7:

| model | val macro-F1 | test macro-F1 | test HIGH recall | test SEVERE recall |
|---|---|---|---|---|
| Baseline (most frequent) | 0.1680 | 0.1720 | 0.000 | 0.000 |
| Logistic regression | 0.7868 | 0.7479 | 0.766 | 0.578 |
| Decision tree | 0.7633 | 0.6804 | 0.859 | 0.267 |
| Random forest | 0.8086 | 0.8013 | 0.919 | 0.533 |
| SVM | 0.7745 | 0.7395 | 0.871 | 0.644 |
| **XGBoost (champion)** | **0.8304** | **0.8422** | 0.915 | 0.756 |

Because each station-line has 158 training days and the per-entity threshold needs 500
targets, band resolution falls back to `system_training_fallback` (the system-wide cuts).
That is stated in every response as `risk_method`, not hidden.

Feature importance (permutation increase in validation MAE, associational only):
`same_weekday_mean_4wk` 1568.1 ≫ `lag_1` 354.1 > `rolling_mean_7` 258.8 > `day_of_week`
163.9 > `lag_7` 154.5. Weekly shape dominates, which is what a two-month window with no
holidays in common can support.

## 6. How accurate is a *future* forecast — measured, not extrapolated

Two numbers are published in
`backend/models/chennai-cmrl-metro/evaluation_replay.json`, and they mean different things:

| evaluation | rows | MAE | RMSE | R² | sMAPE |
|---|---|---|---|---|---|
| one-step-ahead replay on the held-out window (real history up to T−1) | 1,505 | 711.82 | 1395.78 | 0.8706 | 17.20% |
| **recursive projection** from the training cutoff, re-feeding its own forecasts, 2026-07-29 → 2026-10-05 | 2,967 | **902.29** | 1402.51 | 0.8691 | 16.17% |

The recursive figure is the one to quote for the future-forecast feature, because it uses
the same code path the API uses: no observation after the cutoff enters the features.
Error grows with horizon — first 7 projected days MAE 888.9, last 7 days MAE 1,330.9 — and
the API refuses projections beyond 60 days.

## 7. What this family cannot tell you

- **Nothing about the hour.** Daily totals carry no information about when inside the day
  the passengers arrive. `GET /api/heatmap` returns 409 for this system on purpose;
  `GET /api/weekly-pattern` gives the day-of-week profile that *is* supported.
- **No annual or festival seasonality.** The archive starts 2026-01-24; the model cannot
  know Pongal, Diwali or summer effects, and month/week-of-year features are near-collinear
  with the trend inside this window.
- **Ticket-derived counts, not occupancy or safety.** A station at SEVERE may be a
  comfortably operating interchange; the band is relative to that station's own history.
- **Roughly one day of publication lag.** `GET /api/source-gap` reports how far the archive
  sits behind today; the collector in `scripts/collect_transit_observations.py` is the way
  to close that gap from your own runs.
- **Upstream fragility.** The API is undocumented and can change shape; the adapter fails
  loudly on unknown station codes or schema drift instead of guessing.

## 8. Reproduce end to end

```bash
python3 scripts/download_cmrl_data.py
python3 scripts/prepare_chennai_data.py
python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro
python3 scripts/train_chennai_models.py --target-date 2026-10-07     # ~2 min, writes artifacts
python3 -m pytest backend/tests/test_chennai_daily_forecast.py -q    # 16 tests, no network
```

Example request and answer (values from the current artifacts):

```bash
curl -s localhost:8000/api/predict -H 'content-type: application/json' -d \
 '{"system_id":"chennai-cmrl-metro","station_id":"line-01-sal","target_date":"2026-10-12"}'
```

returns `predicted_entries ≈ 6633.97`, `relative_demand_band: MODERATE`,
`forecast_horizon_days: 7`, `forecast_kind: post_frontier_projection`,
`is_model_forecast: true`, `training_cutoff: 2026-07-28`, plus the classifier cross-check,
the counterfactual explanation and the quietest/busiest neighbouring days.
