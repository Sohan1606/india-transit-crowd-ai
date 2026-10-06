# Mumbai Suburban Railway — MRVC / Wilbur Smith survey extract

Status: **rejected as a future-prediction dataset by the Phase-15 gate; accepted as a
labelled historical baseline.** This page records exactly what the source document
contains, what was extracted, what was refused, and what would have to happen for Mumbai to
join the prediction families.

## 1. The source document

| | |
|---|---|
| Title | *Mumbai Sub-urban Rail Passenger Surveys and Analysis — Executive Summary* |
| Prepared for | Mumbai Railway Vikas Corporation Ltd (MRVC) |
| Prepared by | Wilbur Smith Associates |
| Pages | 38 |
| PDF creation / modification | 2013-08-16 / 2013-09-04 |
| SHA-256 of the file used | `26f7d4ea4fb5ba27d283d9a1701815fcb39094782a370cedfc1427375993f646` |
| Licence / reuse statement | **none printed in the executive summary** |
| Committed in this repository | **no** — the PDF is not redistributed; re-download it from MRVC before publishing any figure |

Fieldwork is from **2011-12**, with one later section (Virar–Dahanu Road) from **June 2013**.
Everything else in the document is either narrative or model output.

## 2. Extraction result

```
python3 scripts/extract_mumbai_pdf_surveys.py            # ~1 second, needs the PDF locally
```

* `data/research/mumbai_suburban_rail_pdf_observed.csv` — **249** records, one row per
  measure/entity/interval, every row carrying `source_table` and `source_page`.
  SHA-256 `ad7913f919e4c23cc3fd06c1a120b8592a0528ec92e8ce69bda8de8ec3f9edcb`.
* `data/research/mumbai_suburban_rail_pdf_observed.metadata.json` — provenance, survey
  schedule, time depth, gate result, per-criterion evidence.
* `data/research/mumbai_suburban_rail_MODELLED_od_forecast.csv` — the quarantined Table E-13
  forecast block (4 rows), see §5.

| measure | rows | directly counted or derived | source |
|---|---|---|---|
| `passengers_travelling_in_peak_direction` | 50 | derived (two-stage expansion) | Tables E-4…E-8 |
| `passengers_travelling_peak_period_total` | 10 | derived, printed per-hour totals | Tables E-4…E-8 |
| `station_entries_plus_exits_14h` | 47 | **counted at entry/exit points** | Tables E-9…E-12, E-14…E-20 |
| `station_entries_plus_exits_hourly_share` | 56 | counted, published as % of the 14-hour total | Tables E-15, E-17, E-19, E-21 |
| `peak_hour_section_load` | 18 | counted | Tables E-9…E-12 |
| `peak_hour_passengers_travelling` | 12 | derived | Figures E-4…E-9 narrative |
| `peak_hour_passengers_per_train` | 10 | derived against rated rake capacity | narrative iv |
| `queue_length_at_ticket_counters` | 46 | **counted, and the only dated rows** | Table E-22 |

`observation_type` is one of `directly_observed`, `counted_at_entry_exit_points`,
`derived_from_sample_survey`, `derived_from_section_load` — a per-row statement of how far
each number sits from a person with a clicker.

## 3. Time depth, stated plainly (Phase 2)

* **5** distinct survey periods; **5** distinct calendar dates in the whole extract:
  `2011-12-08`, `2012-02-11`, `2012-11-21`, `2013-06-17`, `2013-06-18`.
* Each line's numbers describe **one typical weekday**. There is no repeat measurement of a
  station, so there is no series: no lag, no week-over-week change, no error estimate.
* 50 station names across 4 line rosters, 8 line labels, 42 interval labels, 08:00–22:00 for
  station tables and 07:00–11:30 / 16:00–20:30 for the in-train peak surveys.
* Only `queue_length_at_ticket_counters` has a real timestamp (Table E-22 prints survey
  dates). Every other row is tied to a *period*, not a date, and the extractor does not
  invent one.

Survey schedule as printed in Table E-1 (p. 7), including its own gaps and ambiguities:

