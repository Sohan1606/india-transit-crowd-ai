# Future-prediction dataset research — findings

Research question: **can this product, for a selected Indian public-transport system, produce
a genuine machine-learned prediction of passenger demand for a time that has not happened
yet, based on actually observed passenger data?** Not "can we display a number", and not
"can we replay a past observation and call it a forecast".

Working date for every "today/today−n" statement: **2026-10-06 (Asia/Kolkata)**.
Environment: this repository's sandbox, with the network access it has. Every claim below is
either (a) a file inside this repository, (b) a page or API response retrieved during this
research pass, or (c) explicitly marked as *not verifiable from here*.

---

## Part A — Method

1. The uploaded 38-page MRVC / Wilbur Smith *Executive Summary* PDF was converted to text
   page by page and read in full (all tables E-1 … E-22 plus the narrative), so that claims
   about the document come from the document.
2. Every candidate source was then pursued on the same terms: what does the file contain, at
   what granularity, over how many distinct periods, for which stable entity ids, under which
   licence — and only then, can it be a supervised target.
3. Sources probed (retrieved 2026-10-06 unless noted): `data.gov.in` (+ `api.data.gov.in`,
   `www.` variants, HTTP and TLS 1.2 forced, three public read-through proxies, and the
   Wayback CDX index for the domain), `mrvc.in` / `mrvc.co.in`, `mmrda.maharashtra.gov.in`,
   `data.maharashtra.gov.in`, `data.mumbai.gov.in`, `openbmc.in`, `mahametro.gov.in`,
   `mmrc-mumbai.in`, `mmmocl.co.in`, `mumbaimetroone.com`, `mmropl.com`,
   `indianrailways.gov.in`, `data.opencity.in` (CKAN `package_search`/`package_show`),
   `otd.delhi.gov.in`, Delhi Transport Stack, `chennaimetrorail.org`,
   `commuters-data.chennaimetrorail.org`, `commuters-dataapi.chennaimetrorail.org`,
   `kochimetro.org`, `hmrl.co.in`, GitHub (repository search, git trees, READMEs, raw
   content, commit metadata), Zenodo / DataCite / Figshare / Dataverse API searches,
   Mendeley InData (API requires OAuth — not attempted further), Kaggle dataset pages,
   and English-Wikipedia articles for the operator-level annual aggregates.
4. Rejection was recorded with a reason, not silence, because the negative result is the
   deliverable for most Indian cities.

---

## Part B — Twenty findings

**1. The uploaded PDF is a survey cross-section, not a dataset in the time-series sense.**
249 observed/derived records were extracted with per-row table and page citations
(`data/research/mumbai_suburban_rail_pdf_observed.csv`, SHA-256 `ad7913f9…9edcb`). Fieldwork
ran 2011-11-22 → 2012-03-15, plus a Virar–Dahanu Road section on 2013-06-17/18.

**2. Its real time depth is five dates.** The only distinct calendar dates anywhere in the
extract are 2011-12-08, 2012-02-11, 2012-11-21, 2013-06-17, 2013-06-18. 50 stations are
named, 8 line labels and 42 interval labels appear, and only the ticket-queue measure
(Table E-22) carries a dated survey day. No station is measured twice.

**3. Much of the quantitative content is derived, and the document says so.** Tables E-2/E-3
publish expansion factors (coach → train, then sampled services → all peak services), so
E-4…E-8 are model-expanded estimates of one weekday, recorded as
`observation_type = derived_from_sample_survey`.

**4. Two numbers in the document are internally inconsistent, and the inconsistency is
load-bearing.** Table E-1's station roster names 46 stations while the same table's
methodology row says "37 selected stations"; the in-train survey is 300 services in Section
III and 310 in Table E-1. Both readings are stored in the metadata; the extract uses the
figures the tables themselves print.

**5. The 2016/2021/2031 figures are model output and were quarantined.** Table E-13 (p. 25)
daily trips in lakhs — 2012: 38.15 / 26.34 / 18.76 / 83.25; 2016: 41.19 / 29.86 / 24.60 /
95.65; 2021: 44.65 / 33.85 / 30.82 / 109.32; 2031: 51.14 / 40.84 / 42.67 / 134.65 — is
written to a separate CSV with `classification = "HISTORICAL STUDY MODEL OUTPUT"` and
`eligible_as_supervised_label = False`. 2016 is an *interpolation* (the report states no model
forecast existed for that year) and off-peak demand is *assumed* at 15%. Training on this
sequence would make a model imitate a 2008-vintage travel-demand model — circular
pseudo-labels, and unverifiable by construction.

