# Data sources, provenance and licensing

**Review date: 2026-10-06.** Prediction in this release is trained only from verified observed-demand archives, one per registered model family:

* **Bengaluru · BMRCL — station-hour boardings** (hourly family, unchanged by this work).
* **Chennai · CMRL — station-day entries** (day family; full write-up in
  [`chennai-metro-dataset.md`](chennai-metro-dataset.md)).

Two further systems were assessed and **refused**: the Mumbai suburban railway survey extract
(see [`mumbai-wilbur-smith-dataset.md`](mumbai-wilbur-smith-dataset.md)) and the MMRDA daily
line-level resource. Refusals are recorded with the failing criteria, and the other sources
below stay classified as candidates or network discovery. Families are never silently joined
to each other's target data, and `scripts/validate_demand_dataset.py` recomputes the gate for
any dataset that claims to be trainable.

## Enabled prediction source: BMRCL/Namma Metro

| Property | Verified value |
|---|---|
| Publisher / provenance | Bengaluru Metro Rail Corporation Ltd (BMRCL); upstream compilation by Vonter. Upstream repository says the underlying station-hour records were obtained through RTI. |
| Upstream repository | <https://github.com/Vonter/bmrcl-ridership-hourly> |
| Pinned commit | `6c44579b5ff3428a88bddc44baf84e436a940612` |
| Exact raw archive URL | <https://raw.githubusercontent.com/Vonter/bmrcl-ridership-hourly/6c44579b5ff3428a88bddc44baf84e436a940612/data/station-hourly.csv.zip> |
| Raw file in project | `data/raw/india/bmrcl-station-hourly.csv.zip` |
| Raw ZIP SHA-256 | `a0469f3365c53ca25d9aed5396775fc1c6018cfc0b93e245e8bc3e1c9524bd81` |
| Granularity | One record per observed station and source hour. |
| Measure | Source dictionary describes `Ridership` as passengers boarded at that station in that hour. It is not onboard load or physical occupancy. |
| Source columns | Semicolon-delimited CSV: `Date`, `Hour`, `Station`, `Ridership`. |
| Timezone | `Asia/Kolkata`; source date + hour is localized as station-local time. |
| Source periods | 2025-08-01 through 2025-08-18, and 2025-09-01 through 2025-09-30. August 19–31 is not present. |
| Observations | 92,280 station-hour rows, 83 stations, 48 distinct source dates, no duplicate station-hour keys. |
| Reported zeros / missing values | 18,200 explicit source zeros retained; 0 missing observations filled. Station records per date vary (68–83). |
| License | Open Database License (ODbL) 1.0, as documented by the upstream repository. |

The pinned raw ZIP was downloaded again from the exact raw GitHub URL and compared byte-for-byte with the bundled ZIP; both have the SHA-256 shown above. The source adapter verifies this pinned checksum during download. The exact ODbL text is preserved at [`../data/licenses/ODbL-1.0.txt`](../data/licenses/ODbL-1.0.txt). Attribution, share-alike and underlying-rights cautions are in [`../data/licenses/BMRCL-ATTRIBUTION.md`](../data/licenses/BMRCL-ATTRIBUTION.md).

### Normalized records

- Output: `data/processed/namma_metro_station_hourly.csv`.
- Sidecar: `data/processed/namma_metro_station_hourly.metadata.json`.
- Normalized CSV SHA-256: `9cbc3981092d42792a6c50a2af032cf3c6f018b8e41ed0aa297716e486adb062`.
- Canonical fields: `system_id`, `city`, `mode`, `operator`, `entity_id`, `entity_name`, `entity_type`, `timestamp`, `demand_count`, `measure`, `source_id`.
- IDs are stable normalized slugs derived from observed station names. Source rows are not expanded to create station-hours before a station appears.
- Explicit zeros remain observed zero counts. Absent hours are missing, not zero; no interpolation, forward fill or fabricated station record is added.

The final observed source timestamp is 2025-09-30 23:00 IST. Most station projections beyond that frontier are recursive calls to a one-hour model, bounded to 336 hours from that station's latest observed hour. The history includes a long August gap, a changing roster, and a short September holdout. It cannot establish current 2026 service conditions, annual seasonality, live demand, or generalization to other operators.

