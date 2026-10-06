# BMRCL/Namma Metro dataset attribution and reuse notice

The bundled historical station-hour dataset is republished from **[`Vonter/bmrcl-ridership-hourly`](https://github.com/Vonter/bmrcl-ridership-hourly)** at upstream commit **`6c44579b5ff3428a88bddc44baf84e436a940612`**. The upstream repository describes the ridership records as having been obtained through RTI and documents the periods 1–18 August 2025 and 1–30 September 2025. It describes `Ridership` as passengers boarded at a station in the source hour.

## Attribution

> Contains BMRCL station-hour ridership data obtained through RTI and compiled/published by Vonter in [`bmrcl-ridership-hourly`](https://github.com/Vonter/bmrcl-ridership-hourly), pinned to commit `6c44579b5ff3428a88bddc44baf84e436a940612`. Adapted normalized database and accompanying database metadata are made available under the Open Database License (ODbL) 1.0.

The upstream repository provides its database under **ODbL-1.0**. The full license text is included as [`ODbL-1.0.txt`](ODbL-1.0.txt); see also <https://opendatacommons.org/licenses/odbl/1-0/>. Reuse and redistribution of the database and adapted databases must follow the license's attribution and share-alike requirements.

## Adaptations made in this project

- Converted the upstream semicolon-delimited CSV fields (`Date`, `Hour`, `Station`, `Ridership`) into the shared normalized transit-demand record contract.
- Converted each local date/hour to an ISO timestamp using `Asia/Kolkata` and assigned stable station IDs.
- Preserved source-reported zeros as observed values.
- Preserved absent station-hours as missing; **no absent rows were zero-filled or interpolated**.
- Did not add schedules, synthetic passenger counts, capacity, train positions, occupancy, or current-service claims.

The pinned raw archive's SHA-256 is recorded in `data/processed/namma_metro_station_hourly.metadata.json`. The normalized CSV's SHA-256 is recorded in the same sidecar.

## Rights caution

The upstream repository notes that some contents in the database may be copyrighted by **Bengaluru Metro Rail Corporation Ltd (BMRCL)**. This project makes no claim of BMRCL endorsement, public-domain status for underlying source material, or blanket waiver of rights. The repository's ODbL grant and the upstream rights note are both preserved here. Obtain legal advice and confirm rights with the relevant source/rights holder before republishing beyond the license grant or using the data in a commercial service. This notice is not legal advice.