**6. No licence or reuse statement is printed in the executive summary.** Ownership is
asserted by the cover page only (MRVC / Wilbur Smith Associates). The PDF is therefore not
redistributed by this project, and the extract is marked reference-only pending MRVC's terms.

**7. MRVC publishes no machine-readable ridership history.** `mrvc.co.in` does not resolve
from here; `mrvc.in` answered only through cached indexes; a Wayback CDX query for the domain
timed out at 40 s. No open-data endpoint, bulk CSV, API or archive was found on any MRVC
property. What the corporation publishes about suburban ridership is narrative and press
material.

**8. Indian Railways / Western Railway / Central Railway publish annual and quarterly
aggregates only.** `indianrailways.gov.in` was unreachable from this environment. The best
longitudinal figures found were aggregate: Wikipedia's Western-line table (969.805 M
passengers in 2022-23; 1,279.4 M in 2016-17), a Western Railway Mumbai Central division note
(Q1 FY26 25.60 Cr vs Q1 FY25 26.04 Cr, −1.71%), and older division comparisons (FY20 124.15 Cr
vs FY23 96.99 Cr). An annual or quarterly total per division cannot supervise a per-station,
per-interval model; using it would mean inventing the distribution inside each period.

**9. Mumbai's open-data portals are mostly not running.** `data.maharashtra.gov.in`,
`data.mumbai.gov.in` and `mmrda.maharashtra.gov.in` did not resolve; `openbmc.in` (the BMC's
open-data portal) did not resolve either. `data.opencity.in` responded, and its Mumbai
suburban-rail item (`mumbai-suburban-network-2025`) is KML geometry — network shape, zero
demand values.

**10. Exactly one genuine longitudinal *observed* Mumbai transit series was found.**
`https://www.data.gov.in/resource/ridership-data-monorail-01-10-2024-21-09-2025` —
MMRDA/NDSAP daily ridership for Metro 2A, Metro 7 and the Monorail, 2024-10-01 → 2025-09-21,
granularity "Daily", columns `Date, Line, Paper QR, NCMC and Other Trip, Total Ridership`,
13 KB, and the page states "API for this resource does not exist". Reviewed via the archived
copy dated 2025-12-06.

**11. That resource could not be retrieved or hashed from here, and its licence is unresolved.**
`www.data.gov.in` failed the TLS handshake (`error:0A000126`); forcing TLS 1.2 returned 503;
plain HTTP failed with errno 52; `api.data.gov.in` did not resolve; r.jina.ai returned 503 and
allorigins/codetabs returned 522; the Wayback CDX entry has no archived *download* URL. So:
documented, not bundled, and not used. It is also line-level, with no station identifier, so
even with the file it could only ever support a separate line-level daily model.

**12. MMMOCL's ridership page is a dashboard, not data.**
`https://www.mmmocl.co.in/ridership-information` embeds a Looker Studio report. The embed
serves a template gallery to non-browser clients and exposes no documented export, no bulk
endpoint and no licence text. Scraping a BI tool's internal RPC would produce numbers whose
provenance and terms cannot be stated, so it is a *collector target*, not a dataset.

**13. Mumbai Metro figures in circulation are press aggregates.** Wikipedia's summary
(77 stations, ~10.57 lakh/day for FY 2025-26; ≈900 k/day in Oct 2025 with Blue Line ≈460 k)
and Jan-2026 reports on Line 3 (monthly 19.7 L → 46.56 L; Marol Naka 16.45 L) are network or
station totals released to media. They have no interval dimension and no stable per-day series
to learn from.

**14. Academic/repost candidates were checked and refused.** `uwaterregistry/Project-529`
holds MMMOCL DPR **forecasts**; `princek9109/Mumbai-Suburban-Rail-Project` and
`aarizkhandata/metro-fuel-analysis` are timetable/fuel analyses; Kaggle's
`prasad22/mumbai-local-train-dataset` is a synthetic schedule-style table. Zenodo, DataCite,
Figshare and Dataverse searches for Mumbai ridership returned nothing with observed station
counts — closest hit, `10.5281/zenodo.21470227`, is an MTA-plus-synthetic dataset. Mendeley
InData needs OAuth and was not pursued.

