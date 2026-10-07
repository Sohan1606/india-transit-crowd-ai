# Mumbai Local (Central Railway) — supplied dataset, audited

**Status: AUDITED and integrated as a labelled demonstration family.** The file was published on
`origin/feature/future-demand-dataset` (single commit `01f8be4`, stored through Git LFS) and materialised
locally with `scripts/fetch_lfs_object.py`; every figure below was measured from those bytes on
2026-10-06, not carried over from the request that supplied them.

| Fact | Measured value |
| --- | --- |
| File | `data/development/synthetic/mumbai_local_all_central_stations_2026_synthetic-1.csv` |
| Size / sha256 | 78,945,924 bytes / `f54eb331…` — equal to the LFS pointer's oid |
| Rows × columns | 464,280 data rows × 26 columns (464,281 lines including the header) |
| Columns | `Record_ID, Date, Time, Day_of_Week, Day_Number, Is_Weekend, Month, Season, Holiday_Name, Is_Indian_Holiday, Source_Station, Line, Station_Position, Stations_On_Route, Peak_Period, Peak_Direction, Rainfall_mm, Temperature_C, Train_Capacity, Estimated_Passenger_Count, Capacity_Utilization_Pct, Crowd_Density, Target_Next_Hour_Passengers, Target_Next_Hour_Crowd, Data_Type` |
| Declared provenance | `Data_Type = Synthetic` on every row — the pipeline reads that and classifies the family `synthetic_development` |
| Calendar | 2026-01-01 … 2026-12-31, 365 distinct dates, `Time` = 24 hourly labels (`00:00 … 23:00`) |
| Corridors | exactly 3: `Central Main` (26 stations on route), `Central Kasara Branch` (15), `Central Karjat/Khopoli Branch` (12), from `Line` × `Stations_On_Route` |
| Stations | 51 distinct `Source_Station` values; 53 distinct (corridor, station) pairs, `Station_Position` 0…25 |
| Row arithmetic | 53 series × 365 days × 24 hours = 464,280 — the file is a complete grid, no gaps, no duplicates |
| Demand measure | `Estimated_Passenger_Count`; `Train_Capacity` is the single constant 8200 in every row |

## What this dataset is, and what it is not

It is a **synthetic hourly demand table** for the Central corridor of the Mumbai suburban network,
supplied for development. It contains no coordinates, no timetable, no headways, no GTFS, no
origin-destination matrix and no occupancy measurement. The pipeline therefore forecasts one thing: the
passenger count of the next hour on a given corridor-and-station series. `Capacity_Utilization_Pct`,
`Crowd_Density` and `Train_Capacity` are inputs the profiler may consider; none of them is presented as a
capacity, boarding or safety result, and the API has no notion of "how full is this train".

Nothing about this family is live. The most recent row usable for fitting is `2026-10-06 23:00` IST (see the
future guard below), so every answer for a later hour is a model projection, labelled as one.

## Forecast target policy — the supplied target column was rejected

`Target_Next_Hour_Passengers` looks like next-hour demand and is not. Measured against the chronological
series of the file itself, grouped the way the data is actually organised (`Line` + `Source_Station`,
ordered by `Date` + `Time`):

- exact agreement after the shift: **2.74 %** of 464,227 comparable rows (median absolute difference 677 passengers);
- no other offset works either: t+2 h 2.22 %, t+3 h 1.70 %, t+6 h 0.73 %, t+12 h 0.77 %, t+24 h 2.10 %;
- the two columns are correlated (0.837), which is exactly how a plausible-but-wrong label looks;
- a concrete row, `CSMT / Central Main`, 2026-01-01: demand at 00:00 is 2842, at 01:00 is 2227 — and the
  "next hour" target recorded on the 00:00 row says 2151. Neither.

`scripts/audit_demand_dataset.py` reaches the same verdict on its own — `INCONSISTENT`, best alignment
`entity+Month@+1`, 2.75 % exact — and `Target_Next_Hour_Crowd` is `UNVERIFIABLE` because it holds band
labels (`Low/Moderate/High/Extreme`), not numbers. **Both columns are ignored as ground truth.** The
supervised target is derived inside the pipeline from `Estimated_Passenger_Count` shifted one hour within
each series, which is the only definition this file supports. That policy is generic: the profiler now
excludes any label-shaped column (`Target_*`, `Next_*`, `Label_*`) from being the demand *series*
whenever the file also carries a plain series column, so no future dataset can smuggle a precomputed label
in through a name.