| survey | period | what it covered | exclusions printed in the report |
|---|---|---|---|
| Commuter Feedback | 2011-11-22 → 2011-12-06 | 25,000 sampled interviews, 08:00–22:00 | started after the Diwali vacation; **no surveys 23/12/2011–02/01/2012** |
| Passenger Entry/Exit count | 2011-12-08 → 2012-02-10 | all authorised **and unauthorised** points of 37 selected stations | Table E-1 prints the end date as `10/2/2012` |
| Alighting Distribution | *(blank in Table E-1)* | selected platforms, Up/Down, slow/fast, coach-type detail | start/end cell is empty in the source; left NULL here |
| In-Train Boarding/Alighting | 2012-02-11 → 2012-03-15 | **310** of ~2,813 daily services | Section III says 300 services, Table E-1 says 310; 310 used and the conflict recorded |
| Virar–Dhanu Road | 2013-06-17 → 2013-06-18 | inspection/mapping, entry-exit counts, FoB counts at 8 stations | partly **secondary data provided by MRVC**, limited surveys |

Independent internal check that the date handling is right: Table E-22 prints queue samples
dated `21/11/2012` and `18/06/2013`; the latter falls inside the stated 17–18/06/2013
Virar–Dahanu window. Two separate tables agreeing on a date is the only cross-date
verification this document permits.

## 4. Methodology notes that change how a number must be read

1. **Expansion factors are applied twice** (Tables E-2, E-3): counted coach samples → whole
   train, then sampled services → all peak services. So Tables E-4…E-8 are derived
   estimates of a weekday, not raw counts, and are typed as such.
2. **Hourly train counts are not additive.** "No. of trains running in the given one hour"
   counts a train once per hour it touches: a service running 07:30–08:15 appears in both
   buckets. Summing E-5's hourly services gives 274 against the printed peak total of 153.
   The extractor therefore **never** checks `Σ hourly services = printed total` — it verifies
   the *passenger* totals instead (e.g. Western Line Up 1,124,170 over 153 services).
3. **Bracketed station counts** in Tables E-14/16/18/20 are trains stopping at the station
   between 08:00 and 22:00; kept as the separate field `trains_stopping_8_to_22`, never as a
   demand value.
4. **Share rows are percentages of a 14-hour total** (E-15/17/19/21), so they are stored as
   `station_entries_plus_exits_hourly_share` with `share_percent`, and the 14-hour totals are
   kept as their own measure. Combining the two into one "hourly passengers" column would be
   an interpolation, which the brief forbids.
5. **Station roster ambiguity is documented, not resolved.** Table E-1 says 37 selected
   stations; the roster on pp. 5–6 names 46. Both statements are in the metadata; the
   extractor keeps whichever names the tables actually print (50 appear).
6. **Crowding ratios are against rated capacity**, not comfort: 1,800 passengers for a
   9-car rake, 3,522 for a 12-car rake. Worst printed cases: Western fast 5,560 and slow
   4,182 per train; Central Down 4,498 / 5,446.
7. **Line-level hourly shape** (system totals, p. 12) sums to 2,291,376 morning passengers
   over 349 Up services and 2,242,948 over 333 Down services, with peaks of ≈632,000
   (08:30–09:30 Up) and ≈587,000 (18:00–19:00 Down). These are the only numbers in the
   document that describe the whole network in one hour, and they are a *cross-section*.