### ODbL and attribution

The database is used under ODbL-1.0. Keep the upstream attribution and license with the source and any adapted database; share adaptations to the database under the same license as required by ODbL, and indicate changes. The project preserves the license text and source notice, and records the source commit and both source/normalized checksums. The upstream repository cautions that some database contents may carry underlying BMRCL rights; this project does not assert BMRCL endorsement or a blanket waiver of those rights. See the attribution notice before redistribution. This documentation is not legal advice.

## Enabled prediction source: CMRL / Chennai Metro (station-day)

| Property | Verified value |
|---|---|
| Publisher | Chennai Metro Rail Limited (CMRL), via its public passenger-flow API `commuters-dataapi.chennaimetrorail.org/api/PassengerFlow/*`. |
| Historical archive | Community collector `PratyushBalaji/chennai-metro-ridership-tracker`, pinned commit `72ee5eadb6ca890bfd9900d6464a1a371566c86b`. |
| Raw file SHA-256 (at the pinned commit) | `ChennaiMetro_Station_Ridership.csv` `2630ea1b083e…709190`; `ChennaiMetro_Daily_Ridership.csv` `6f16712ee90a…a02bc`; `ChennaiMetro_Hourly_Ridership.csv` `4ae938c6c392…3f19e`. |
| Bundled in repository | **No.** `data/raw/` and the normalized CSV are git-ignored; `scripts/download_cmrl_data.py` + `scripts/prepare_chennai_data.py` regenerate them and verify the digests. |
| Granularity | One record per station-line entity per calendar day. |
| Measure | `daily_station_entries` — one counting event per journey at the station. Verified against the same day's system ticket count: mean ratio 1.0061 over 255 days (entries+exits would be ≈2.0). |
| Entities | 43 station-line ids for 41 physical stations; Chennai Central and Alandur are reported once per corridor and are kept as two entities, never summed. |
| Coverage | 2026-01-24 → 2026-10-05, 255 consecutive days, 10,965 rows, 0 missing station-days, 0 filled values, 0 source-reported zeros, no duplicate station-date keys. |
| Timezone | `Asia/Kolkata`, day-aligned at 00:00 local. |
| Licence / rights | The tracker's MIT licence covers its code only; CMRL asserts no bulk-reuse terms. Documented in [`../data/licenses/CMRL-DATA-NOTICE.md`](../data/licenses/CMRL-DATA-NOTICE.md); data is fetched, not redistributed. |
| Gate | All ten criteria pass → `data/research/chennai-cmrl-metro_validation_gate.json`. |

The last observed day (2026-10-05) is one day behind today, so a request for 2026-10-06 or
later is a genuine future forecast, bounded to 60 days of recursive projection and measured
recursively at MAE 902.29 / R² 0.8691 over a 69-day projection. Day granularity cannot answer
hour-of-day questions at all; the API returns 409 for a heatmap on this family rather than
dividing a daily total across hours.

## Other observed-demand sources reviewed

These records establish leads for future, source-specific adapters. **None is enabled for prediction in this build.** A candidate must be reproducibly downloadable, have a well-defined observed-demand target and timezone/resolution, have re-use terms reviewed, and pass data-quality and chronological evaluation before registration.