## How the family is built

    sh scripts/run_mumbai_registration.sh

That script runs the shared, adaptive registration path with the flags this file's shape requires:

- `--timestamp-columns Date,Time` — the file splits the moment across two columns; the joined value is
  what the grid, the period and the ordering are measured from (measured period 3,600 s, 100 % of gaps).
  This is a reading step for any file of this shape, not a Mumbai rule.
- `--entity-key-columns Line,Source_Station` — an interchange station appears on up to three corridors, so
  the station alone is not a series. 53 composite series are produced and never summed together.
- `--entity-attribute-columns Line,Source_Station,Station_Position,Peak_Direction` plus
  `--entity-hierarchy-columns Line,Source_Station` — the API publishes those values per entity, and the
  client builds a corridor-then-station cascade from them. No station list exists in the front end.
- `--exclude-unobserved-future` — rows dated on or after the runner's current IST date (`2026-10-07` at build time) are dropped before anything
  else happens, because training on days that have not happened yet would make every "future forecast"
  claim false. It removed 109,392 of 464,280 rows and left 354,888 = 53 × 279 × 24, so the
  series runs through `2026-10-06 23:00` IST. The exclusion is
  recorded in the sidecar as `rows_excluded_as_unobserved_future`.
- `--dataset-class synthetic_development --serve-as demo` — see the serving section.

Gate result for this family: **9 of 10 criteria pass**, the only failure being
`target_values_are_actual_observations` — the file does not contain observations, and saying so is the
point of the criterion. `provenance_is_reproducible` passes because the run records the source branch,
the commit `01f8be4`, the source sha256 and the normalized sha256.

## Model results (demonstration data — not evidence about passengers)

Fitted on a bounded window because a full year of hourly rows for 53 series exceeds what this runner can
hold: `--fit-window-days 120`, i.e. 152,640 of 354,888 rows, the 120 days ending 2026-10-06. The window is
recorded inside the model report (`fit_window`) beside the numbers it produced, and the served history
stays complete.

| Model | Test MAE | Test RMSE | Test R² |
| --- | --- | --- | --- |
| **Random Forest (champion; validation MAE 392.43, ranked 1)** | **388.91** | **539.25** | **0.97341** |
| Seasonal Naive (the reference a model must beat) | 1063.54 | 1587.98 | 0.76938 |

The champion's test partition is 21,571 rows spanning 2026-09-20 01:00 to 2026-10-06 23:00 (407 distinct
target hours), i.e. the last 15 % of the fitted window and never used to select it. Beating Seasonal Naive
by 2.7× on MAE is the sentence worth quoting; the R² on its own would flatter synthetic data.

Risk bands: champion classifier XGBoost — accuracy 0.8766, macro-F1 0.6614, macro ROC-AUC 0.966. Per band:
`LOW` F1 0.968, `MODERATE` 0.844, `HIGH` 0.676, `SEVERE` 0.157 (recall 0.101 on 346 rows). That
`SEVERE` number is the honest weak point of a relative-band classifier on a smooth synthetic year, and it is
reported rather than smoothed over. Thresholds are historical-relative q50/q80/q95 fitted on the
chronological training targets only, per entity (53) then system then global. Recursive one-hour projection
is capped at 336 hours from the frontier, and the served attributes for each series (`/api/stations`) carry
`Line`, `Source_Station`, `Station_Position` and `Peak_Direction` under the canonical id, e.g.
`central-main-csmt`.

The R² is high **because synthetic data is smooth by construction** — it is not evidence that a real
suburban platform is predictable at that accuracy, and it is never presented as such.

## Serving mode

`data/registry/model_families.json` records `served_as: demo` for `mumbai-local-central`. The family is
visible in `/api/systems`, answerable through `/api/predict`, and every response carries
`data_class: "synthetic_development"` plus a disclosure beginning `SYNTHETIC DEMONSTRATION FORECAST`, with
`metrics_are_demonstration_only: true`. The front end shows the demo banner and flags the family in the
systems list. It is never described as live, observed or operator-reported ridership anywhere in the
product, and the same code path would serve a genuine observed Mumbai file without any change other than
`--dataset-class observed --serve-as production` and a passing gate.

## Regenerating the inputs