**15. Conclusion for Mumbai suburban rail: the honest answer is "not yet".** It fails 6 of
10 gate criteria, including the two decisive ones (`genuine_future_test_period_exists`,
`target_values_are_actual_observations`). A model trained on it would either replay a single
weekday or learn a 2008 model's extrapolations. The repository therefore ships the canonical
cross-section, the quarantined model output, the gate with per-criterion evidence, and a
collector — and refuses to call that a future-forecasting capability.

**16. Bengaluru is the only station-**hour** observed source in India that is openly licensed,
and it is finite.** The verified `Vonter/bmrcl-ridership-hourly` snapshot (ODbL-1.0, ZIP SHA-256
`a0469f33…`) gives 92,280 station-hours across 83 stations, 2025-08-01 → 2025-09-30 with
August 19–31 absent in the source. OpenCity mirrors the same RTI-derived data
(`bmrcl-station-wise-ridership-data`, CC BY-NC / CC BY-NC-SA 4.0, credited to Vivek Mathew).
The upstream repository contains only `raw/august/` and `raw/september/`, so the window cannot
be extended from that source; the model stays a two-month, two-period snapshot and its
champion is measured accordingly (test MAE 44.58, R² 0.9596 on held-out hours).

**17. Chennai Metro Rail's portal is a live, machine-readable, per-station daily feed — and
that made a new family possible.**
`commuters-dataapi.chennaimetrorail.org/api/PassengerFlow/{stationData,allTicketCount,hourlybaseddata}/{0|1}`
returns JSON directly (no auth, no key; a browser User-Agent suffices). `stationData/1` is a
per-line block: `categories` = station labels, `series[name="Total"].data` = that station's
count for the day. The portal serves only the previous complete day, so history requires a
collector.

**18. A community collector supplies the missing history, with verifiable provenance.**
`PratyushBalaji/chennai-metro-ridership-tracker` appends the portal response daily via GitHub
Actions. At pinned commit `72ee5ea…` the archive holds **255 consecutive days** (2026-01-24 →
2026-10-05), 10,965 station-day rows, 41 stations on 2 lines, zero date gaps, zero duplicate
station-days. Its MIT licence covers the code only, so the data is fetched and checksum-verified
at prepare time rather than bundled (`data/licenses/CMRL-DATA-NOTICE.md`).