| City / system | Provenance and published granularity | Access and rights review | Forecast suitability / decision |
|---|---|---|---|
| **Delhi Metro (DMRC)** | Delhi Transport Stack catalog describes hourly station entry and exit footfall. The catalog labels the item approval-based Excel. OTD separately exposes static DMRC GTFS, which is stations/routes/schedules, not footfall. | Footfall file not downloaded; approval, reproducible export and dataset-specific re-use rights need confirmation. No private key or account was assumed. | The strongest next station-hour candidate if an authorized file is obtained and validated. **Not enabled.** |
| **Mumbai MMRDA Metro 2A / 7 / Monorail** | OGD resource page: “Ridership Data Monorail from 01-10-2024 to 21-09-2025”; daily granularity; fields include date, line, Paper QR, NCMC/other-trip categories and total ridership. The page lists a 13 KB CSV; reference URL and webservice/API fields are `NA`. | <https://www.data.gov.in/resource/ridership-data-monorail-01-10-2024-21-09-2025>. OGD platform terms refer users to each resource's license metadata and state that portal content is under Government Open Data License—India (GODL-India); the reviewed resource view did not show an individual license field. Recheck the live record and attribution before redistribution. The downloadable file has not been bundled or used for training. | Real observed demand at **daily line** level, but not station-hour. Could support a separately defined daily-line study after a reproducible file and license audit; **not** this model. |
| **Chennai Metro (CMRL)** — station-day | Official passenger-flow API (previous complete day only) plus the community daily archive described above. OpenCity separately publishes monthly system totals for 2023–24 → June 2026 (2.9 KB CSV, metadata `Other (Public Domain)`). | The **daily** source is enabled as its own family (fetched, checksum-pinned, not redistributed). The **monthly** aggregate is not re-fetched or merged: mixing a monthly network total with station-day counts would combine incompatible measures. | Daily station entries support a next-day forecast. Monthly totals support context only, never a next-hour station target. |
| **Mumbai Suburban Railway (MRVC / Wilbur Smith 2013)** | Extract of all quantitative tables from the Executive Summary PDF: 249 observed/derived records across 8 measures, 50 stations, 42 interval labels, with per-row table and page citations. | `data/research/mumbai_suburban_rail_pdf_observed.csv` + sidecar. The PDF prints no licence or reuse statement and is **not** redistributed. Re-download from MRVC before publishing any figure. | **Rejected for prediction** by 6 of 10 gate criteria: one typical weekday per survey window (no repeat dates), two-stage survey expansion for the hourly tables, licence unresolved. Accepted as a labelled historical baseline (peak-hour shape, station entry/exit structure, crowding ratios). Its 2016/2021/2031 OD forecast is quarantined as `HISTORICAL STUDY MODEL OUTPUT` and never used as a label. |

The candidate list returned by `GET /api/demand-sources` is also kept aligned with the reviewed sources above. Catalog presence is not model availability.

## Network and schedule references — discovery only

GTFS Schedule contains public-transport service descriptions such as agencies, routes, stops, trips and stop times. It does not contain these systems' observed passenger boardings, station footfall or vehicle occupancy. A schedule-only file is not accepted by the observed-demand adapter registry.

| System / source | Provenance, contents and access | License / reuse status | Product use |
|---|---|---|---|
| **Delhi city bus — Open Transit Data (OTD)** | Official Department of Transport, GNCTD / IIIT-Delhi. Static download page lists stops, routes, approximate stop times and trips; page says bus static data last updated June 20, 2024. OTD documentation warns stop times are rough estimates based on constant speed. <https://otd.delhi.gov.in/data/static/> and <https://otd.delhi.gov.in/documentation/>. | OTD Terms and Conditions apply: static access asks for basic user information; use of contents requires specifying purpose, manner, timeframe and identity, and DoT reserves a right to refuse permission. Real-time APIs are for authorized users with private-key access. <https://otd.delhi.gov.in/terms>. No private key, real-time feed or live position is used. | Bus route/stop/schedule discovery only; no ridership target. |
| **Delhi Metro (DMRC) — OTD static GTFS** | Official OTD DMRC static page lists stops, routes, approximate stop times and trips; page says last updated August 10, 2023. <https://otd.delhi.gov.in/data/staticDMRC/>. | The same OTD portal terms govern reuse. Separate hourly footfall is approval-based on Delhi Transport Stack and is documented above; it is not inferred from GTFS. | Metro station and schedule discovery only. No live positions or passenger-demand prediction. |
| **Mumbai-region BEST / TMT / KDMT — `croyla/mumbai-gtfs`** | Community repository says it builds GTFS feeds for BEST, TMT and KDMT and provides original/compatibility ZIPs. Latest reviewed feed commit: August 19, 2026. <https://github.com/croyla/mumbai-gtfs>. | GitHub identifies the repository license as MIT-0. Its README does not identify the upstream source of each feed or establish a separate authoritative data-rights grant. Do not treat the code-repository license as proof of underlying source rights; no feed is redistributed in this project. | Routes/trips/stops/schedules only; not observed passenger counts. |
| **Pune PMPML — `croyla/pmpml-gtfs`** | Community generator says it converts Apli-PMPML / Chartr API route, stop and schedule data into GTFS. The reviewed feed generation is dated September 6, 2026. <https://github.com/croyla/pmpml-gtfs/>. | Repository carries an MIT No Attribution code license. Its README documents API access but does not establish a separate authoritative transit-data reuse grant. No GTFS file is redistributed. | Schedule/network discovery only; no passenger-demand values. |
| **Kochi Metro (KMRL) open data** | Official KMRL page provides GTFS-static routes, schedules and fares. <https://kochimetro.org/open-data/>. | KMRL's posted terms grant free, non-exclusive use/adaptation/reproduction/redistribution, including commercial and non-commercial applications, subject to KMRL attribution (“Contains data provided by Kochi Metro Rail Limited”) and no implied endorsement. Terms can change. | Network and schedule discovery only; not boardings. |
| **Hyderabad Metro (HMRL) / Open Data Telangana** | HMRL announcement of November 25, 2025 reports publication of a GTFS dataset covering three corridors, 118 stations and 6,958 scheduled weekly trips. <https://hmrl.co.in/hyderabad-metro-rail-data-goes-live-on-google-maps/>. | The announcement describes the GTFS publication but does not pin a downloadable revision or state its data-reuse license. Recheck the portal/license before reuse; no feed is bundled. | Service/schedule discovery only; no observed-demand target or live-occupancy claim. |

