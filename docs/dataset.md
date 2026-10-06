# Data sources, provenance and licensing

**Review date: 2026-10-06.** The prediction model in this release is trained only from the verified BMRCL/Namma Metro station-hour observed-demand archive. Other Indian sources below are explicitly classified as candidates or service/network discovery; they are not silently joined to the target data.

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

## Other observed-demand sources reviewed

These records establish leads for future, source-specific adapters. **None is enabled for prediction in this build.** A candidate must be reproducibly downloadable, have a well-defined observed-demand target and timezone/resolution, have re-use terms reviewed, and pass data-quality and chronological evaluation before registration.

| City / system | Provenance and published granularity | Access and rights review | Forecast suitability / decision |
|---|---|---|---|
| **Delhi Metro (DMRC)** | Delhi Transport Stack catalog describes hourly station entry and exit footfall. The catalog labels the item approval-based Excel. OTD separately exposes static DMRC GTFS, which is stations/routes/schedules, not footfall. | Footfall file not downloaded; approval, reproducible export and dataset-specific re-use rights need confirmation. No private key or account was assumed. | The strongest next station-hour candidate if an authorized file is obtained and validated. **Not enabled.** |
| **Mumbai MMRDA Metro 2A / 7 / Monorail** | OGD resource page: “Ridership Data Monorail from 01-10-2024 to 21-09-2025”; daily granularity; fields include date, line, Paper QR, NCMC/other-trip categories and total ridership. The page lists a 13 KB CSV; reference URL and webservice/API fields are `NA`. | <https://www.data.gov.in/resource/ridership-data-monorail-01-10-2024-21-09-2025>. OGD platform terms refer users to each resource's license metadata and state that portal content is under Government Open Data License—India (GODL-India); the reviewed resource view did not show an individual license field. Recheck the live record and attribution before redistribution. The downloadable file has not been bundled or used for training. | Real observed demand at **daily line** level, but not station-hour. Could support a separately defined daily-line study after a reproducible file and license audit; **not** this model. |
| **Chennai Metro (CMRL)** | OpenCity, sourced to Government of Tamil Nadu, publishes monthly system totals from 2023–24 through June 2026. Resource page lists a 2.9 KB CSV and reports an August 3, 2026 update. | <https://data.opencity.in/dataset/chennai-metro-monthly-usage-data/resource/c63ef5a0-e7d2-49b3-9c88-5ca5ce309fcf>. Resource metadata shows `Other (Public Domain)`. Re-fetch the file and metadata before ingestion; the official passenger-flow visualization is not a bundled bulk-history dataset. | Credible monthly aggregate, but no station key or hourly resolution. Suitable for monthly trend/total analysis only; **not** a next-hour station target. |

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

## Reproducible commands

```bash
# From the repository root
python scripts/download_data.py       # downloads pinned archive; SHA-256 is enforced
python scripts/prepare_data.py        # writes normalized CSV + provenance sidecar
python scripts/train_models.py        # trains only a registered family
python scripts/evaluate_models.py     # replays persisted champion on held-out data
```

To use a different registered family, pass its normalized data with `--data` and its provenance sidecar with `--metadata`. The training registry rejects systems without a verified adapter/model-family entry. A source or license revision requires new review and a new pinned checksum; do not bypass the checksum to make a changed file appear equivalent.