8. Column alignment, not judgement, did most of the work: the PDF text layer emits tables as
   whitespace-separated columns with headers repeated mid-table (e.g. `Total Services 64 37
   101` sits inside E-7's Up block), so the parser collapses whitespace per page, bounds each
   block by the next `Table E- n` header or the table's own `Note:` line, and infers each
   row's direction from the row's own hour (≤ 11 → Up). A page holding two tables is the
   reason a block must end early.

## 5. The modelled forecasts are quarantined (Phase 10)

Table E-13 (p. 25) is the document's 2012/2016/2021/2031 demand forecast. It is stored
**separately**, with `classification = "HISTORICAL STUDY MODEL OUTPUT"` and
`eligible_as_supervised_label = False` on every row:

| year | Western | Central | Harbour | Total (lakh daily trips) |
|---|---|---|---|---|
| 2012 | 38.15 | 26.34 | 18.76 | 83.25 |
| 2016 | 41.19 | 29.86 | 24.60 | 95.65 |
| 2021 | 44.65 | 33.85 | 30.82 | 109.32 |
| 2031 | 51.14 | 40.84 | 42.67 | 134.65 |

Why it can never be a training target here:

* The 2012 "value" is the model's own base year, i.e. the surveyed weekday re-expressed by a
  travel-demand model — using it as ground truth is circular.
* 2016 is printed as an **interpolation** because the report states no model forecast existed
  for it.
* 2021 and 2031 are projections of peak-hour OD matrices expanded to a day, with off-peak
  demand **assumed** at 15% — the report says so.
* Training `2012 → 2016 → 2021 → 2031` and then claiming to predict the future would be a
  model imitating a model, unverifiable by construction.

Their permitted use: a labelled benchmark for plausibility ("does a 2013 strategic forecast
of 109 lakh daily trips line up with today's operator aggregates?"). A repository-wide test
(`test_no_training_or_feature_code_reads_the_quarantine_file`) fails if any file under `ml/`
or `scripts/` other than the extractor ever references that CSV.

## 6. Gate result (Phase 15)

`eligible_for_primary_future_prediction_model: false`, six criteria failed, each with
written evidence rather than a flag:

| failed criterion | evidence |
|---|---|
| `target_values_are_actual_observations` | most values are two-stage survey expansions; only entry/exit and queue counts are directly counted, and those are one-day aggregates |
| `time_ordering_is_known` | one surveyed weekday per line; no ordering across days exists |
| `missingness_quantified` | the report never says how many of the network's stations were excluded, nor per-station survey-day counts |
| `license_usage_rights_understood` | no licence or reuse statement is printed |
| `sufficient_observations_for_time_series_split` | 249 rows form 5 period snapshots, not a series; no train/validation/test split by time is possible |
| `genuine_future_test_period_exists` | a 2013 study has no observation after any cut-off; a "forecast" would be pure extrapolation from one weekday, unverifiable |

Four criteria pass (granularity known, entity identity stable enough for cross-sections,
provenance documented per row, no future values used as past features). The proposed target
is recorded as `null` with the reason, so nobody later "finds" a target in this file.

Contrast with the two accepted families: Bengaluru 92,280 station-**hours** over 61 days,
Chennai 10,965 station-**days** over 255 consecutive days. Both can be split by time and
scored on unseen days. Mumbai's survey cannot, and saying so is the finding.

## 7. Newer observed Mumbai data: what was searched and what exists

Only one genuinely longitudinal *observed* Mumbai transit series was found in this research
pass, and it is not station-level: the MMRDA/NDSAP daily ridership resource on data.gov.in
(`ridership-data-monorail-01-10-2024-21-09-2025`, daily line totals for Metro 2A, Metro 7 and
the Monorail, 2024-10-01 → 2025-09-21, 13 KB). It was reviewed through an archived copy; the
sandbox had no route to `data.gov.in` (TLS handshake failures through every available proxy),
so the file was never hashed here and its resource-level licence field was not visible. It is
listed as a candidate with `prediction_enabled: false`: no station identifier, unclear bulk
reuse terms, unreachable at build time.

Everything else Mumbai-side was refused for a stated reason — operator dashboards with no
export (MMMOCL ridership page is a Looker Studio embed), press-release and annual division
aggregates (Western Railway 969.805 M passengers in 2022-23 etc.), KML/geometry-only open
data (`data.opencity.in/…/mumbai-suburban-network-2025`), GTFS schedules, and academic
repositories containing DPR *forecasts*. Full reasoning, per source, is in
[`future-prediction-dataset-research.md`](future-prediction-dataset-research.md).

## 8. What would make Mumbai trainable

A station-day count for each surveyed station, published or collected on a schedule. The
append-only collector implements the accumulation half of that:

```bash
python3 scripts/collect_transit_observations.py --source manual \
    --input my_station_day_counts.csv --system-id mumbai-suburban-railway \
    --source-id mumbai-operator-weekly-return
python3 scripts/collect_transit_observations.py --status
```

Input columns: `station_id, station_name, date, demand_count` (+ optional `line_id,
direction, time_interval, measure, service_type, note`). It stores each run as an immutable
JSONL file plus the raw payload's SHA-256, refuses duplicate `(source, station, day,
measure)` keys, refuses negative or unparseable values, never fills a missed day, and
reports gaps on request. Roughly 90 contiguous days of station-day counts across at least 10
stations would clear every currently failing criterion except the licence one; that licence
question is MRVC's to answer, and this project will not resolve it by assumption.