## Auditing a supplied file first

Before anything is registered, `scripts/audit_demand_dataset.py` states what a candidate file actually
contains - read-only, writes nothing, safe to run twice:

```bash
python3 scripts/audit_demand_dataset.py --csv incoming.csv --json /tmp/audit.json
# or as a pre-flight inside the registration entry point:
python3 scripts/register_demand_dataset.py --csv incoming.csv ... --print-audit
```

It reports the inventory (rows, dtypes, cardinality, missingness, duplicate rows), what the file declares
about its own provenance (a `Data_Type = Synthetic` column is surfaced at the top, before any modelling
decision), the measured timestamp grid, the clock times that actually occur, per-entity coverage and
holes, which columns could be the demand target and why others were disqualified, what each
line/corridor/direction column does to the rows, and - the mandatory part - whether a precomputed
`Target_*` column reproduces the demand series shifted forward. A target column is accepted as ground
truth only when it matches `demand(t + k)` for a verified grouping and offset on at least 99.9 % of
aligned rows; otherwise the audit prints `INCONSISTENT` (or `UNVERIFIABLE` when the key structure does
not allow the check) and the column is excluded from the label, with the supervised target derived from
the chronological series instead.

On the Mumbai research extract the tool is honest about the reason it cannot be a forecasting source:
`measured period NONE - the modal spacing is 5616000s but accounts for only 25 % of gaps`, i.e. five
survey days, not a series.

## Registering another observed-demand dataset (adaptive path)

`scripts/register_demand_dataset.py` is the front door for a dataset nobody wrote an adapter for. It
adapts to the file instead of forcing the file to match the code, and it refuses rather than inventing:

```bash
python3 scripts/register_demand_dataset.py --csv incoming.csv --system-id pune-metro --city Pune \
    --mode METRO --operator Maha-Metro --source-id maha-afc --source-url https://example.org/afc \
    --licence "CC BY 4.0" --provenance-statement "Who counted, when, how." \
    --write --install-registry --train
```

1. **Profiling** (`ml/data_pipeline/profile.py`) decides the column roles from the data: parseable
   datetime share, distinct-per-row coverage, monotonicity, repeats per entity, integer share, range,
   variability, autocorrelation at the modal spacing. Header names only ever add a capped +/-0.30
   prior, never a decision. Consequences: `Date`/`Station`/`Total` in a CMRL export and
   `service_date`/`station_code`/`boarding_count` elsewhere both resolve; a per-row surrogate key is
   disqualified as a measure; a column whose header says `forecast`/`predicted`/`modelled`/`simulated`
   is disqualified as a label; a small-integer code column is disqualified as a demand count.
