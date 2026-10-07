# Mumbai Metro — supplied demand table and station reference, audited

**Status: AUDITED and integrated as a labelled demonstration family.** Both files came from
`origin/feature/future-demand-dataset` (commit `01f8be4`, Git LFS) and were materialised with
`scripts/fetch_lfs_object.py`, which compares each object against the pointer's size and sha256 before
replacing it. Every figure below is measured from those bytes; none is carried over from the request that
supplied them.

## The demand table

| Fact | Measured value |
| --- | --- |
| File | `data/development/synthetic/Mumbai_Metro_Crowd_Prediction_2026.csv` |
| Size / sha256 | 148,837,459 bytes / `8d9db473…`, equal to the LFS pointer's oid |
| Rows × columns | 683,280 data rows × 27 columns, with a UTF-8 BOM on the first header (handled by `encoding="utf-8-sig"`) |
| Columns | `Record_ID, Date, Time, Day_of_Week, Is_Weekend, Holiday_Name, Is_Indian_Holiday, Month, Metro_Line, Line_Name, Operational_Status, Source_Station, Station_Position, Stations_On_Line, Destination_Station, Travel_Direction, Peak_Period, Peak_Destination, Rainfall_mm, Temperature_C, Train_Capacity, Estimated_Passenger_Count, Capacity_Utilization_Pct, Crowd_Density, Target_Next_Hour_Passengers, Target_Next_Hour_Crowd, Data_Type` |
| Declared provenance | `Data_Type = Synthetic` on every row |
| Calendar | 2026-01-01 … 2026-12-31, 365 dates; `Time` has exactly **six** values: 08:00, 09:00, 13:00, 16:00, 18:00, 20:00 |
| Series | 312 distinct (line, origin, destination) triples × 6 slots = 1,872 series; 1,872 × 365 days = 683,280, an exact grid with zero duplicate rows |
| Network spread | 12 `Metro_Line` values, 164 distinct stations as origins and 22 as destinations, `Train_Capacity` the constant 2500, `Crowd_Density` only ever `Low` or `Moderate` |
| Demand measure | `Estimated_Passenger_Count` |

## The station reference, and what the two files agree on

`Mumbai_Metro_Station_Reference_2026.csv` — 14,950 bytes, 168 rows, sha256 recorded in the sidecar — holds
`Metro_Line, Line_Name, Operational_Status, Station_Position, Stations_On_Line, Station,
Morning_Peak_Destination, Evening_Peak_Destination`. That is the whole contract it can honour: 12 lines,
164 stations, per-line positions 1…`Stations_On_Line`, and the peak-direction endpoint per station. It has
no coordinates, no headways and no timetable, so nothing in this project draws a route map or claims a
train frequency for these lines.

Consistency between the two files was checked rather than assumed:

- every distinct `(line, source, destination)` triple in the demand table resolves to two stations that
  exist on that line in the reference, and no series has source equal to destination: **0 inconsistencies**;
- `Travel_Direction` in the demand table is literally `"Source -> Destination"` on **every** row, so the
  column is a label of the ordered pair, not an independent fact;
- `Operational_Status` is a per-line-state field with six values. Across the 168 reference rows: Operational
  69, Under Construction 60, Under Construction / Partial 20, Operational / Phase-wise 8, Under
  Development 6, Planned / Under Development 5. Most of this network is not open, and the API publishes the
  status per entity so the interface can say so next to any forecast on those lines. The demand table itself
  contains rows for those lines — the data is what it is — but a forecast about an under-construction line
  is a model projection on synthetic input, never a service statement.

## Granularity: a slot grid, not an hourly series

Six published slots a day is not a 24-value hourly series, and pretending otherwise would mean inventing
the hours between them. The family is therefore registered as **day granularity with the slot as part of the
series identity** (`--entity-key-columns Metro_Line,Source_Station,Destination_Station,Time`): each series is
one station pair at one clock time, observed once per day, and the supervised target is the same slot of a
later day. Consequences, all enforced by the pipeline rather than by prose:

- a request for `07:00` cannot be answered, because no such series exists. The discovery endpoint exposes
  the family's published slots (`supported_time_slots`, taken from the file's own `Time` values), the client
  can only select among them, and an unknown final level in an entity id is refused with the list of values
  that do exist;
- nothing is interpolated, summed across slots or averaged into a "per-hour" figure — the 24-value
  interpolation the reference material invited is exactly what this family does not do;