The raw CSVs are not in the ZIP and are not redistributed. From a fresh clone of the branch:

    git lfs pull                       # or:
    python3 scripts/fetch_lfs_object.py --all --under data/development
    sh scripts/run_mumbai_registration.sh

`scripts/fetch_lfs_object.py` verifies each object against the pointer's size and sha256 before it
replaces the pointer file, and reports a mismatch instead of writing anything.

## What a packaged checkout actually serves from

The registry entry for this family points at a compressed inference copy committed in the repository:

| file | rows | bytes | checksum |
| --- | --- | --- | --- |
| `data/inference/mumbai-local-central_demand_timeseries.csv.gz` | 354,888 | 2,089,076 | `normalized_gz_sha256` = `f6c626ca45b85fa9…` in the sidecar |
| `data/inference/mumbai-local-central_demand_timeseries.metadata.json` | sidecar + entity attributes + route context | 25,033 | — |

It does **not** point at `data/development/…csv`: that directory is git-ignored because it holds a
78,945,924-byte source file this project is not licensed to redistribute, and an entry that resolves only in
the workspace that produced it is how a "works on my machine" deployment is born. `training_dataset_relative_path`
in the registry still names the development copy, so the row-level provenance of the fit stays auditable.

A fresh clone can therefore serve this family without the source CSV. Rebuilding the development copy (needed
before `--train`) is two commands: `python3 scripts/fetch_lfs_object.py --all --under data/development`
(checksum-verified against the LFS pointers in `.gitattributes`), then `sh scripts/run_mumbai_registration.sh`.

## How a rider's choice is built

The corridor list, the stations inside each corridor, their order and the two ends are derived at registration
from this file's own `Station_Position` values inside `Line` - 3 corridors,
53 stations, 53 TOWARDS choice sets. No React file repeats a
route table, so the UI cannot disagree with the data.

`MUMBAI LOCAL → CENTRAL RAILWAY → CORRIDOR → FROM → TOWARDS → DATE → TIME → PREDICT`

TOWARDS is journey context. This file measures one series per corridor+station - there are no
destination-specific counts in it - so the selected direction is never sent as a filter and no directional
number is invented; `/api/metadata` says exactly that in `route_context.towards_kind`, and the client prints it.
A terminus offers one direction (Kalyan is `Towards CSMT` only), never itself, because the options are the
endpoints of the corridor the station sits on.

## API shape (nothing accepted and ignored)

`POST /api/predict` takes `system_id`, `station_id`, `target_date`, `target_hour` and forbids extra keys
(`StrictRequest`, `extra="forbid"`). `station_id` is the composite slug of the published levels
(`central-main-kalyan`); `/api/metadata` maps corridor → station → entity id, and an unknown id is refused
while naming the published values that do exist. There is deliberately no `corridor_id` or `direction`
parameter: half-implemented request fields are worse than none.

Hour: this is a complete 24-hour family, so `supported_time_slots` is not restricted and every hour 0-23 is
answerable. A date past the data frontier (2026-10-06T23:00 here) is answered
by persisted-model inference and carries `forecast_kind = "post_snapshot_projection"` with `absolute_error = null`;
an observed date is answered with `forecast_kind = "historical_replay"` plus Actual, Prediction and Error together.
Neither path retrains, cross-validates or rebuilds the dataset - `scripts/benchmark_inference.py` measures the
artifact's modification time across all requests and reports it unchanged.

## Fitting and serving this family on your own hardware

`scripts/windows_gpu_training.ps1` is the full Windows sequence (venv on Python 3.13, GPU requirements, LFS
materialisation, `scripts/check_gpu.py` preflight, both families, latency measurement). GPU selection is the
environment only - `TRANSITCROWD_XGB_DEVICE=cuda` - which the two trainers read for their XGBoost candidates;
no Python file needs editing. A test (`test_the_two_training_entry_points_agree_on_flags`) keeps that script and
`scripts/run_mumbai_registration.sh` using the same flags.

The bundle this workspace produced (`backend/models/mumbai-local-central/transitcrowd.joblib`, 44,751,480 bytes)
is **development evidence from a CPU-only sandbox**, not the intended production model: the joblib files are
git-ignored and excluded from the package so nobody mistakes them for one. `model_report.json` and
`station_analytics.json` are committed, because the audit and the metrics are the part worth reviewing.