2. **Granularity is measured, not declared.** The modal timestamp spacing sets the period (5 minutes
   to 7 days are supported); `--granularity` may only confirm it. A 15-minute file is profiled,
   normalized and gated with the period-aware feature schema in `ml/features/periodic.py` (lags 1 /
   1 week / 2 weeks / 4 weeks at that period), but training and serving are implemented for `day` and
   `hour` only - other periods are refused at that step with a reason instead of being answered with a
   day model.
3. **Semantic validation**: two or more near-tied candidate measures -> refusal listing them, never a
   guess; an additive relation between candidate columns (entries + exits = total) is reported and the
   columns are never summed into one target; missing entities and irregular spacing are counted, not
   filled; `clean_normalized_demand` enforces period alignment, whole non-negative counts, one
   system/city/mode/operator/entity-type per family and one record per entity-period.
4. **Normalization** to the canonical schema in `data/processed/<system>_demand_timeseries.csv` plus a
   `.metadata.json` sidecar carrying the chosen mapping, the profiler scores, both SHA-256 digests and
   the provenance fields.
5. **The ten-criterion gate** (`scripts/validate_demand_dataset.py`) runs on the normalized file. The
   gate is a conjunction: anything less than 10/10 is not registered, and the report is kept either way
   at `data/processed/<system>_validation_gate.json`.
6. **Registration** writes `data/registry/model_families.json` (read by `ml/training/registry.py`; a
   JSON family can add a system but can never replace a code-defined one), then `--train` runs the
   offline trainer, which saves model + preprocessor + config + metadata + training cut-off + horizon
   bands into `backend/models/<system_id>/`.

**Synthetic and simulated files are development input only.** A dataset declared
`--dataset-class synthetic_development|simulated|modelled_output|historical_study_output` can be
profiled and gated - which is exactly how the two teammate 365-day synthetic CSVs were tested - but it
fails `target_values_are_actual_observations`, is never registered as a served family, and is written
under `data/development/` instead of `data/processed/`. Registering one requires the explicit
`--allow-development-family` flag, which marks it `development_only: true` (`served_as: internal`) — `backend/app/main.py`
skips, so no endpoint can serve it. The synthetic fixtures themselves are not redistributed here.

### Choosing how a registered family may be served

`--serve-as` decides the serving mode, and the mode decides what the gate must have shown:

| Mode | Data it accepts | Gate requirement | What the API does |
| --- | --- | --- | --- |
| `production` | a dataset class that claims observed ground truth | every criterion, including `target_values_are_actual_observations` | normal answers |
| `demo` | a dataset that admits it is *not* observed (synthetic / simulated / modelled / other) | every criterion except `target_values_are_actual_observations`, and that must be the only failure | answers carry `data_class: synthetic_development` and the disclosure sentence; metadata sets `metrics_are_demonstration_only: true` |
| `internal` | anything (fixtures, development runs) | none | never built into the app: `backend/app/main.py` skips it |

`auto` (the default) picks `production` for an observed class and `internal` otherwise, so nothing becomes
public by accident. Registering an observed-class dataset as `demo` is refused: a verified dataset must not
be hidden behind a demonstration label any more than a synthetic one may be dressed as verified.

## Reproducible commands

```bash
# From the repository root — Bengaluru (hour-granularity family)
python scripts/download_data.py       # downloads pinned archive; SHA-256 is enforced
python scripts/prepare_data.py        # writes normalized CSV + provenance sidecar
python scripts/train_models.py        # trains only a registered family
python scripts/evaluate_models.py     # replays persisted champion on held-out data

# Chennai (day-granularity family)
python3 scripts/download_cmrl_data.py                                  # pinned + SHA-256 verified
python3 scripts/prepare_chennai_data.py                                # canonical record contract
python3 scripts/validate_demand_dataset.py --system-id chennai-cmrl-metro   # the 10-criterion gate
python3 scripts/train_chennai_models.py --target-date 2026-10-07       # benchmarks + future snapshot

# Any other system: collect observations until a series exists (nothing is interpolated)
python3 scripts/collect_transit_observations.py --source cmrl
python3 scripts/collect_transit_observations.py --status
```

To use a different registered family, pass its normalized data with `--data` and its provenance sidecar with `--metadata`. The training registry rejects systems without a verified adapter/model-family entry. A source or license revision requires new review and a new pinned checksum; do not bypass the checksum to make a changed file appear equivalent.