- the granularity is recorded in the registry entry (`day`) and reported by `/api/metadata` and
  `/api/systems`, so no caller has to know that Mumbai is special.

## Forecast target policy — both supplied target columns were rejected

`Target_Next_Hour_Passengers` was tested against the chronological series in the file itself, grouped by
(line, origin, destination) and ordered by date then slot:

- as a *next-slot* label: **1.99 %** exact agreement at the best alignment the audit tries (`INCONSISTENT`);
- as a *same-slot-next-day* label, which is the semantics this grid supports: **1.09 %** exact agreement,
  correlation 0.794;
- `Target_Next_Hour_Crowd` holds two band labels (`Low`, `Moderate`) and is not numeric for most rows:
  `UNVERIFIABLE`.

So both are ignored as ground truth. The supervised target is derived from `Estimated_Passenger_Count`
shifted within each series, which is the only definition the file's own chronology supports. The audit
output at `data/development/mumbai-metro_validation_gate.json` and the `/tmp`-style JSON report from
`scripts/audit_demand_dataset.py` are the reproducible evidence for these numbers.

## How the family is built

    sh scripts/run_mumbai_registration.sh

Beyond the slot-aware entity key above, the flags that matter are:

- `--timestamp-columns Date` — the date alone carries the moment, because the slot lives in the key;
- `--entity-attribute-columns Metro_Line,Line_Name,Operational_Status,Source_Station,Destination_Station,Time,Stations_On_Line,Travel_Direction`
  and `--entity-hierarchy-columns Metro_Line,Source_Station,Destination_Station,Time` — written into the
  sidecar keyed by the canonical (slugged) entity id, published per entity by `/api/stations`, and rendered
  by the client as a four-level cascade. There is no Mumbai list in the front end; the cascade *is* the
  metadata;
- `--exclude-unobserved-future` — rows on or after 2026-10-06 are dropped before anything else, leaving
  522,288 usable rows (1,872 series × 279 days; 160,992 rows dated on or after the build date were dropped,
  an exact product at both ends). The count is recorded in the sidecar as
  `rows_excluded_as_unobserved_future`;
- `--dataset-class synthetic_development --serve-as demo` — see the serving section;
- `--fit-window-days 150` — models are fitted on the most recent 150 days (280,800 of 522,288 rows) while
  the complete stored history remains available as observations. This is a memory-and-runtime bound of the
  runner, recorded inside the model report as `fit_window`, and it is stated beside every metric rather than
  hidden.

Gate result: **9 of 10 criteria pass**, the single failure being
`target_values_are_actual_observations` — the file's values are not observations, which is precisely what
its `Data_Type` column says. All the structural criteria pass: exact grid, complete coverage, known
chronology, no future values in past features, entity integrity, licence/redistribution stance recorded,
reproducible provenance (branch commit `01f8be4`, source and normalized sha256).

## Training notes this file forced into shared code

Two generic changes came from trying to train this family, and both are now in the pipeline for anyone else
who gets here:

1. **Entity encoding scales with the family.** A one-hot block over 1,872 entity ids densified into a
   196,560 × 1,872 float64 matrix — a 2.74 GiB allocation, and with `max_features=0.7` the forest then had
   to scan those columns at every split. Above 128 entities the day trainer uses an ordinal identity
   instead, recorded in the report as `entity_encoding`, so the entity remains distinguishable without
   thousands of near-zero columns. Below the threshold nothing changes, which is why Chennai's 43 entities
   are unaffected.
2. **The horizon scan samples entities.** Error growth with horizon is a property of the model and the
   calendar, not of each of 1,872 series, so the scan takes 80 entities evenly spaced across the sorted
   set and reports `entities_total` / `entities_sampled` next to the curve it produced.

## Model results (demonstration data — not evidence about passengers)

Fitted on 280,800 of 522,288 usable rows (150 days,
2026-05-09 → 2026-10-05), recorded in the report as
`fit_window`; the served history stays complete. Entity identity for this family is encoded as
**ordinal** because it has 1,872 series — see the training notes above — and that
choice is written into the report beside the metrics.

| Model | Test MAE | Test RMSE | Test R² |
| --- | --- | --- | --- |
| **Svr (champion)** | **33.23** | 59.84 | 0.94342 |
| Seasonal Naive (the reference) | 41.91 | 75.16 | 0.91076 |