**19. Measure semantics were tested empirically before anything was modelled.**
Summing station `Total` per day against the system `allTicketCount` for the same day gives a
mean ratio of **1.0061** (min 0.9502, max 1.2106) across all 255 days; the live day
2026-10-05 gives 381,903 / 396,919 = 0.9622. ≈1.0 means one counting event per journey, i.e.
**entries**, not entries+exits (which would sit near 2.0); the days above 1.0 are explained by
Chennai Central and Alandur being reported once per corridor. Consequently interchanges are
kept as two line-scoped entities and never summed. `hourlybaseddata` is **network-level** (≈22
buckets/day), so Chennai gets **no** station-hour data; the tracker's `PHPDT/
ChennaiMetro_Daily_PHPDT.csv` (adjacent-pair peak-hour-per-direction, 798 KB) is a
plausible future feature source and is deliberately unused here.

**20. Day granularity is a real forecasting capability, not a downgrade, and it is the only
granularity India offers at station level today.** No Indian source in this search publishes
minute-level or 15-minute counts anywhere, so those horizons were dropped as specified. With
255 days × 43 station-line entities the Chennai family supports a chronological
158/34/35-day split, a next-day target, and — critically — a *future* date beyond the frontier
that can be scored when the source catches up. Measured recursively (see
`docs/chennai-metro-dataset.md` §6): MAE 902.29, RMSE 1402.51, R² 0.8691, sMAPE 16.17% over a
69-day projection that re-feeds its own forecasts, versus MAE 929.78 for a same-weekday seasonal
naive baseline — so the learned model beats the baseline on genuinely unseen days.
Deliverable for the Mumbai gap: `scripts/collect_transit_observations.py` records
`source timestamp, collection timestamp, value, source id, raw payload SHA-256`, refuses
duplicates and negatives, never interpolates, and reports gaps — a station-day count kept
90+ days deep is what would let Mumbai pass.

---

## Part C — Answers to the seven final success questions

**Q1. Did we find newer genuine observed Mumbai passenger-demand data?**
Newer *observed* Mumbai transit data: yes, one resource — the MMRDA/NDSAP daily line-level
series 2024-10-01 → 2025-09-21 on data.gov.in (finding 10). Newer observed **Mumbai suburban
railway station-level** data: **no** — nothing published, and nothing findable in operator
portals, open-data portals, research repositories or press releases (findings 7–9, 13, 14).
The data.gov.in file was additionally not retrievable or hashable from this environment and
carries no visible resource-level licence (finding 11), so it is documented, not used.

**Q2. Is the data at a granularity that supports the model's prediction target?**
For Mumbai suburban rail, no: one typical weekday per survey window, no repeat dates, so no
next-hour or next-day target exists (findings 1–2). For the family this project added, yes:
Chennai gives station × day, which supports a next-**day** target. Hour-of-day questions are
answered only by the Bengaluru family, and the Chennai API refuses them (409) instead of
splitting a daily total into fake hours. Minute-level and 15-minute targets were rejected
because no such labels exist anywhere in the searched sources (finding 20).

**Q3. Can the model be trained on past observations and evaluated on a future period?**
Yes, for Bengaluru (hour) and Chennai (day). Chennai: 6,794 training rows over 158 days,
1,462 validation rows over 34 days, 1,505 test rows over the final 35 days, champion selected
on validation only, test reported once, and an additional 69-day recursive projection
(2026-07-29 → 2026-10-05) scored with no post-cutoff observation entering the features —
MAE 902.29. A functional leakage probe (alter the target day, require every row at or before
it to be byte-identical) runs in CI for both granularities.

**Q4. Does the product answer a date/time that has not happened yet, and can that answer be
verified later?**
Yes for `chennai-cmrl-metro`. The data frontier is 2026-10-05 and today is 2026-10-06, so
`/api/predict` with `target_date` ≥ 2026-10-06 is a genuine future forecast;
`/api/future-preview?days=N` projects the next N unobserved days; `/api/source-gap` states
how far the archive lags. Verification is mechanical: when the source publishes that day, the
collector/prepare step brings the observation in and the same evaluation script can score the
stored forecast. Requests for dates at or before the frontier are answered but labelled
`forecast_kind: "historical_replay"`, `is_model_forecast: false`, with the reason in
`forecast_note` — a replay is never presented as a forecast.

**Q5. Is the modelled-forecast content from the PDF kept away from training?**
Yes. E-13's 2012/2016/2021/2031 values live only in
`data/research/mumbai_suburban_rail_MODELLED_od_forecast.csv`, every row flagged
`eligible_as_supervised_label = False` and `classification = "HISTORICAL STUDY MODEL OUTPUT"`,
with the rejection reason in the sidecar. No file under `ml/` or `scripts/` references that
CSV except the extractor that writes it, and a repository-wide test fails if one ever does.
Permitted use is limited to a labelled historical-study benchmark, as stated in the dataset doc.

**Q6. Which system in this product can genuinely predict future demand, and which cannot?**
**Can:** `chennai-cmrl-metro` (CMRL, station-day entries, 255 days, next-day horizon up to 60
days) and `bengaluru-namma-metro` (BMRCL, station-hour boardings, next-hour horizon up to 336
hours) — unchanged, still served, still measured. **Cannot, with the reason recorded:**
Mumbai suburban railway (cross-section only, gate-rejected), Mumbai Metro/Monorail (line-level
daily only, licence and retrieval unresolved), DMRC (hourly footfall is approval-gated; the
Delhi Transport Stack exposes no public JSON API — six plausible paths returned 404),
DTC/PMPML/BEST/TMT/KDMT (GTFS schedules and, for OTD, a static-download page whose terms
require stating purpose and may require permission), HMRL and KMRL (GTFS static only, with
KMRL's attribution terms quoted from its open-data page). The catalog states each of these as
`prediction_available: false` with a specific `prediction_unavailable_reason`; the API returns
409 for them rather than a number.

**Q7. Is the dataset big/long enough to be credible, and how is its size reported?**
Stated as measured, never rounded up. Chennai: **10,965** observed station-day rows, 43
entities, **255** consecutive days (2026-01-24 → 2026-10-05), 0 filled cells, 0 reported
zeros, 227 supervised target days after the 28-day history requirement — i.e. roughly 8.4
months, no annual seasonality, ~1 day of publication lag. Bengaluru: 92,280 station-hours,
83 stations, 61 days with a documented 13-day hole. Mumbai: **249** records on **5** dates.
Every count above is reproducible: `python3 scripts/validate_demand_dataset.py --system-id
chennai-cmrl-metro` recomputes rows, entities, coverage, gap cells, partition sizes, the
leakage probe and the future-test-period check from the files themselves.

---

## Appendix — sources and dispositions

| source | what it offers | disposition |
|---|---|---|
| MRVC / Wilbur Smith Executive Summary PDF (2013) | tables E-1…E-22 | extracted; 249 observed/derived records + quarantined model output; gate-rejected |
| `data.gov.in` MMRDA daily ridership 2024-10-01→2025-09-21 | line-level daily totals + ticket types | documented as the only newer observed Mumbai series; unreachable + licence unresolved → not bundled, not modelled |
| `mmmocl.co.in/ridership-information` | Looker Studio dashboard | no export/licence → collector target only |
| `mrvc.in`, `mrvc.co.in`, `mmrda.maharashtra.gov.in`, `data.maharashtra.gov.in`, `data.mumbai.gov.in`, `openbmc.in`, `mahametro.gov.in`, `mmrc-mumbai.in`, `indianrailways.gov.in` | operator/portal properties | unreachable or offline from this environment; recorded as unverified rather than treated as absent evidence |
| Wikipedia: Western line annual table; Mumbai Metro summary | annual/network aggregates | usable for context only; never as labels |
| Press releases (Hindustan Times 2024-10-28; Free Press Journal / News18 Jan 2026; division notes) | monthly/station totals in lakhs | context only; no interval dimension |
| `Vonter/bmrcl-ridership-hourly` (ODbL-1.0), OpenCity BMRCL mirror (CC BY-NC) | 92,280 station-hours | the existing Bengaluru family; preserved, unmodified, and re-verified by the same gate |
| `commuters-dataapi.chennaimetrorail.org` + `PratyushBalaji/chennai-metro-ridership-tracker` @ `72ee5ea` | per-station daily JSON, 255-day archive | **new accepted family**; data fetched on demand, SHA-256 pinned, not redistributed |
| `chennaimetrorail.org/passenger-traffic` | 404 (the portal lives on the `commuters-data` host) | noted so the wrong host is not re-probed |
| Kaggle `subhashb21022/cmrl-datasets` | model output + tiny counts | refused — not observed data |
| `uwaterregistry/Project-529`, `princek9109/…`, `aarizkhandata/…`, Kaggle `prasad22/…` | DPR forecasts, timetables, synthetic tables | refused — not observed demand |
| Zenodo `10.5281/zenodo.21470227`, DataCite/Figshare/Dataverse searches | transit ML sets | refused — MTA + synthetic, no Indian station counts |
| Delhi Transport Stack, `otd.delhi.gov.in` | DMRC hourly footfall (approval-based), static GTFS | not usable; GTFS is schedule, never a demand target |
| `kochimetro.org/open-data`, `hmrl.co.in` GTFS announcement | static GTFS | discovery only; licence terms recorded where published |

### What still blocks a Mumbai prediction model

1. **A publisher of station-day (or station-hour) counts.** MRVC / Western / Central Railway,
   or MMRDA for metro assets, would have to publish a repeated series; a dashboard is not a
   series.
2. **A licence or written permission.** The PDF carries none; data.gov.in's resource page did
   not expose one in the view available here.
3. **Length.** ≥ 90 contiguous days for a usable split at day granularity; ≥ 30 days for hour
   granularity (the Bengaluru precedent). The collector exists to start that clock.
4. **Entity stability.** The 2011-12 roster (37 vs 46 stations) must be reconciled against
   today's station list before any two periods can be compared.