Risk bands: champion classifier Random Forest — accuracy 0.8504, macro-F1 0.8300.

Horizon governance: the report records 18 usable day(s) of 18 measured (method: recursive multi-day-ahead projection re-feeding its own forecasts, evaluated on the vali); beyond the usable horizon the service refuses rather than extrapolating. The test partition, the per-model validation ranking that selected the champion, and the
limitations text are in `backend/models/mumbai-metro/model_report.json`.

The band-to-band error here is wider than the daily metro figures Chennai produces because a station-pair
slot has 150 observations in the fitted window instead of thousands; that is a property of this file's
shape, and it is why the family is labelled a demonstration rather than a benchmark.

## Serving mode

`data/registry/model_families.json` records `mumbai-metro` with `served_as: demo`. It appears in
`/api/systems` with `granularity: "day"` and `data_class: "synthetic_development"`; `/api/metadata` adds
`entity_hierarchy`, `supported_time_slots` (the six published slots), `supported_time_note` and
`metrics_are_demonstration_only: true`; every prediction carries a disclosure beginning `SYNTHETIC
DEMONSTRATION FORECAST`. The numbers are never presented as live or observed ridership, and the family
would be promoted by registering a genuine observed file — not by changing this code.

## Regenerating the inputs

    git lfs pull                                              # or:
    python3 scripts/fetch_lfs_object.py --all --under data/development
    sh scripts/run_mumbai_registration.sh

The raw CSVs are not redistributed in the ZIP and not committed as bytes (the two large ones are LFS
pointers on that branch); the station reference is small but comes from the same private source, so the
fetch step above restores all three and verifies each checksum.

## What a packaged checkout actually serves from

| file | rows | bytes |
| --- | --- | --- |
| `data/inference/mumbai-metro_demand_timeseries.csv.gz` | 522,288 | 2,710,328 |
| `data/inference/mumbai-metro_demand_timeseries.metadata.json` | sidecar, 1872 entity attribute sets | 923,629 |

The registry points at that gzip, not at the 148,837,459-byte source CSV under `data/development/` (git-ignored,
not redistributable): `python3 scripts/fetch_lfs_object.py --all --under data/development` then
`sh scripts/run_mumbai_registration.sh` rebuilds everything, on any machine. The sidecar records
`normalized_gz_sha256` = `24d318eba8feeb05…` and the service verifies whichever container it
actually loads, so a packaged dataset cannot drift from the rows the model was fitted on.

## How a rider's choice is built

`MUMBAI METRO → LINE → FROM → TOWARDS → TIME SLOT → DATE → PREDICT`

Those four levels are this file's own entity key - `Metro_Line`, `Source_Station`, `Destination_Station`, `Time` -
with the display labels set at registration (`--entity-hierarchy-labels "Line,From,Towards,Time slot"`), so the
UI never shows a raw `Travel_Direction` string. TOWARDS here is a real measured dimension: each series *is* a
source→destination pair, unlike the suburban file. A request naming a station and a slot that the source does not
publish is refused with the published values named - `Time` holds exactly
08:00, 09:00, 13:00, 16:00, 18:00, 20:00 and nothing between them, so no
interpolation is offered. Day granularity: `target_hour` is not accepted; the slot lives in the series identity.

## Latency measured in this sandbox (2026-10-07, 1 vCPU, 1984 MB RAM, CPU-only XGBoost)

```
python3 scripts/benchmark_inference.py --system-id mumbai-metro --requests 24
[load]    dataset read + bundle load + integrity checks: 3.97 s   (once per process)
[latency] 24 requests (16 future, 8 historical): p50 1584.4 ms, p95 3249.9 ms, max 3868.0 ms
[no-refit] artifact mtime unchanged across all requests: True
```

Startup is a few seconds and per-request work is under four seconds even for a three-day projection over
1,872 series; nothing in that path trains a model. Numbers are for this container, not a
promise about a deploy - the same script measures yours.

## Fitting on your own hardware

`scripts/windows_gpu_training.ps1` (Windows/PowerShell) or `scripts/run_mumbai_registration.sh` (bash) run the
identical command; `TRANSITCROWD_XGB_DEVICE=cuda` selects the GPU after `python3 scripts/check_gpu.py` proves the
wheel can use it. The joblib in `backend/models/mumbai-metro/` is CPU-fit development evidence and is not committed.
